#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in supported Zarf phase deployments in this job's disposable cluster."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import yaml

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('identity_observer',HERE/'drive.py')
D=importlib.util.module_from_spec(spec);spec.loader.exec_module(D)
retained_spec=importlib.util.spec_from_file_location('owned_application_retention',HERE/'retained_state.py')
R=importlib.util.module_from_spec(retained_spec);retained_spec.loader.exec_module(R)
failure_spec=importlib.util.spec_from_file_location('identity_failure_evidence',HERE/'failure_evidence.py')
F=importlib.util.module_from_spec(failure_spec);failure_spec.loader.exec_module(F)
PHASES=('shared','transition','strict','rollback','shared')
VARIABLES={'DOMAIN','TAK_IMAGE_TAG','FILESYSTEM_BACKUP','POSTGRES_STORAGE_CLASS','CLOUDTAK_STORAGE_CLASS'}
# Pinned k3d-slim-dev Core 1.16.0: core-base (Pepr/Istio) and
# core-identity-authorization (Keycloak); Velero is not a SLIM component.
# https://github.com/defenseunicorns/uds-core/blob/v1.16.0/bundles/k3d-slim-dev/uds-bundle.yaml
CORE_NAMESPACES=('kube-system','istio-system','pepr-system','keycloak')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def bind_inputs(archive,archive_sha,plan_path):
    D.require(archive.is_file() and not archive.is_symlink() and digest(archive)==archive_sha,'bound prebuilt package differs')
    D.require(re.fullmatch(r'zarf-package-takserver-(?:amd64|arm64)-dev(?:-upstream)?\.tar\.zst',archive.name),'unsupported application archive')
    plan=json.loads(plan_path.read_text());D.require(plan['schema']==1 and plan['sourceSHA']==os.environ['GITHUB_SHA'],'candidate plan source differs')
    item=plan['files']['config'];config=plan_path.parent/item['path']
    D.require(config.is_file() and not config.is_symlink() and digest(config)==item['sha256'],'bound config differs')
    value=yaml.safe_load(config.read_text());D.require(set(value)=={'variables'} and set(value['variables'])=={'takserver'},'unexpected package variables')
    variables=value['variables']['takserver'];D.require(set(variables)==VARIABLES and all(isinstance(x,(str,int,bool)) for x in variables.values()),'unsupported baseline variables')
    return {'archive':str(archive),'archiveSHA256':archive_sha,'plan':str(plan_path),'planSHA256':digest(plan_path),'config':str(config),'configSHA256':item['sha256'],'variables':variables}

def deploy_command(bound,phase):
    D.require(phase in D.PHASES,'unsupported package phase')
    argv=['uds','zarf','package','deploy',bound['archive'],'--confirm','--features','values=true']
    for key,value in sorted(bound['variables'].items()):argv+=['--set-variables',key+'='+str(value)]
    # The staged baseline explicitly selects the local backup owner.
    argv+=['--set-variables','FILESYSTEM_BACKUP_OWNER=local','--set-values','tak.workloadIdentityPhase='+phase]
    return argv

def declared_flags(help_text):
    # Parse Cobra flag declarations, including their optional short alias.
    # Prose/examples and longer similarly named flags do not establish support.
    return set(re.findall(r'^\s*(?:-[A-Za-z0-9],\s+)?(--[a-z][a-z0-9-]*)(?=\s|=|$)',help_text,re.MULTILINE))

def cli_preflight(command):
    for operation,flags in [('deploy',('--confirm','--features','--set-values','--set-variables')),('remove',('--confirm',))]:
        available=declared_flags(command(['uds','zarf','package',operation,'--help']))
        missing=[flag for flag in flags if flag not in available]
        D.require(not missing,'pinned Zarf '+operation+' CLI lacks required flags: '+', '.join(missing))

def require_clean_objects(namespace,kind,objects):
    if namespace=='pepr-system':
        objects=[x for x in objects if x['metadata']['name'] in D.PEPR or x['metadata'].get('labels',{}).get('name')=='takserver-oidc']
    if kind=='serviceaccounts':objects=[x for x in objects if x['metadata']['name']!='default']
    D.require(not objects,'retained application state prevents clean strict install: '+kind)

PACKAGE_FAILURE='PRIVATE-package-command-failure.json'
PACKAGE_CATEGORIES=('timeout','helm-hook','helm-upgrade','resource-conflict','package-validation','unknown')

