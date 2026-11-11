#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded source acquisition for a genuine complete Cesium Native graph."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tarfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('cesium_native_helper',HERE.parent/'native-deps/build.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
COMPRESSED=512*1024**2
EXPANDED=4*1024**3
BUILD=6*1024**3


def digest512(path):
    value=hashlib.sha512()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):value.update(chunk)
    return value.hexdigest()


def inventory(root):
    result={}
    for p in root.rglob('*'):
        if '__pycache__' in p.parts:continue
        if p.is_symlink():raise ValueError('source symlink refused')
        if p.is_file():result[str(p.relative_to(root))]={'bytes':p.stat().st_size,'sha256':native.digest(p)}
    return result


def verify_providers(sql_root,draco_root):
    values={}
    for family,root in [('sqlcipher',sql_root),('draco',draco_root)]:
        data=json.loads((root/'complete.json').read_text())
        folder=HERE.parent/('native-sqlcipher' if family=='sqlcipher' else 'native-deps')
        for name,sha in data['recipe'].items():
            if native.digest(folder/name)!=sha:raise ValueError('provider recipe changed')
        for tool in data['tools'].values():
            if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('provider tool changed')
        if family=='sqlcipher':
            if data.get('encryption_controls') is not True or data.get('whole_archive_PIC') is not True:
                raise ValueError('genuine SQLCipher controls unavailable')
            for name,expected in data['installed'].items():
                if native.inventory(root/(name+'-install'))!=expected:raise ValueError('provider installed files changed')
            if inventory(root/'source')!=json.loads((root/'source-inputs.json').read_text()):
                raise ValueError('provider sources changed')
            if data['archives']['sqlcipher']['sha256']!='b670845f28da0a3c717e991e9f18a334e08f6bc977190bbce6be864ca229f96d' or data['archives']['openssl']['sha256']!='603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a':
                raise ValueError('SQLCipher/OpenSSL actual provider differs')
        else:
            if data.get('draco_version')!='1.5.7' or data.get('codec_fixture_probe_passed') is not True or data.get('pic_link_passed') is not True:
                raise ValueError('real Draco codec/PIC proof unavailable')
            if native.inventory(root/'install')!=data['installed']:raise ValueError('Draco installed files changed')
            if native.digest(root/'sources.json')!=data['source_inventory_sha256']:raise ValueError('Draco source manifest differs')
            expected={x['path']:{'bytes':x['bytes'],'sha256':x['sha256']} for x in json.loads((root/'sources.json').read_text())}
            if inventory(root/'source')!=expected:raise ValueError('Draco sources changed')
        for name,item in data['probe_outputs'].items():
            path=root/native.relative(name)
            if path.is_symlink() or path.stat().st_size!=item['bytes'] or native.digest(path)!=item['sha256']:
                raise ValueError('provider control artifact changed')
        values[family]={'receipt_sha256':native.digest(root/'complete.json'),'source_bytes':sum(x['bytes'] for x in inventory(root/'source').values()),'actual_recipe':data['recipe']}
    return values


def download(entry,cache,budget,output):
    name=entry['port'];target=cache/(name+'.tar.gz')
    expected=entry.get('source_sha512')
    if target.exists():
        if target.is_symlink() or (expected and digest512(target)!=expected):raise ValueError('cached source differs')
        return target
    temporary=cache/(name+'.partial')
    if temporary.exists():raise ValueError('partial source acquisition preserved; new cache required')
    native.run(['/usr/bin/curl','--fail','--silent','--show-error','--location',
        '--max-time','110','--max-filesize',str(COMPRESSED-budget['compressed']),
        '--output',str(temporary),entry['source_url']],output,'download-'+name,120,limit=4096)
    received=temporary.stat().st_size
    if budget['compressed']+received>COMPRESSED:raise ValueError('compressed budget exceeded')
    if expected and digest512(temporary)!=expected:raise ValueError('upstream archive SHA512 differs')
    temporary.replace(target)
    budget['compressed']+=received
    return target


