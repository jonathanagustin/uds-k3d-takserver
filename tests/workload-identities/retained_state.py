# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Private invariants and exact retained-application cleanup, never Core cleanup."""
import base64
import hashlib
import json
from pathlib import PurePosixPath
import re
import shlex
import ssl
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
import yaml

APP_RELEASES={'takserver':{'takserver','uds-takserver-config'},'cloudtak':{'uds-cloudtak'}}
GENERATED_SECRETS={'takserver-ca-key','takserver-certs','tak-health-client'}

def require(value,message):
    if not value:raise ValueError(message)

def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def resource_record(obj):
    meta=obj['metadata']
    require(meta.get('namespace') in APP_RELEASES and not meta.get('deletionTimestamp'),'retained resource outside live application')
    return {'kind':obj['kind'],'name':meta['name'],'namespace':meta['namespace'],'uid':meta['uid'],'resourceVersion':meta['resourceVersion'],
            'metadataSHA256':sha({k:meta.get(k) for k in ('name','namespace','uid','labels','annotations','ownerReferences')})}

def hooks(driver):
    text=driver.command(['helm','--kube-context','k3d-uds','get','hooks','uds-takserver-config','-n','takserver'])
    objects=[obj for obj in yaml.safe_load_all(text) if isinstance(obj,dict)]
    secret=next(obj for obj in objects if obj.get('kind')=='Secret' and obj['metadata']['name']=='takserver-keystore')
    annotations=secret['metadata'].get('annotations',{})
    require(annotations.get('helm.sh/hook')=='pre-install,pre-upgrade' and annotations.get('helm.sh/hook-delete-policy')=='before-hook-creation','stored keystore hook ownership differs')
    role=next(obj for obj in objects if obj.get('kind')=='Role' and obj['metadata']['name']=='takserver-cert-init')
    named={name for rule in role['rules'] if rule.get('resources')==['secrets'] for name in rule.get('resourceNames',[])}
    require(GENERATED_SECRETS|{'takserver-keystore'}<=named,'stored source-generator RBAC differs')
    job=next(obj for obj in objects if obj.get('kind')=='Job' and obj['metadata']['name']=='takserver-cert-init')
    require(job['spec']['template']['spec']['serviceAccountName']=='takserver-cert-init','stored source generator identity differs')
    return {'storedHooksSHA256':hashlib.sha256(text.encode()).hexdigest(),'sourceGeneratorJobSHA256':sha(job),'keystoreHookSHA256':sha(secret)}

def claim_parent(driver,pvc):
    name=pvc['metadata']['name'];namespace=pvc['metadata']['namespace'];matches=[]
    for stateful in driver.get('statefulsets',namespace=namespace)['items']:
        meta=stateful['metadata'];annotations=meta.get('annotations',{})
        if annotations.get('meta.helm.sh/release-name') not in APP_RELEASES[namespace] or annotations.get('meta.helm.sh/release-namespace')!=namespace:continue
        for template in stateful['spec'].get('volumeClaimTemplates',[]):
            prefix=template['metadata']['name']+'-'+meta['name']+'-'
            if name.startswith(prefix) and re.fullmatch(r'[0-9]+',name[len(prefix):]):matches.append((stateful,template))
    require(len(matches)==1,'PVC is not a unique claim of the installed application chart')
    parent,template=matches[0]
    require(pvc['spec']['storageClassName']=='local-path-local' and pvc['status']['phase']=='Bound','PVC is not the disposable local trial data')
    volume=driver.get('persistentvolume',pvc['spec']['volumeName'],namespace='default')
    claim=volume['spec']['claimRef'];require(claim['namespace']==namespace and claim['name']==name and claim['uid']==pvc['metadata']['uid'],'PV claim ownership differs')
    return {'statefulSet':parent['metadata']['name'],'statefulSetUID':parent['metadata']['uid'],'claimTemplateSHA256':sha(template),
            'volumeName':volume['metadata']['name'],'volumeUID':volume['metadata']['uid']}

def mount(driver,pvc):
    matches=[];parent=claim_parent(driver,pvc)
    for pod in driver.get('pods',namespace=pvc['metadata']['namespace'])['items']:
        volumes={v['name'] for v in pod['spec'].get('volumes',[]) if v.get('persistentVolumeClaim',{}).get('claimName')==pvc['metadata']['name']}
        if volumes:
            owners=[x for x in pod['metadata'].get('ownerReferences',[]) if x.get('controller') is True]
            require(len(owners)==1 and owners[0].get('kind')=='StatefulSet' and owners[0].get('uid')==parent['statefulSetUID'],'PVC consumer is not its exact application controller')
        for container in pod['spec']['containers']:
            for item in container.get('volumeMounts',[]):
                if item['name'] in volumes and not item.get('readOnly'):
                    path=item['mountPath'];require(re.fullmatch(r'/[A-Za-z0-9_./-]+',path) and '..' not in PurePosixPath(path).parts,'unsupported PVC mount path')
                    matches.append((pod['metadata']['name'],container['name'],path))
    require(len(matches)==1,'PVC has no unique writable application mount')
    return matches[0]