def bounded_package_run(argv,timeout):
    child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    streams={child.stdout:bytearray(),child.stderr:bytearray()};truncated={key:False for key in streams}
    deadline=time.monotonic()+timeout;timed_out=False
    selector=selectors.DefaultSelector()
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(),False);selector.register(stream,selectors.EVENT_READ)
        while selector.get_map() or child.poll() is None:
            now=time.monotonic()
            if not timed_out and now>=deadline:
                timed_out=True
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            # Escaped descendants can retain pipe descriptors after the owned
            # process group dies. Never wait indefinitely for their EOF.
            if timed_out and now>=deadline+0.25:break
            for key,_ in selector.select(0.01):
                try:chunk=os.read(key.fileobj.fileno(),65536)
                except BlockingIOError:continue
                if not chunk:selector.unregister(key.fileobj);continue
                buffer=streams[key.fileobj];buffer.extend(chunk)
                if len(buffer)>16384:del buffer[:-16384];truncated[key.fileobj]=True
        code=child.wait(timeout=1)
    finally:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        # The direct child belongs to this process group and cannot escape a
        # pre-exec session leader's group. Reap it even after a read failure.
        child.wait(timeout=1)
        selector.close()
        for stream in streams:stream.close()
    result={'exitStatus':code,'timedOut':timed_out}
    for name,stream in [('stdout',child.stdout),('stderr',child.stderr)]:
        text=streams[stream].decode('utf-8','replace');encoded=text.encode('utf-8')
        if len(encoded)>16384:
            text=encoded[-16384:].decode('utf-8','ignore');truncated[stream]=True
        result[name]=text;result[name+'Truncated']=truncated[stream]
    return result

def command_failure_category(result):
    if result['timedOut']:return 'timeout'
    text=(result['stdout']+'\n'+result['stderr']).lower()
    for category,pattern in [('helm-hook',r'failed (pre|post)-(install|upgrade)|hook.*failed'),
                             ('helm-upgrade',r'upgrade failed|cannot patch|helm.*error'),
                             ('resource-conflict',r'already exists|conflict with|ownership metadata'),
                             ('package-validation',r'package.*checksum|invalid package|package validation')]:
        if re.search(pattern,text):return category
    return 'unknown'