def extract(archive,destination,budget,git_tree=None,allow_ktx_notice=False,source_links=None,allow_zstd_tests=False):
    result={}
    attested={}
    if allow_ktx_notice:
        attested['NOTICE.md']=('LICENSE.md','LICENSE.md',1523,'0f92b4ce771585dfebc963ede074a30b4431b9e327911db44097d83ccf372128')
    if allow_zstd_tests:
        for name in ('unzstd','zstdcat'):
            attested['tests/cli-tests/bin/'+name]=('zstd','tests/cli-tests/bin/zstd',162,'808cc561268e42dd3ca2dcb1f39874661e19a568cc05374a1bff3d9d440e5022')
    with tarfile.open(archive) as source:
        members=source.getmembers()
        if len(members)>100000:raise ValueError('archive member bound exceeded')
        names=set();roots=set();regular=[];links=[]
        for item in members:
            path=native.relative(item.name)
            roots.add(path.parts[0])
            spec=attested.get('/'.join(path.parts[1:]))
            allowed_link=bool(spec and item.issym() and item.linkname==spec[0])
            if str(path) in names or not(item.isdir() or item.isfile() or allowed_link):raise ValueError('duplicate or nonregular archive input')
            if allowed_link:links.append((item,path))
            names.add(str(path))
            if item.isfile():regular.append((item,path))
        if len(roots)!=1:raise ValueError('single source root required')
        if len(links)!=len(attested):raise ValueError('expected exact attested archive links')
        expanded=sum(item.size for item,_ in regular)
        for _,path in links:
            spec=attested['/'.join(path.parts[1:])]
            target=[m for m,p in regular if '/'.join(p.parts[1:])==spec[1]]
            if len(target)!=1 or target[0].size!=spec[2]:raise ValueError('attested link target differs')
            expanded+=target[0].size
        if budget['expanded']+expanded>EXPANDED:raise ValueError('expanded source budget exceeded')
        destination.mkdir()
        for item,path in regular:
            relative='/'.join(path.parts[1:])
            if not relative:raise ValueError('source root is a file')
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
            sha=hashlib.sha256();git=hashlib.sha1();git.update(('blob '+str(item.size)+'\0').encode())
            with source.extractfile(item) as incoming,target.open('xb') as outgoing:
                while True:
                    chunk=incoming.read(65536)
                    if not chunk:break
                    outgoing.write(chunk);sha.update(chunk);git.update(chunk)
            target.chmod(0o755 if item.mode&0o111 else 0o644)
            result[relative]={'bytes':item.size,'sha256':sha.hexdigest()}
            if git_tree is not None:
                expected=git_tree.get(relative)
                if not expected or expected['sha']!=git.hexdigest() or expected['size']!=item.size:
                    raise ValueError('Cesium source does not match pinned Git blob')
        for _,path in links:
            relative='/'.join(path.parts[1:]);spec=attested[relative]
            target=destination/spec[1]
            if native.digest(target)!=spec[3]:raise ValueError('attested link target bytes differ')
            shutil.copyfile(target,destination/relative)
            (destination/relative).chmod(target.stat().st_mode & 0o777)
            post={'bytes':target.stat().st_size,'sha256':native.digest(target)}
            result[relative]=post
            if source_links is not None:source_links[relative]={'logical_target':spec[0],'materialized_postimage':post}
        if git_tree is not None and set(result)!=set(git_tree):raise ValueError('Cesium source archive is incomplete')
        budget['expanded']+=expanded
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','cache','sqlcipher_proof','draco_proof'):
        parser.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    args=parser.parse_args()
    output,cache=native.external(args.output),native.external(args.cache)
    if output.exists() or output==cache or output in cache.parents or cache in output.parents:
        raise ValueError('new separate output required')
    for proof in (args.sqlcipher_proof,args.draco_proof):
        if output==proof.resolve() or proof.resolve() in output.parents:raise ValueError('output overlaps provider proof')
    lock=json.loads((HERE/'inputs.lock.json').read_text())
    if lock['vcpkg_commit']!='1de2026f28ead93ff1773e6e680387643e914ea1' or lock['cesium']['commit']!='f8b38abbbaa24ec2984ff663182240d06285b36c':
        raise ValueError('unreviewed source pins')
    for item in json.loads((HERE/'metadata.lock.json').read_text()):
        path=HERE/native.relative(item['path'])
        if path.is_symlink() or path.stat().st_size!=item['bytes'] or native.digest(path)!=item['sha256']:
            raise ValueError('pinned port metadata differs')
    providers=verify_providers(args.sqlcipher_proof,args.draco_proof)
    budget={'compressed':0,'expanded':sum(v['source_bytes'] for v in providers.values())}
    cache.mkdir(parents=True,exist_ok=True)
    if any(p.is_symlink() or not p.is_file() for p in cache.iterdir()):raise ValueError('unknown source cache entry')
    budget['compressed']=sum(p.stat().st_size for p in cache.iterdir())
    if budget['compressed']>COMPRESSED or budget['expanded']>EXPANDED:raise ValueError('existing input budget exceeded')
    output.mkdir();output.chmod(0o700);(output/'source').mkdir()
    records={};current='prepare'
    initial=inventory(HERE)
    try:
        entries=[{'port':'cesium',**lock['cesium']}]+[e for e in lock['ports'] if e['selected_action']=='acquire_source']
        tree={e['path']:e for e in json.loads((HERE/'cesium-tree.json').read_text()) if e['type']=='blob'}
        for entry in entries:
            current=entry['port']
            archive=download(entry,cache,budget,output)
            links={}
            source=extract(archive,output/'source'/current,budget,tree if current=='cesium' else None,current=='ktx',links,current=='zstd')
            records[current]={'source_url':entry['source_url'],'sha512':digest512(archive),'sha256':native.digest(archive),
                'bytes':archive.stat().st_size,'files':source,'logical_source_links':links,
                'licenses':{p:v for p,v in source.items() if Path(p).name.lower().startswith(('license','copying','notice','copyright'))},'expanded_bytes':sum(p['bytes'] for p in source.values())}
            (output/'acquisition-progress.json').write_text(json.dumps({'current':current,'budget':budget,'sources':records},sort_keys=True)+'\n')
        if inventory(HERE)!=initial or verify_providers(args.sqlcipher_proof,args.draco_proof)!=providers:
            raise ValueError('recipe/provider changed during acquisition')
        (output/'acquired.json').write_text(json.dumps({'sources':records,'providers':providers,'budget':budget,
            'recipe':initial,'full_cesium_build_acceptance':False,'full_kernel_sdk_acceptance':False},sort_keys=True)+'\n')
        print('bounded_complete_source_acquisition=true')
    except Exception as error:
        (output/'failed.json').write_text(json.dumps({'source':current,'failure_class':str(error) if isinstance(error,ValueError) else type(error).__name__,
            'budget':budget,'full_cesium_build_acceptance':False},indent=2)+'\n')
        raise RuntimeError('bounded Cesium acquisition stopped; inspect private failed.json') from None


if __name__=='__main__':main()