def capture(driver):
    origin=hooks(driver);records=[]
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        for pvc in driver.get('persistentvolumeclaims',namespace=namespace)['items']:
            rec=resource_record(pvc);rec['parent']=claim_parent(driver,pvc);pod,container,path=mount(driver,pvc)
            sentinel=path.rstrip('/')+'/.uds-'+driver.state['trialID'];token=sha({'uid':rec['uid'],'trial':driver.state['trialID']})+'\n'
            script='umask 077; set -o noclobber; test -d '+shlex.quote(path)+'; test ! -L '+shlex.quote(path)+'; cat > '+shlex.quote(sentinel)
            result=driver.exec(pod,container,['/bin/bash','-ceu',script],token)
            require(result.returncode==0 and not result.stderr.strip(),'could not create exact owned PVC data sentinel')
            rec.update(sentinel=sentinel,sentinelSHA256=hashlib.sha256(token.encode()).hexdigest());records.append(rec)
    require(records,'application data claims missing')
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        referenced=set()
        for pod in driver.get('pods',namespace=namespace)['items']:
            for volume in pod['spec'].get('volumes',[]):
                if volume.get('secret'):referenced.add(volume['secret']['secretName'])
                for item in volume.get('projected',{}).get('sources',[]):
                    if item.get('secret'):referenced.add(item['secret']['name'])
            for container in [*pod['spec'].get('containers',[]),*pod['spec'].get('initContainers',[])]:
                for env in container.get('env',[]):
                    if env.get('valueFrom',{}).get('secretKeyRef'):referenced.add(env['valueFrom']['secretKeyRef']['name'])
                for env in container.get('envFrom',[]):
                    if env.get('secretRef'):referenced.add(env['secretRef']['name'])
        for secret in driver.get('secrets',namespace=namespace)['items']:
            name=secret['metadata']['name']
            annotations=secret['metadata'].get('annotations',{})
            if name in referenced or namespace=='takserver' and name in GENERATED_SECRETS|{'takserver-keystore'}:
                rec=resource_record(secret);rec['dataSHA256']=sha(secret.get('data',{}));rec['recreatedHook']=namespace=='takserver' and name=='takserver-keystore';records.append(rec)
    for config in driver.get('configmaps')['items']:
        if config['metadata']['name']=='cert-migration':
            rec=resource_record(config);rec['dataSHA256']=sha({'data':config.get('data',{}),'binaryData':config.get('binaryData',{})});records.append(rec)
    require(any(x['name']=='takserver-keystore' for x in records) and any(x['name']=='cert-migration' for x in records),'source-generated credential state missing')
    return {'source':origin,'records':records}

def verify(driver,proof,remove_sentinels=False):
    require(hooks(driver)==proof['source'],'stored source generator/hook changed across phase-only deployment')
    observations=[]
    for rec in proof['records']:
        current=driver.get(rec['kind'],rec['name'],namespace=rec['namespace']);meta=current['metadata']
        if not rec.get('recreatedHook'):require(meta['uid']==rec['uid'],'application invariant resource replaced')
        else:require(meta.get('annotations',{}).get('helm.sh/hook-delete-policy')=='before-hook-creation','keystore no longer source-owned hook')
        if rec['kind']=='PersistentVolumeClaim':
            require(claim_parent(driver,current)==rec['parent'],'data PVC/PV parent changed');pod,container,_=mount(driver,current)
            result=driver.exec(pod,container,['/bin/bash','-ceu','test ! -L '+shlex.quote(rec['sentinel'])+'; sha256sum -- '+shlex.quote(rec['sentinel'])])
            observed=result.stdout.split()
            require(result.returncode==0 and not result.stderr.strip() and len(observed)==2 and observed[0]==rec['sentinelSHA256'] and observed[1]==rec['sentinel'],'application PVC data sentinel changed')
            if remove_sentinels:
                result=driver.exec(pod,container,['/bin/bash','-ceu','rm -- '+shlex.quote(rec['sentinel'])]);require(result.returncode==0,'exact owned sentinel cleanup failed')
            observations.append({'kind':rec['kind'],'name':rec['name'],'namespace':rec['namespace'],'uid':meta['uid'],'volumeUID':rec['parent']['volumeUID'],'sentinelSHA256':observed[0]})
        else:
            value=current.get('data',{}) if rec['kind']=='Secret' else {'data':current.get('data',{}),'binaryData':current.get('binaryData',{})}
            require(sha(value)==rec['dataSHA256'],'application credential/certificate data changed')
            observations.append({'kind':rec['kind'],'name':rec['name'],'namespace':rec['namespace'],'uid':meta['uid'],'dataSHA256':sha(value),'recreatedHook':rec.get('recreatedHook',False)})


    return observations

