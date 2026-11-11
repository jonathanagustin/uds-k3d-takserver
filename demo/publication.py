#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Sign candidates once, then publish exact reviewed bytes without touching historical demos."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import zipfile

REPO = 'jonathanagustin/uds-takserver'
WORKFLOW = '.github/workflows/demo.yaml'
REF = 'refs/heads/main'
IDENTITY = 'https://github.com/'+REPO+'/'+WORKFLOW+'@'+REF
MANIFEST = 'demo-manifest.json'
BUNDLE = 'demo-attestation.sigstore.json'
INTOTO = 'demo-videos.intoto.jsonl'
TOTAL = 256 * 1024**2
FILE = 64 * 1024**2
JSON_LIMIT = 1024**2
CLIPS = ('deploy','package-ready','sso','cloudtak-user','atak-device','airgap',
         'policy','sync','secure','upgrade','self-healing')
CLIP_FILES = tuple('clips/demo-clip-'+name+'.'+extension for name in CLIPS for extension in ('mp4','jpg'))
PATTERNS = ('demo.mp4','demo-operate.mp4','*-chapters.txt','poster.png','preview.gif',
            'demo-deploy.jpg','demo-operate-and-trust.jpg','shots/*.webp') + CLIP_FILES


def require(value):
    if not value:raise ValueError('Demo publication policy rejected')


def match(value, pattern):
    return type(value) is str and re.fullmatch(pattern,value) is not None


def unique(pairs):
    out={}
    for key,value in pairs:
        require(key not in out);out[key]=value
    return out


def decode(data):
    require(len(data)<=JSON_LIMIT)
    return json.loads(data,object_pairs_hook=unique)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''):digest.update(chunk)
    return digest.hexdigest()


def info(path,name=None):
    path=Path(path)
    require(not path.is_symlink() and path.is_file() and 0<path.stat().st_size<=FILE)
    return {'file':name or path.name,'bytes':path.stat().st_size,'sha256':sha(path)}


def identity(run_id,attempt,source):
    require(match(str(run_id),r'[1-9][0-9]{0,19}') and match(str(attempt),r'[1-9][0-9]{0,5}'))
    require(match(source,r'[0-9a-f]{40}'))
    return {'run':str(run_id),'attempt':str(attempt),'workflowCommit':source}


def mode(run,attempt,legacy,ref):
    require(ref==REF and not legacy)
    if not run and not attempt:return 'record'
    identity(run,attempt,'0'*40)
    return 'publish'


def tag(source):
    identity(source['run'],source['attempt'],source['workflowCommit'])
    return 'demo-run-'+source['run']+'-attempt-'+source['attempt']


class GitHub:
    def command(self,args,output=None,limit=JSON_LIMIT,json_output=True,program='gh'):
        # Stream bounded binary downloads; never echo subprocess diagnostics/URLs.
        with tempfile.TemporaryFile() as stderr,tempfile.TemporaryFile() as temporary:
            stdout=output or temporary
            process=subprocess.Popen([program,*args],stdout=stdout,stderr=stderr,start_new_session=True)
            deadline=time.monotonic()+120
            try:
                while process.poll() is None:
                    require(time.monotonic()<deadline and os.fstat(stdout.fileno()).st_size<=limit and
                            os.fstat(stderr.fileno()).st_size<=JSON_LIMIT)
                    time.sleep(.1)
                require(process.returncode==0 and os.fstat(stdout.fileno()).st_size<=limit and
                        os.fstat(stderr.fileno()).st_size<=JSON_LIMIT)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
            if output is None:
                temporary.seek(0);data=temporary.read(JSON_LIMIT+1)
                return decode(data) if json_output else data

    def cosign(self,command):return self.command(command[1:],json_output=False,program='cosign')

    def api(self,path):return self.command(['api',path])

    def pages(self,path):return self.command(['api','--paginate','--slurp',path])


def run_identity(gh,run_id,attempt,completed=True):
    source=gh.api('repos/'+REPO+'/actions/runs/'+str(run_id)+'/attempts/'+str(attempt))
    workflow=gh.api('repos/'+REPO+'/actions/workflows/demo.yaml')
    require(source['id']==int(run_id) and source['run_attempt']==int(attempt) and
            source['workflow_id']==workflow['id'] and source['path']==WORKFLOW and workflow['path']==WORKFLOW)
    require(source['event']=='workflow_dispatch' and source['head_branch']=='main')
    if completed:require(source['status']=='completed' and source['conclusion']=='success')
    for key in ('repository','head_repository'):
        require(source[key]['full_name']==REPO and source[key]['id']==1427088300 and
                source[key]['owner']['id']==5193877)
    identity(run_id,attempt,source['head_sha'])
    return source


