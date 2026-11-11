#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Export three checked actual TAKX postimages; never mutate official source or build artifacts."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition):
    if not condition:raise ValueError('mission admission projection refused')


def profile():
    value=json.loads((ROOT/'admission-profile.json').read_text())
    lock=json.loads((ROOT/'inputs.lock.json').read_text())
    require(type(value['schema']) is int and value['schema']==1 and value['profileId']=='takx57-mission-admission-v2' and value['sourceRevision']==lock['takx']['revision'])
    require(set(value['sources'])=={
        'Platform/src/main/java/gov/tak/platform/datapackage/PackageReader.java',
        'Platform/src/main/java/gov/tak/platform/datapackage/ZipReader.java',
        'Platform/src/main/java/gov/tak/platform/datapackage/PackageImporter.java',
        'Client/src/main/java/gov/tak/core/comms/takserver/DataPackageManager.java'})
    baseline={**lock['takx']['sources'],**lock['takx']['integrationSources']}
    for path,item in value['sources'].items():
        require(item['preSha256']==baseline[path] and item['scope']==path.split('/')[0])
    patch=ROOT/value['patch']['file']
    require(patch.resolve().is_relative_to((ROOT/'patches').resolve()) and sha(patch)==value['patch']['sha256'])
    return value


def export(source,output):
    source,output=Path(source),Path(output)
    value=profile();profile_sha=sha(ROOT/'admission-profile.json')
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    require(revision.returncode==0 and revision.stdout.decode().strip()==value['sourceRevision'])
    for path,item in value['sources'].items():require(sha(source/path)==item['preSha256'])
    require(not output.exists() and not output.is_symlink())
    require(not output.resolve().is_relative_to(source.resolve()) and not source.resolve().is_relative_to(output.resolve()))
    require(shutil.disk_usage(output.parent).free>2*1024**3+1024**2)
    output.mkdir(mode=0o700);projected=output/'source';projected.mkdir()
    for path in value['sources']:
        destination=projected/path;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/path,destination)
    patch=(ROOT/value['patch']['file']).resolve()
    for options in (['--check'],[]):
        result=subprocess.run(['git','apply','--whitespace=error',*options,str(patch)],cwd=projected,
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
        require(result.returncode==0 and len(result.stdout)<=65536 and len(result.stderr)<=65536)
    require({path.relative_to(projected).as_posix() for path in projected.rglob('*') if path.is_file()}==set(value['sources']))
    for path,item in value['sources'].items():require(sha(projected/path)==item['postSha256'])
    require(sha(ROOT/'admission-profile.json')==profile_sha and sha(patch)==value['patch']['sha256'])
    for path,item in value['sources'].items():require(sha(source/path)==item['preSha256'])
    receipt={'schema':1,'profileId':value['profileId'],'profileSha256':profile_sha,
             'patchSha256':value['patch']['sha256'],'sourceRevision':value['sourceRevision'],
             'projectorSha256':sha(__file__),'sources':value['sources'],
             'fullPlatformCompileAcceptance':False,'fullClientCompileAcceptance':False,'nativeTransferAcceptance':False}
    (output/'projection.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    return receipt


def verify(output):
    output=Path(output).absolute();require(output.is_dir() and not output.is_symlink() and output.resolve()==output)
    value=profile();receipt=json.loads((output/'projection.json').read_text())
    require(type(receipt['schema']) is int and receipt['schema']==1 and receipt['profileId']==value['profileId'] and
            receipt['profileSha256']==sha(ROOT/'admission-profile.json') and receipt['patchSha256']==value['patch']['sha256'] and
            receipt['sourceRevision']==value['sourceRevision'] and receipt['projectorSha256']==sha(__file__) and receipt['sources']==value['sources'])
    require(receipt.get('fullPlatformCompileAcceptance') is False and receipt.get('fullClientCompileAcceptance') is False and receipt.get('nativeTransferAcceptance') is False)
    projected=output/'source'
    require(projected.is_dir() and not projected.is_symlink() and projected.resolve()==projected and not any(path.is_symlink() for path in projected.rglob('*')))
    require({path.relative_to(projected).as_posix() for path in projected.rglob('*') if path.is_file()}==set(value['sources']))
    for path,item in value['sources'].items():
        target=projected/path
        require(not target.is_symlink() and target.resolve().is_relative_to(projected.resolve()) and sha(target)==item['postSha256'])
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    try:export(args.source,args.output);print('Checked actual mission admission source projection exported; no compile acceptance')
    except (ValueError,KeyError,OSError,subprocess.SubprocessError):parser.exit(1,'Source projection refused; preserve failed output and use a fresh path\n')


if __name__=='__main__':main()