class PackageTrial(D.Driver):
    def __init__(self,evidence,bound):
        super().__init__(evidence);self.bound=bound;self.deadline=time.monotonic()+7200
        self.state.update(method='package',inputBindings={key:bound[key] for key in ('archiveSHA256','planSHA256','configSHA256')},packagePhases=[],phaseEvidence=[],freshStrictAccepted=False)

    def guard(self):
        # The base driver enforces reviewed probe/driver and ephemeral identity.
        D.require(time.monotonic()<self.deadline,'120-minute package trial wall budget exhausted')
        receipt=super().guard()
        if not self.state.get('packageDriverSHA256'):
            for filename in ('package_roundtrip.py','phase_evidence.py','retained_state.py','failure_evidence.py'):
                reviewed=self.command(['git','show','HEAD:tests/workload-identities/'+filename])
                D.require(reviewed.encode()==(HERE/filename).read_bytes(),'package trial source differs from reviewed HEAD')
            self.state['packageDriverSHA256']=digest(Path(__file__))
        return receipt

    def inputs_unchanged(self):
        for path,key in [('archive','archiveSHA256'),('plan','planSHA256'),('config','configSHA256')]:
            D.require(digest(self.bound[path])==self.bound[key],'package input changed')

    def core_snapshot(self):
        result={}
        namespaces=self.get('namespaces',namespace='default')['items']
        retained=sorted(obj['metadata']['name'] for obj in namespaces if obj['metadata']['name'] not in (D.NS,'cloudtak'))
        D.require(set(CORE_NAMESPACES)<=set(retained),'required Core namespaces missing')
        for ns in retained:
            result['namespace/'+ns]=self.get('namespace',ns,ns)['metadata']['uid']
            for kind in ('deployments','statefulsets','daemonsets','packages.uds.dev'):
                for obj in self.get(kind,namespace=ns)['items']:
                    if ns=='pepr-system' and obj['metadata']['name'] in D.PEPR:continue
                    if ns=='velero' and kind=='daemonsets' and obj['metadata']['name']=='node-agent':
                        annotations=obj['metadata'].get('annotations',{})
                        if annotations.get('meta.helm.sh/release-name')=='uds-takserver-config' and annotations.get('meta.helm.sh/release-namespace')==D.NS:continue
                    result[ns+'/'+kind+'/'+obj['metadata']['name']]=obj['metadata']['uid']
        result['mesh']=D.sha(self.get('configmap','istio','istio-system').get('data',{}))
        return result

    def core_unchanged(self):
        D.require(self.core_snapshot()==self.state['coreSnapshot'],'retained Core identity/config changed')

    def capture_phase(self,phase,account):
        alias='fresh-strict' if self.state.get('initializingFresh') else ('baseline' if not self.state['packagePhases'] else phase)
        verdict=super().capture_phase(alias,account,binding_extra={
            'packageArchiveSHA256':self.bound['archiveSHA256'],'baselineValuesSHA256':self.bound['configSHA256']})
        self.journal('package-phase-evidence-'+alias,accepted=verdict['accepted'])
        return verdict

    def observe(self,phase):
        desired,_=self.render(phase);current=self.get('package',D.NS)
        D.require(current['spec']==desired['spec'],'package deployment differs from exact phase render')
        self.state['currentAllow']=desired['spec']['network']['allow']
        self.wait(self.policies)
        self.wait(lambda:self.observe_pepr(phase))
        expected='dedicated' if phase in ('transition','strict') else 'shared'
        identities=self.wait(lambda:self.identities(expected));self.core_unchanged()
        values=json.loads(self.command(['helm','--kube-context',D.CONTEXT,'get','values','uds-takserver-config','-n',D.NS,'-o','json']))
        D.require(values.get('workloadIdentityPhase','shared')==phase,'stored config Helm value differs')
        alias='fresh-strict' if self.state.get('initializingFresh') else ('baseline' if not self.state['packagePhases'] else phase)
        if self.state.get('initializingFresh'):
            self.state['freshDataInvariants']=R.capture(self)
            data_evidence=R.verify(self,self.state['freshDataInvariants'])
        else:data_evidence=R.verify(self,self.state['dataInvariants'])
        self.journal('private-application-data-verified',phase=alias,observations=data_evidence)
        self.traffic(identities,phase,evidence_phase='package-'+alias)
        self.application_checks(phase=alias,prepare=not self.state['packagePhases'] or self.state.get('initializingFresh',False))
        self.journal('package-application-checks',phase=alias)
        self.capture_phase(phase,expected)
        self.state['packagePhases'].append(phase);self.journal('package-observed-'+alias,pods=identities)

    def run_package(self,argv,timeout):
        self.guard();self.inputs_unchanged();self.core_unchanged()
        D.require(self.command(['kubectl','config','current-context']).strip()==D.CONTEXT,'Zarf default context is not the guarded cluster')
        role='remove' if argv==['uds','zarf','package','remove','takserver','--confirm'] else 'deploy'
        phase=next((phase for phase in D.PHASES if argv==deploy_command(self.bound,phase)),None) if role=='deploy' else 'shared'
        D.require(phase is not None,'unsupported package command')
        result=bounded_package_run(argv,min(timeout,max(1,int(self.deadline-time.monotonic()))))
        if result['exitStatus']!=0 or result['timedOut']:
            binding={key:self.state['guard'][key] for key in ('sourceSHA','runID','runAttempt')}
            payload={'schema':1,'binding':binding,'role':role,'phase':phase,**result,
                     'packageDriverSHA256':digest(Path(__file__)),'driverSHA256':digest(HERE/'drive.py')}
            folder=self.evidence.parent
            D.require(stat.S_IMODE(folder.stat().st_mode)==0o700 and not any(path.is_symlink() for path in (folder,*folder.parents)),
                      'package failure directory is not private')
            destination=folder/PACKAGE_FAILURE
            data=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
            while len(data)>64*1024:
                for stream in ('stdout','stderr'):
                    payload[stream]=payload[stream][len(payload[stream])//2:];payload[stream+'Truncated']=True
                data=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
            try:
                fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            except FileExistsError:
                # Never follow a pre-existing link or adopt another trial's file.
                previous=self.state.get('packageCommandFailure',{})
                D.require(previous.get('file')==PACKAGE_FAILURE and not destination.is_symlink() and
                          stat.S_ISREG(destination.stat().st_mode) and stat.S_IMODE(destination.stat().st_mode)==0o600 and
                          destination.stat().st_size<=64*1024 and digest(destination)==previous.get('sha256'),
                          'existing package failure is not the owned first failure')
            else:
                with os.fdopen(fd,'wb') as output:output.write(data)
                self.state['packageCommandFailure']={'file':PACKAGE_FAILURE,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            self.journal('package-command-failed',role=role,phase=phase,exitStatus=result['exitStatus'],timedOut=result['timedOut'],
                         category=command_failure_category(result),stdoutPresent=bool(result['stdout']),stderrPresent=bool(result['stderr']))
            raise ValueError('supported package command failed; inspect bounded private evidence')
        return result['stdout']


    def deploy(self,phase):
        self.guard();self.inputs_unchanged();self.core_unchanged()
        D.require(self.command(['kubectl','config','current-context']).strip()==D.CONTEXT,'Zarf default context is not the guarded cluster')
        self.journal('package-deploy-start',phase=phase,archiveSHA256=self.bound['archiveSHA256'])
        self.run_package(deploy_command(self.bound,phase),1500)
        self.inputs_unchanged();self.observe(phase)

    def require_cloudtak(self):
        namespace=self.get('namespace','cloudtak',namespace='cloudtak');deployment=self.get('deployment','cloudtak',namespace='cloudtak')
        package=self.get('package','cloudtak',namespace='cloudtak')
        D.require(not namespace['metadata'].get('deletionTimestamp'),'CloudTAK namespace terminating')
        D.ready(deployment);D.ready(package)
        D.require(package['status'].get('phase')=='Ready' and deployment['status'].get('availableReplicas',0)>0,'CloudTAK component is required for issue32 acceptance')
        return {key:obj['metadata']['uid'] for key,obj in (('namespace',namespace),('deployment',deployment),('package',package))}

    def application_checks(self,phase,prepare=False):
        self.guard()
        if prepare:
            self.command(['uds','run','setup:keycloak-user','--with','group=/UDS Core/Admin','--no-progress'],timeout=300)
            self.command(['python3',str(D.ROOT/'tests/ensure-tak-group.py')],timeout=180)
            self.command(['uds','run','test:gateway','--no-progress'],timeout=420)
        self.command(['uds','run','test:web-tls','--no-progress'],timeout=420)
        self.command(['uds','run','test:api-smoke','--no-progress'],timeout=720)
        self.command(['uds','run','test:flows','--no-progress'],timeout=300)
        before=self.require_cloudtak()
        if phase in ('baseline','strict','fresh-strict'):
            output=self.command(['uds','run','test:cloudtak','--no-progress'],timeout=900)
            D.require('The cloudtak component is not deployed. Skipping.' not in output and self.require_cloudtak()==before,'CloudTAK check skipped or component changed')
            self.journal('cloudtak-basemap-application-checks',phase=phase,passed=True)

    def patch(self,kind,obj,path,value,namespace=D.NS):
        D.require(kind=='Pod' and path=='/metadata/labels','package phases must use Zarf, not direct phase patches')
        return super().patch(kind,obj,path,value,namespace)

    def stage_config(self,*args):raise ValueError('direct Package phase mutation forbidden in package trial')
    def stage_admission(self,*args):raise ValueError('direct admission phase mutation forbidden in package trial')

    def initialize(self):
        binding=self.bind_zarf_domain(Path(self.bound['plan']))
        D.require(binding['configSHA256']==self.bound['configSHA256'] and binding['DOMAIN']==self.bound['variables']['DOMAIN'],'package/render DOMAIN binding differs')
        self.prepare()  # Initial shared observation only; creates no trial resources.
        D.require(Path(self.bound['archive']).name.startswith('zarf-package-takserver-'+self.state['architecture']+'-'),'bound archive architecture differs from guarded node')
        self.require_cloudtak()
        self.state['coreSnapshot']=self.core_snapshot();self.compile_probe()
        self.state['dataInvariants']=R.capture(self)
        self.create({'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':self.state['negativeAccount']},'automountServiceAccountToken':False})
        self.observe('shared')

    def clean_application_state(self):
        for ns,kinds in [(D.NS,('deployments','statefulsets','jobs','pods','persistentvolumeclaims','secrets','configmaps','services','serviceaccounts','roles','rolebindings','packages.uds.dev')),
                         ('cloudtak',('deployments','statefulsets','jobs','pods','persistentvolumeclaims','secrets','configmaps','services','serviceaccounts','roles','rolebindings','packages.uds.dev')),
                         ('pepr-system',('deployments','secrets'))]:
            namespace=self.kube('get','namespace',ns,'--ignore-not-found','-o','json')
            if not namespace.strip():continue
            for kind in kinds:
                objects=self.get(kind,namespace=ns)['items']
                if kind=='configmaps':
                    retained=[]
                    for obj in objects:
                        if obj['metadata']['name'] in ('kube-root-ca.crt','istio-ca-root-cert','uds-trust-bundle'):
                            R.preserved_trust(self,obj,self.state['preservedTrustMaps'])
                        else:retained.append(obj)
                    objects=retained
                require_clean_objects(ns,kind,objects)
        return {'clean':True}

    def fresh_strict(self):
        self.guard();self.core_unchanged();self.inputs_unchanged()
        D.require(self.state['packagePhases']==list(PHASES),'fresh strict requires successful package round trip')
        # Remove only this exact application's installed Zarf package, never a bundle/Core.
        for entry in list(self.state['created']):
            if entry['kind']=='ServiceAccount' and not entry.get('deleted'):self.delete_created(entry['kind'],entry['name'])
        self.state['preservedTrustMaps']=R.capture_trust(self)
        self.state['retainedCleanup']=R.cleanup_snapshot(self,self.state['dataInvariants'])
        installed=self.get('secret','zarf-package-takserver','zarf')
        self.state['removedPackageSecretUID']=installed['metadata']['uid'];self.journal('application-remove-start')
        self.run_package(['uds','zarf','package','remove','takserver','--confirm'],900)
        self.core_unchanged()
        self.wait(lambda:R.consumers_gone(self),300)
        for record in self.state['retainedCleanup']:
            R.conditional_delete(self,record)
            self.journal('retained-object-conditionally-removed',kind=record['kind'],name=record['name'],uid=record['uid'])
        self.wait(self.clean_application_state,300)
        # New install has new Deployment/Package UIDs; retain old observations in journal.
        self.state['previousInstall']={k:self.state[k] for k in ('packageUID','deploymentUIDs','peprUIDs','backendTargets')}
        self.run_package(deploy_command(self.bound,'strict'),1500);self.inputs_unchanged();self.core_unchanged()
        package=self.get('package',D.NS);deployments={x['metadata']['name']:x for x in self.get('deployments')['items'] if x['metadata']['name'] in D.APPS}
        D.require(set(deployments)==set(D.APPS),'fresh strict workloads missing')
        self.state.update(packageUID=package['metadata']['uid'],packageInvariant=D.package_invariant(package),deploymentUIDs={n:x['metadata']['uid'] for n,x in deployments.items()},templateFingerprints={n:D.template_fingerprint(x) for n,x in deployments.items()},peprUIDs={n:self.get('deployment',n,'pepr-system')['metadata']['uid'] for n in D.PEPR},peprTemplateFingerprints={n:D.template_fingerprint(self.get('deployment',n,'pepr-system'),True) for n in D.PEPR})
        self.state.pop('backendTargets',None)
        self.create({'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':self.state['negativeAccount']},'automountServiceAccountToken':False})
        self.state['initializingFresh']=True
        self.observe('strict');self.state['initializingFresh']=False;self.state['freshStrictAccepted']=True;self.journal('fresh-strict-verified')

    def finish(self):
        self.core_unchanged();self.inputs_unchanged()
        R.verify(self,self.state.get('freshDataInvariants',self.state['dataInvariants']),remove_sentinels=True)
        for entry in reversed(self.state['created']):
            if entry['kind']=='ServiceAccount' and not entry.get('deleted'):self.delete_created(entry['kind'],entry['name'])
        self.state['completed']=True;self.state['accepted']=self.state['packagePhases'][:5]==list(PHASES) and (not self.state.get('freshStrictRequested') or self.state['freshStrictAccepted'])
        self.journal('package-roundtrip-verified')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=('preflight','round-trip'));p.add_argument('--archive',type=Path);p.add_argument('--archive-sha256');p.add_argument('--candidate-plan',type=Path);p.add_argument('--evidence',type=Path);p.add_argument('--fresh-strict',action='store_true');a=p.parse_args()
    driver=None
    try:
        command=lambda argv:subprocess.run(argv,text=True,capture_output=True,check=True,timeout=30).stdout
        cli_preflight(command)
        if a.operation=='preflight':return
        D.require(all((a.archive,a.archive_sha256,a.candidate_plan,a.evidence)),'bound inputs and evidence required')
        b=bind_inputs(a.archive.resolve(),a.archive_sha256,a.candidate_plan.resolve());driver=PackageTrial(a.evidence.resolve(),b)
        driver.state['freshStrictRequested']=a.fresh_strict
        driver.initialize()
        for phase in PHASES[1:]:driver.deploy(phase)
        if a.fresh_strict:driver.fresh_strict()
        driver.finish()
    except Exception as error:
        # Capture before journaling: initialize/preflight may fail before trialID.
        # No message, command, stderr or local value is persisted or printed.
        if a.evidence:
            try:F.write(a.evidence.absolute().parent,error)
            except (ValueError,OSError,subprocess.SubprocessError):pass
        if driver is not None and driver.state.get('trialID'):
            driver.journal('stopped',failure=type(error).__name__ if type(error).__name__ in F.TYPES else 'Other')
        raise SystemExit('package identity trial stopped; inspect private callsite evidence; no automatic rollback') from None

if __name__=='__main__':main()
