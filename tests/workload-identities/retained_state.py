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
SOURCE_CLEANUP={(ns,'Secret',name) for ns,name in [('takserver',name) for name in GENERATED_SECRETS|{'takserver-keystore','takclient-enrollment'}]+[('cloudtak','cloudtak-tak-admin')]}|{('takserver','ConfigMap','cert-migration'),('takserver','ConfigMap','takserver-startup')}

def cleanup_allowed(rec):
    return rec['namespace'] in APP_RELEASES and (rec['kind']=='PersistentVolumeClaim' and 'parent' in rec or (rec['namespace'],rec['kind'],rec['name']) in SOURCE_CLEANUP)

def require(value,message):
    if not value:raise ValueError(message)

def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

SOURCE_FILES=('pepr/capabilities/workload.ts','pepr/capabilities/cloudtak-admin.ts','pepr/capabilities/takclient-credentials.ts')

def source_files():
    return {name:hashlib.sha256((Path(__file__).resolve().parents[2]/name).read_bytes()).hexdigest() for name in SOURCE_FILES}

def require_origin(rec):
    origin=rec.get('origin',{})
    require(set(origin)=={'sourceFilesSHA256','storedHooksSHA256','sourceGeneratorJobSHA256','keystoreHookSHA256'} and origin['sourceFilesSHA256']==source_files(),'retained cleanup has no unchanged bound source origin')
    require(all(re.fullmatch(r'[a-f0-9]{64}',origin[key]) for key in ('storedHooksSHA256','sourceGeneratorJobSHA256','keystoreHookSHA256')),'retained source origin hashes invalid')

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
    sources=source_files()
    return {'sourceFilesSHA256':sources,'storedHooksSHA256':hashlib.sha256(text.encode()).hexdigest(),'sourceGeneratorJobSHA256':sha(job),'keystoreHookSHA256':sha(secret)}

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
    require(pvc['metadata']['namespace'] in APP_RELEASES,'PVC mount outside application')
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
                    require(isinstance(container.get('name'),str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*',container['name']),'unsupported PVC container')
                    matches.append((pod['metadata']['name'],container['name'],path))
    require(len(matches)==1,'PVC has no unique writable application mount')
    return matches[0]

def sentinel_exec(driver,operation,namespace,pod,container,args,payload=None):
    require(operation in ('create','read','remove') and namespace in APP_RELEASES,'unsupported sentinel operation/scope')
    driver.journal('retained-sentinel-start',operation=operation,namespace=namespace)
    result=driver.exec(pod,container,args,payload,namespace=namespace)
    # Fixed bounded facts only: never publish remote stderr, paths or Pod names.
    status=result.returncode
    driver.journal('retained-sentinel-exec',operation=operation,namespace=namespace,
                   exitStatus=status if isinstance(status,int) and -255<=status<=255 else None,
                   stderrPresent=bool(result.stderr.strip()))
    return result

def sentinel_create_script(path,sentinel):
    # Fixed predicate statuses: 61 missing directory, 62 symlink, 63 unwritable,
    # 64 existing sentinel, 65 write failure. No remote text is evidence.
    directory=shlex.quote(path);target=shlex.quote(sentinel)
    return ('umask 077; set -o noclobber; '
            'if test -L '+directory+'; then exit 62; fi; '
            'if ! test -d '+directory+'; then exit 61; fi; '
            'if ! test -w '+directory+'; then exit 63; fi; '
            'if test -e '+target+' || test -L '+target+'; then exit 64; fi; '
            'if ! cat > '+target+'; then exit 65; fi')

def capture(driver):
    origin=hooks(driver);records=[]
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        for pvc in driver.get('persistentvolumeclaims',namespace=namespace)['items']:
            rec=resource_record(pvc);rec['parent']=claim_parent(driver,pvc);pod,container,path=mount(driver,pvc)
            sentinel=path.rstrip('/')+'/.uds-'+driver.state['trialID'];token=sha({'uid':rec['uid'],'trial':driver.state['trialID']})+'\n'
            script=sentinel_create_script(path,sentinel)
            result=sentinel_exec(driver,'create',namespace,pod,container,['/bin/bash','-ceu',script],token)
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
            extra=(namespace,name) in {('cloudtak','cloudtak-tak-admin'),('takserver','takclient-enrollment')}
            if extra:generated_secret(driver,secret)
            if name in referenced or namespace=='takserver' and name in GENERATED_SECRETS|{'takserver-keystore'} or extra:
                rec=resource_record(secret);rec['dataSHA256']=sha(secret.get('data',{}));rec['recreatedHook']=namespace=='takserver' and name=='takserver-keystore';records.append(rec)
    for config in driver.get('configmaps')['items']:
        if config['metadata']['name']=='takserver-startup':startup_map(config)
        if config['metadata']['name'] in ('cert-migration','takserver-startup'):
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
            result=sentinel_exec(driver,'read',rec['namespace'],pod,container,['/bin/bash','-ceu','test ! -L '+shlex.quote(rec['sentinel'])+'; sha256sum -- '+shlex.quote(rec['sentinel'])])
            observed=result.stdout.split()
            require(result.returncode==0 and not result.stderr.strip() and len(observed)==2 and observed[0]==rec['sentinelSHA256'] and observed[1]==rec['sentinel'],'application PVC data sentinel changed')
            if remove_sentinels:
                result=sentinel_exec(driver,'remove',rec['namespace'],pod,container,['/bin/bash','-ceu','rm -- '+shlex.quote(rec['sentinel'])]);require(result.returncode==0,'exact owned sentinel cleanup failed')
            observations.append({'kind':rec['kind'],'name':rec['name'],'namespace':rec['namespace'],'uid':meta['uid'],'volumeUID':rec['parent']['volumeUID'],'sentinelSHA256':observed[0]})
        else:
            value=current.get('data',{}) if rec['kind']=='Secret' else {'data':current.get('data',{}),'binaryData':current.get('binaryData',{})}
            require(sha(value)==rec['dataSHA256'],'application credential/certificate data changed')
            observations.append({'kind':rec['kind'],'name':rec['name'],'namespace':rec['namespace'],'uid':meta['uid'],'dataSHA256':sha(value),'recreatedHook':rec.get('recreatedHook',False)})


    return observations

def cleanup_snapshot(driver,proof):
    verify(driver,proof,remove_sentinels=True);result=[]
    for rec in proof['records']:
        if cleanup_allowed(rec):
            current=driver.get(rec['kind'],rec['name'],namespace=rec['namespace'])
            if rec['name']=='takserver-startup':startup_map(current)
            if rec['name'] in ('cloudtak-tak-admin','takclient-enrollment'):generated_secret(driver,current,cleanup=True)
            item=resource_record(current);item['origin']=proof['source']
            if rec['kind']=='PersistentVolumeClaim':item['parent']=claim_parent(driver,current)
            result.append(item)
    return result

def consumers_gone(driver):
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        require(all(not driver.get(kind,namespace=namespace)['items'] for kind in ('pods','deployments','statefulsets')),'application still has consumers')
    return {'consumersGone':True}

def conditional_delete(driver,rec):
    require(cleanup_allowed(rec),'cleanup outside exact retained application scope')
    require_origin(rec)
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


def startup_map(obj):
    require(obj['kind']=='ConfigMap' and obj['metadata'].get('namespace')=='takserver' and obj['metadata']['name']=='takserver-startup' and obj['metadata'].get('annotations',{}).get('uds.dev/tak-startup')=='complete' and obj.get('data')=={'ready':'true'} and not obj.get('binaryData'),'startup map is not the literal source-generated checkpoint')


def generated_secret(driver,obj,cleanup=False):
    meta=obj['metadata'];name=meta['name'];namespace=meta['namespace']
    if namespace=='cloudtak' and name=='cloudtak-tak-admin':
        require(meta.get('labels',{}).get('app.kubernetes.io/part-of')=='cloudtak','admin copy source label differs')
        config=driver.get('configmap','cert-migration');keystore=driver.get('secret','takserver-keystore')
        raw=driver.kube('get','secret','takserver-certs','-n','takserver','--ignore-not-found','-o','json')
        certificates=json.loads(raw).get('data',{}) if raw.strip() else {}
        binary=config.get('binaryData',{})
        expected={'ca.pem':binary.get('ca.pem') or certificates.get('ca.pem'),'admin.pem':binary.get('admin.pem') or certificates.get('admin.pem'),
                  'admin.key':certificates.get('admin.key') or binary.get('admin.key'),'CAPASS':keystore.get('data',{}).get('CAPASS')}
        require(all(expected.values()) and obj.get('data')==expected,'admin copy does not match exact source credentials')
        return True
    if namespace=='takserver' and name=='takclient-enrollment':
        require(meta.get('labels',{}).get('app.kubernetes.io/managed-by')=='takserver-oidc','enrollment cache source label differs')
        if cleanup:require(not driver.get('takclients.tak.jonathanagustin.github.io',namespace='takclients')['items'],'active client enrollment credentials must not be retired')
        return True
    return False


def trust_binding(driver,obj):
    """Bind public trust data to retained Core authority and exact source metadata."""
    meta=obj['metadata'];namespace=meta['namespace'];name=meta['name']
    require(namespace in APP_RELEASES and not obj.get('binaryData'),'trust map namespace/payload differs')
    if name=='kube-root-ca.crt':
        source_namespace,source_name,key,source_key='kube-system',name,'ca.crt','ca.crt'
        source_owner='kubernetes-root-ca-publisher'
    elif name=='istio-ca-root-cert':
        require(meta.get('labels',{}).get('istio.io/config')=='true','Istio trust source marker missing')
        source_namespace,source_name,key,source_key='istio-system',name,'root-cert.pem','root-cert.pem'
        source_owner='istio-namespace-controller'
    elif name=='uds-trust-bundle':
        labels=meta.get('labels',{});require(labels.get('uds/package')==namespace and labels.get('uds/ca-bundle')=='true','UDS bundle source labels differ')
        package=driver.get('package',namespace,namespace=namespace)
        owners=meta.get('ownerReferences',[])
        require(any(x.get('kind')=='Package' and x.get('uid')==package['metadata']['uid'] for x in owners),'UDS bundle has no exact Package owner')
        source_namespace,source_name,key,source_key='istio-system',name,'ca-bundle.pem','extra.pem'
        source_owner='uds-core-ca-bundle-controller'
    else:raise ValueError('unknown trust map')
    source=driver.get('configmap',source_name,namespace=source_namespace)
    require(set(obj.get('data',{}))=={key} and obj['data'][key] and obj['data'][key]==source.get('data',{}).get(source_key),'trust map is not the bound Core authority data')
    rec=resource_record(obj)
    rec.update(dataSHA256=sha(obj['data']),sourceOwner=source_owner,sourceNamespace=source_namespace,sourceName=source_name,sourceUID=source['metadata']['uid'],sourceDataSHA256=sha(source.get('data',{})))
    return rec


def capture_trust(driver):
    result=[]
    for namespace in APP_RELEASES:
        if not driver.kube('get','namespace',namespace,'--ignore-not-found','-o','json').strip():continue
        for obj in driver.get('configmaps',namespace=namespace)['items']:
            if obj['metadata']['name'] in ('kube-root-ca.crt','istio-ca-root-cert','uds-trust-bundle'):result.append(trust_binding(driver,obj))
    return result


def preserved_trust(driver,obj,bindings):
    matches=[r for r in bindings if r['namespace']==obj['metadata'].get('namespace') and r['name']==obj['metadata']['name']]
    require(len(matches)==1,'trust map has no bound source authority')
    rec=matches[0];require({k:v for k,v in resource_record(obj).items() if k!='resourceVersion'}=={k:rec[k] for k in ('kind','name','namespace','uid','metadataSHA256')} and sha(obj.get('data',{}))==rec['dataSHA256'],'bound trust map changed before clean-state observation')
    source=driver.get('configmap',rec['sourceName'],namespace=rec['sourceNamespace'])
    require(source['metadata']['uid']==rec['sourceUID'] and sha(source.get('data',{}))==rec['sourceDataSHA256'],'retained Core trust authority changed')
    return True