def extract(gh,run,name,directory):
    pages=gh.pages('repos/'+REPO+'/actions/runs/'+str(run['id'])+'/artifacts?per_page=100')
    found=[a for page in pages for a in page['artifacts'] if a['name']==name]
    require(len(found)==1)
    asset=found[0];require(not asset['expired'] and 0<asset['size_in_bytes']<=TOTAL)
    for key,value in {'id':run['id'],'repository_id':1427088300,'head_repository_id':1427088300,
                      'head_branch':'main','head_sha':run['head_sha']}.items():
        require(asset['workflow_run'].get(key)==value)
    require(shutil.disk_usage(directory).free>2*1024**3+3*TOTAL)
    with tempfile.TemporaryFile() as archive:
        gh.command(['api','repos/'+REPO+'/actions/artifacts/'+str(asset['id'])+'/zip'],archive,TOTAL)
        archive.flush()
        require(os.fstat(archive.fileno()).st_size==asset['size_in_bytes'])
        archive.seek(0);digest=hashlib.file_digest(archive,'sha256').hexdigest()
        require(asset['digest']=='sha256:'+digest)
        archive.seek(0)
        with zipfile.ZipFile(archive) as zipped:
            entries=zipped.infolist();names=[entry.filename for entry in entries]
            require(0<len(entries)<=128 and len(set(names))==len(names) and
                    sum(entry.file_size for entry in entries)<=TOTAL)
            for entry in entries:
                require(not entry.is_dir() and stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and
                        0<entry.file_size<=FILE and match(entry.filename,r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?'))
                path=Path(directory)/entry.filename;path.parent.mkdir(parents=True,exist_ok=True)
                require(not path.exists() and not path.is_symlink())
                with zipped.open(entry) as src,path.open('xb') as dest:shutil.copyfileobj(src,dest,1024**2)
    return asset


def capture(directory,app_source):
    root=Path(directory);require(match(app_source,r'[0-9a-f]{40}'))
    source=identity(os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],os.environ['GITHUB_SHA'])
    for path in (root/'clips').glob('demo-clip-*'):
        require(path.relative_to(root).as_posix() in CLIP_FILES and path.is_file() and not path.is_symlink())
    paths=sorted({p for pattern in PATTERNS for p in root.glob(pattern) if p.is_file()})
    require(root/'demo.mp4' in paths and root/'demo-operate.mp4' in paths)
    outputs=[info(p,p.relative_to(root).as_posix()) for p in paths]
    require(len(outputs)<=100 and sum(item['bytes'] for item in outputs)<=TOTAL)
    (root/'capture.json').write_text(json.dumps({'schema':1,'capture':source,'applicationCommit':app_source,'outputs':outputs},sort_keys=True))


def check_inventory(directory,outputs,extras=()):
    require(type(outputs) is list and 0<len(outputs)<=100)
    names=[]
    for item in outputs:
        require(type(item) is dict and set(item)=={'file','bytes','sha256'})
        require(match(item['file'],r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?'))
        require(type(item['bytes']) is int and match(item['sha256'],r'[0-9a-f]{64}'))
        require(info(Path(directory)/item['file'],item['file'])==item);names.append(item['file'])
    require(len(names)==len(set(names)) and sum(item['bytes'] for item in outputs)<=TOTAL)
    actual={p.relative_to(directory).as_posix() for p in Path(directory).rglob('*') if not p.is_dir()}
    require(actual==set(names)|set(extras))


def prepare_sign(gh,directory):
    current=run_identity(gh,os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],False)
    require(current['head_sha']==os.environ['GITHUB_SHA'])
    with tempfile.TemporaryDirectory() as temp:
        capture_attempt=os.environ.get('CAPTURE_ATTEMPT','')
        require(match(capture_attempt,r'[1-9][0-9]{0,5}') and int(capture_attempt)<=current['run_attempt'])
        extract(gh,current,'demo-video-attempt-'+capture_attempt,temp)
        receipt=decode((Path(temp)/'capture.json').read_bytes())
        require(set(receipt)=={'schema','capture','applicationCommit','outputs'} and type(receipt['schema']) is int and receipt['schema']==1)
        capture_source=receipt['capture'];identity(capture_source['run'],capture_source['attempt'],capture_source['workflowCommit'])
        require(capture_source['attempt']==capture_attempt and capture_source['run']==str(current['id']) and capture_source['workflowCommit']==current['head_sha'] and
                int(capture_source['attempt'])<=current['run_attempt'] and match(receipt['applicationCommit'],r'[0-9a-f]{40}'))
        jobs=gh.pages('repos/'+REPO+'/actions/runs/'+capture_source['run']+'/attempts/'+capture_source['attempt']+'/jobs?per_page=100')
        record=[job for page in jobs for job in page['jobs'] if job['name']=='record']
        require(len(record)==1 and record[0]['conclusion']=='success')
        check_inventory(temp,receipt['outputs'],('capture.json',))
        outputs=[]
        for item in receipt['outputs']:
            name=item['file'];final={'demo.mp4':'demo-deploy.mp4','demo-operate.mp4':'demo-operate-and-trust.mp4'}.get(name,Path(name).name)
            if name.endswith('.mp4') or name in ('demo-deploy.jpg','demo-operate-and-trust.jpg') or (name.startswith('clips/') and name.endswith('.jpg')):
                require(not (Path(directory)/final).exists());shutil.copyfile(Path(temp)/name,Path(directory)/final)
                outputs.append(info(Path(directory)/final))
        manifest={'schema':1,'capture':receipt,'signing':identity(current['id'],current['run_attempt'],current['head_sha']),'outputs':outputs}
        (Path(directory)/MANIFEST).write_text(json.dumps(manifest,sort_keys=True))


def manifest(directory):
    value=decode((Path(directory)/MANIFEST).read_bytes())
    require(type(value) is dict and set(value)=={'schema','capture','signing','outputs'} and type(value['schema']) is int and value['schema']==1)
    require(set(value['signing'])=={'run','attempt','workflowCommit'})
    identity(**{'run_id':value['signing']['run'],'attempt':value['signing']['attempt'],'source':value['signing']['workflowCommit']})
    receipt=value['capture'];require(set(receipt)=={'schema','capture','applicationCommit','outputs'} and type(receipt['schema']) is int and receipt['schema']==1)
    source=receipt['capture'];require(set(source)=={'run','attempt','workflowCommit'});identity(source['run'],source['attempt'],source['workflowCommit'])
    require(source['run']==value['signing']['run'] and source['workflowCommit']==value['signing']['workflowCommit'] and
            int(source['attempt'])<=int(value['signing']['attempt']) and match(receipt['applicationCommit'],r'[0-9a-f]{40}'))
    names=[item['file'] for item in value['outputs']]
    require({'demo-deploy.mp4','demo-operate-and-trust.mp4'}<=set(names) and all(match(name,r'(?:demo-[a-z0-9-]+)\.(?:mp4|jpg)') for name in names))
    require(type(receipt['outputs']) is list and 0<len(receipt['outputs'])<=100)
    for item in receipt['outputs']:
        require(type(item) is dict and set(item)=={'file','bytes','sha256'} and
                match(item['file'],r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?') and
                any(PurePosixPath(item['file']).match(pattern) for pattern in PATTERNS) and
                type(item['bytes']) is int and 0<item['bytes']<=FILE and match(item['sha256'],r'[0-9a-f]{64}'))
    require(sum(item['bytes'] for item in receipt['outputs'])<=TOTAL)
    original={item['file']:item for item in receipt['outputs']}
    require(len(original)==len(receipt['outputs']))
    for item in value['outputs']:
        source_name={'demo-deploy.mp4':'demo.mp4','demo-operate-and-trust.mp4':'demo-operate.mp4'}.get(item['file'],item['file'])
        if item['file'].startswith('demo-clip-'):source_name='clips/'+item['file']
        require(source_name in original and original[source_name]['sha256']==item['sha256'] and
                original[source_name]['bytes']==item['bytes'])
    expected_names=set()
    for source_name in original:
        if source_name.endswith('.mp4') or source_name in ('demo-deploy.jpg','demo-operate-and-trust.jpg') or (source_name.startswith('clips/') and source_name.endswith('.jpg')):
            expected_names.add({'demo.mp4':'demo-deploy.mp4','demo-operate.mp4':'demo-operate-and-trust.mp4'}.get(source_name,Path(source_name).name))
    require(set(names)==expected_names)
    return value


def verify_candidate(gh,directory,run):
    value=manifest(directory);signing=value['signing']
    require(signing==identity(run['id'],run['run_attempt'],run['head_sha']))
    media=[item['file'] for item in value['outputs'] if item['file'].endswith('.mp4')]
    subjects=media+[MANIFEST]
    extras={MANIFEST,BUNDLE,INTOTO}|{name+'.sigstore.json' for name in media}
    check_inventory(directory,value['outputs'],extras)
    expected={name:{'sha256':sha(Path(directory)/name)} for name in subjects}
    for name in subjects:
        results=gh.command(['attestation','verify',str(Path(directory)/name),'--bundle',str(Path(directory)/BUNDLE),
             '--repo',REPO,'--signer-workflow',REPO+'/'+WORKFLOW,'--signer-digest',run['head_sha'],'--source-digest',run['head_sha'],
             '--source-ref',REF,'--cert-oidc-issuer','https://token.actions.githubusercontent.com','--predicate-type','https://slsa.dev/provenance/v1','--format=json'])
        require(type(results) is list and len(results)==1)
        result=results[0]['verificationResult'];statement=result['statement'];certificate=result['signature']['certificate']
        require(certificate['issuer']=='https://token.actions.githubusercontent.com' and certificate['buildSignerURI']==IDENTITY and
                certificate['buildSignerDigest']==run['head_sha'] and certificate['sourceRepositoryDigest']==run['head_sha'] and
                certificate['sourceRepositoryIdentifier']=='1427088300' and certificate['sourceRepositoryOwnerIdentifier']=='5193877' and
                certificate['runInvocationURI']=='https://github.com/'+REPO+'/actions/runs/'+signing['run']+'/attempts/'+signing['attempt'])
        require(statement['_type']=='https://in-toto.io/Statement/v1' and statement['predicateType']=='https://slsa.dev/provenance/v1')
        require(len(statement['subject'])==len(expected) and {s['name']:s['digest'] for s in statement['subject']}==expected)
        definition=statement['predicate']['buildDefinition']
        require(definition['buildType']=='https://actions.github.io/buildtypes/workflow/v1' and
                definition['externalParameters']['workflow']=={'ref':REF,'repository':'https://github.com/'+REPO,'path':WORKFLOW})
        require(definition['internalParameters']['github']['event_name']=='workflow_dispatch' and
                definition['internalParameters']['github']['repository_id']=='1427088300' and
                definition['internalParameters']['github']['repository_owner_id']=='5193877')
        require(statement['predicate']['runDetails']['builder']['id']==IDENTITY)
        require(definition['resolvedDependencies']==[{'uri':'git+https://github.com/'+REPO+'@'+REF,'digest':{'gitCommit':run['head_sha']}}])
        require(statement['predicate']['runDetails']['metadata']['invocationId']==certificate['runInvocationURI'])
    for name in media:
        command=['cosign','verify-blob',str(Path(directory)/name),'--bundle',str(Path(directory)/(name+'.sigstore.json')),
                 '--certificate-identity',IDENTITY,'--certificate-oidc-issuer','https://token.actions.githubusercontent.com']
        # Use the same bounded/private subprocess transport, without a shell.
        gh.cosign(command)
    envelope=decode((Path(directory)/INTOTO).read_bytes())
    import base64
    require(envelope==decode((Path(directory)/BUNDLE).read_bytes())['dsseEnvelope'])
    require(decode(base64.b64decode(envelope['payload']))['subject']==statement['subject'])
    return value


def assets(gh,release_id,files):
    pages=gh.pages('repos/'+REPO+'/releases/'+str(release_id)+'/assets?per_page=100')
    found={}
    for item in (asset for page in pages for asset in page):
        require(item['name'] in files and item['name'] not in found and item['state']=='uploaded')
        local=files[item['name']]
        require(item['size']==local['bytes'] and item.get('digest')=='sha256:'+local['sha256'])
        found[item['name']]=item['id']
    return found


def publish(gh,run_id,attempt,directory):
    require(mode(run_id,attempt,False,os.environ.get('GITHUB_REF'))=='publish')
    run=run_identity(gh,run_id,attempt)
    extract(gh,run,'demo-signed-attempt-'+str(attempt),directory)
    value=verify_candidate(gh,directory,run);release_tag=tag(value['signing'])
    files={p.name:info(p) for p in Path(directory).iterdir()};require(len(files)<=128)
    # A tag's existence is not inferred from a failed release lookup.
    releases=gh.pages('repos/'+REPO+'/releases?per_page=100')
    matches=[item for page in releases for item in page if item['tag_name']==release_tag]
    require(len(matches)<=1)
    if not matches:
        refs=gh.api('repos/'+REPO+'/git/matching-refs/tags/'+release_tag)
        refs=[item for item in refs if item['ref']=='refs/tags/'+release_tag]
        require(len(refs)<=1)
        if refs:require(refs[0]['object']['type']=='commit' and refs[0]['object']['sha']==run['head_sha'])
        else:
            gh.command(['api','--method','POST','repos/'+REPO+'/git/refs','-f','ref=refs/tags/'+release_tag,
                        '-f','sha='+run['head_sha']])
        release=gh.command(['api','--method','POST','repos/'+REPO+'/releases',
                    '-f','tag_name='+release_tag,'-f','target_commitish='+run['head_sha'],
                    '-F','draft=true','-F','prerelease=true','-f','make_latest=false',
                    '-f','name=Demo recording '+str(run_id)+' attempt '+str(attempt),
                    '-f','body=Immutable signed recording candidate; source '+run['head_sha']+'. Not a package release.'])
    else:
        release=gh.api('repos/'+REPO+'/releases/'+str(matches[0]['id']))
    require(type(release.get('id')) is int and release['id']>0)
    release_path='repos/'+REPO+'/releases/'+str(release['id'])
    require(type(release['draft']) is bool and release['tag_name']==release_tag and release['prerelease'] is True and release['target_commitish']==run['head_sha'])
    tag_record=gh.api('repos/'+REPO+'/git/ref/tags/'+release_tag)
    require(tag_record['object']['type']=='commit' and tag_record['object']['sha']==run['head_sha'])
    present=assets(gh,release['id'],files)
    if not release['draft']:require(set(present)==set(files));return
    for name in sorted(set(files)-set(present)):
        require(info(Path(directory)/name)==files[name])
        gh.command(['release','upload',release_tag,str(Path(directory)/name),'--repo',REPO],json_output=False)
        require(name in assets(gh,release['id'],files))
    require(set(assets(gh,release['id'],files))==set(files))
    # Hash-confirm each actual uploaded asset using immutable IDs before promotion.
    for name,asset_id in assets(gh,release['id'],files).items():
        with tempfile.TemporaryFile() as stream:
            gh.command(['api','repos/'+REPO+'/releases/assets/'+str(asset_id),'-H','Accept: application/octet-stream'],stream,FILE)
            stream.seek(0);require(hashlib.file_digest(stream,'sha256').hexdigest()==files[name]['sha256'])
    require(run_identity(gh,run_id,attempt)['head_sha']==run['head_sha'])
    require(gh.api('repos/'+REPO+'/git/ref/tags/'+release_tag)['object']==tag_record['object'])
    current=gh.api(release_path)
    require(current['tag_name']==release_tag and current['id']==release['id'] and current['draft'] is True and current['prerelease'] is True and current['target_commitish']==run['head_sha'])
    gh.command(['api','--method','PATCH',release_path,'-F','draft=false','-f','make_latest=false'])
    final=gh.api(release_path)
    require(final['tag_name']==release_tag and final['id']==release['id'] and final['draft'] is False and final['prerelease'] is True and final['target_commitish']==run['head_sha'])
    require(gh.api('repos/'+REPO+'/git/ref/tags/'+release_tag)['object']==tag_record['object'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('mode','capture','prepare-sign','verify','publish'))
    parser.add_argument('--directory',default='videos')
    parser.add_argument('--app-source')
    args=parser.parse_args()
    try:
        require(os.environ.get('GITHUB_REPOSITORY')==REPO)
        if args.operation=='mode':
            selected=mode(os.environ.get('PUBLISH_RUN_ID',''),os.environ.get('PUBLISH_ATTEMPT',''),
                          os.environ.get('LEGACY_SIGN_ONLY','false')!='false',os.environ.get('GITHUB_REF'))
            with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as stream:stream.write('mode='+selected+'\n')
        elif args.operation=='capture':capture(args.directory,args.app_source)
        else:
            require(os.environ.get('GITHUB_REF')==REF)
            if args.operation=='publish':
                with tempfile.TemporaryDirectory() as temp:
                    publish(GitHub(),os.environ.get('PUBLISH_RUN_ID',''),os.environ.get('PUBLISH_ATTEMPT',''),temp)
            else:
                directory=Path(args.directory);directory.mkdir(parents=True,exist_ok=True)
                if args.operation=='prepare-sign':prepare_sign(GitHub(),directory)
                else:
                    run=run_identity(GitHub(),os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],False)
                    verify_candidate(GitHub(),directory,run)
        return 0
    except (ValueError,KeyError,TypeError,AttributeError,OSError,subprocess.SubprocessError,zipfile.BadZipFile):
        print('Demo publication refused; no historical asset changed or success inferred',file=__import__('sys').stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
