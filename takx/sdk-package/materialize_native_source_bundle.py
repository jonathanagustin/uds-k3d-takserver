#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline constructor of reviewed byte-only producer source evidence; never imports it."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

HERE=Path(__file__).resolve().parent

def require(value,message):
    if not value:raise ValueError(message)

def sha(value):return hashlib.sha256(value).hexdigest()

def materialize(repository,output,manifest_path,known):
    repository=Path(repository).resolve();output=Path(output).absolute();manifest_path=Path(manifest_path).resolve()
    raw=manifest_path.read_bytes();require(len(raw)<=128*1024 and sha(raw) in known,'consumer-reviewed manifest required')
    manifest=json.loads(raw);pin=known[sha(raw)]
    require(manifest['profile']==pin['profile'] and manifest['gitSourceCommit']==pin['git_source_commit'] and
            manifest['sourceCount']==pin['source_count']==len(manifest['files']),'manifest/source pin differs')
    require(not output.exists() and not output.is_symlink() and not any(p.is_symlink() for p in (output.parent,*output.parent.parents)), 'fresh canonical output required')
    for source in (repository,HERE.parent.parent):
        require(not output.is_relative_to(source) and not source.is_relative_to(output),'output overlaps source repository')
    env={**os.environ,'GIT_NO_LAZY_FETCH':'1','GIT_TERMINAL_PROMPT':'0'}
    def git(*args):
        return subprocess.run(['git','--no-lazy-fetch','-c','protocol.allow=never','-C',str(repository),*args],
            check=True,capture_output=True,timeout=10,env=env).stdout
    bodies={};recipe={}
    for row in manifest['files']:
        origin=row['origin'];commit=origin['commit'];path=origin['repositoryPath'];target=PurePosixPath(row['snapshotPath'])
        require(commit==manifest['gitSourceCommit'] and path==row['repositoryPath'] and
                target.parts[:2]==('source','takx') and not target.is_absolute() and '..' not in target.parts and '\\' not in str(target), 'fixed source origin/path required')
        size=int(git('cat-file','-s',commit+':'+path).strip());require(0<size<=2*1024**2,'bounded source blob required')
        body=git('show',commit+':'+path)
        require(len(body)==size and sha(body)==origin['blobSHA256'] and git('rev-parse',commit+':'+path).decode().strip()==origin['blobOID'],'original Git blob differs')
        if origin['kind']=='exact-license-prefix-preimage':
            prefix=origin['removedPrefixUTF8'].encode()
            require(prefix and sha(prefix)==origin['removedPrefixSHA256'] and body.startswith(prefix),'exact declared license prefix differs')
            body=body[len(prefix):]
        else:require(origin['kind']=='git-blob','unsupported source origin')
        require(len(body)==row['bytes'] and sha(body)==row['sha256'],'original recipe preimage differs')
        require(row['snapshotPath'] not in bodies and row['receiptRecipePath'] not in recipe,'duplicate source member')
        bodies[row['snapshotPath']]=body;recipe[row['receiptRecipePath']]=row['sha256']
    require(sha(json.dumps(recipe,sort_keys=True,separators=(',',':')).encode())==pin['native_recipe_sha256'],'source recipe differs')
    recipe_bytes=(json.dumps(recipe,sort_keys=True,indent=2)+'\n').encode()
    require(manifest['recipeFile']=={'path':'recipe.json','bytes':len(recipe_bytes),'sha256':sha(recipe_bytes)},'frozen recipe JSON differs')
    bodies.update({'recipe.json':recipe_bytes,'manifest.json':raw})
    output.mkdir(mode=0o700)
    for name,body in bodies.items():
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
        with os.fdopen(fd,'wb') as stream:stream.write(body)
        target.chmod(0o444)
    for directory in sorted([p for p in output.rglob('*') if p.is_dir()],key=lambda p:len(p.parts),reverse=True):directory.chmod(0o555)
    output.chmod(0o555)
    return {'manifest_sha256':sha(raw),'native_recipe_sha256':pin['native_recipe_sha256'],'source_count':len(recipe),'historical_code_executed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repository',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',default='public-kernel-native-45-v1');args=parser.parse_args()
    require(args.profile=='public-kernel-native-45-v1','unsupported source profile')
    known=json.loads((HERE/'inputs.lock.json').read_text())['native_source_snapshots']
    result=materialize(args.repository,args.output,HERE/'native-source-snapshots'/f'{args.profile}.json',known)
    print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