def cleanup_snapshot(driver,proof):
    verify(driver,proof,remove_sentinels=True);result=[]
    for rec in proof['records']:
        if rec['kind']=='PersistentVolumeClaim' or rec['name'] in GENERATED_SECRETS|{'takserver-keystore','cert-migration'}:
            current=driver.get(rec['kind'],rec['name'],namespace=rec['namespace']);item=resource_record(current);item['origin']=proof['source']
            if rec['kind']=='PersistentVolumeClaim':item['parent']=claim_parent(driver,current)
            result.append(item)
    return result

def consumers_gone(driver):
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        require(all(not driver.get(kind,namespace=namespace)['items'] for kind in ('pods','deployments','statefulsets')),'application still has consumers')
    return {'consumersGone':True}

def conditional_delete(driver,rec):
    require(rec['namespace'] in APP_RELEASES and (rec['kind']=='PersistentVolumeClaim' and 'parent' in rec or rec['namespace']=='takserver' and (rec['kind']=='Secret' and rec['name'] in GENERATED_SECRETS|{'takserver-keystore'} or rec['kind']=='ConfigMap' and rec['name']=='cert-migration')),'cleanup outside exact retained application scope')
    driver.guard();driver.core_unchanged()
    consumers_gone(driver)
    if not driver.kube('get','namespace',rec['namespace'],'--ignore-not-found','-o','json').strip():return
    output=driver.kube('get',rec['kind'],rec['name'],'-n',rec['namespace'],'--ignore-not-found','-o','json')
    if not output.strip():return
    current=json.loads(output);require(resource_record(current)=={k:rec[k] for k in ('kind','name','namespace','uid','resourceVersion','metadataSHA256')},'retained resource identity/metadata changed')
    if rec['kind']=='PersistentVolumeClaim':
        volume=driver.get('persistentvolume',rec['parent']['volumeName'],namespace='default')
        require(volume['metadata']['uid']==rec['parent']['volumeUID'] and volume['spec']['claimRef']['uid']==rec['uid'] and volume['spec']['claimRef']['namespace']==rec['namespace'] and volume['spec']['claimRef']['name']==rec['name'],'retained PVC volume ownership changed')
    config=json.loads(driver.command(['kubectl','--context','k3d-uds','config','view','--minify','--raw','-o','json']))
    require(len(config['clusters'])==len(config['users'])==1,'ambiguous local delete client')
    cluster,user=config['clusters'][0]['cluster'],config['users'][0]['user'];host=urllib.parse.urlsplit(cluster['server'])
    require(host.scheme=='https' and host.hostname in ('127.0.0.1','localhost','0.0.0.0','::1') and not host.username,'cleanup endpoint is not local')
    require(set(user)=={'client-certificate-data','client-key-data'},'cleanup requires local certificate client')
    context=ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data'],validate=True).decode())
    with tempfile.TemporaryDirectory(prefix='owned-app-cleanup-') as temp:
        cert,key=Path(temp)/'client.crt',Path(temp)/'client.key'
        for path,field in ((cert,'client-certificate-data'),(key,'client-key-data')):path.write_bytes(base64.b64decode(user[field],validate=True));path.chmod(0o600)
        context.load_cert_chain(cert,key)
        plural={'Secret':'secrets','ConfigMap':'configmaps','PersistentVolumeClaim':'persistentvolumeclaims'}[rec['kind']]
        endpoint=cluster['server'].rstrip('/')+'/api/v1/namespaces/'+rec['namespace']+'/'+plural+'/'+urllib.parse.quote(rec['name'],safe='')
        options={'apiVersion':'v1','kind':'DeleteOptions','preconditions':{'uid':rec['uid'],'resourceVersion':rec['resourceVersion']},'propagationPolicy':'Foreground'}
        request=urllib.request.Request(endpoint,data=json.dumps(options).encode(),method='DELETE',headers={'Content-Type':'application/json'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
        with opener.open(request,timeout=30) as response:require(response.status in (200,202),'conditional application cleanup refused')
    driver.core_unchanged()
