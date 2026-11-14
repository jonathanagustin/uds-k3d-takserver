#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded genuine six-library LibKML1.3/Expat2.10 source profile."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import tarfile
import time
HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
native=module('kml_native',HERE.parent/'native-deps/build.py')
scene=module('kml_scene',HERE.parent/'kernel-scene/build.py')
scene_kernel=module('kml_scene_kernel',HERE.parent/'kernel-scene/kernel.py')
las=module('kml_las',HERE.parent/'native-las/build.py')
OUTPUT=2*1024**3


def inventory(root):
    found={}
    for p in root.rglob('*'):
        if p.is_symlink():raise ValueError('input symlink refused')
        if not(p.is_file() or p.is_dir()):raise ValueError('nonregular input refused')
        if p.is_file():found[str(p.relative_to(root))]={'bytes':p.stat().st_size,'sha256':native.digest(p)}
    return found


def extract(path,dest,entry):
    if path.is_symlink() or path.stat().st_size!=entry['bytes'] or native.digest(path)!=entry['sha256']:raise ValueError('archive identity differs')
    with tarfile.open(path) as tar:
        members=tar.getmembers();names=set();roots=set();total=0
        for m in members:
            p=native.relative(m.name);roots.add(p.parts[0])
            if m.name in names or not(m.isfile() or m.isdir()):raise ValueError('duplicate or nonregular source')
            names.add(m.name);total+=m.size if m.isfile() else 0
        if len(roots)!=1 or len(members)>10000 or total>512*1024**2:raise ValueError('expanded source bound exceeded')
        dest.mkdir()
        for m in members:
            if not m.isfile():continue
            target=dest/Path(*native.relative(m.name).parts[1:]);target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as incoming,target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)
            target.chmod(0o755 if m.mode&0o111 else 0o644)
    return total


def verify_las(root):
    data=json.loads((root/'complete.json').read_text())
    if data.get('whole_archive_pic') is not True or not data.get('las_laz_semantics'):raise ValueError('LibLAS producer controls missing')
    for name,sha in data['recipe'].items():
        if native.digest(HERE.parent/'native-las'/name)!=sha:raise ValueError('LibLAS recipe differs')
    if native.inventory(root/'install')!=data['installed']:raise ValueError('LibLAS installed inventory differs')
    if native.digest(root/'sources.json')!=data['source_inventory_sha256']:raise ValueError('LibLAS source manifest differs')
    las.check_sources(root/'source',json.loads((root/'sources.json').read_text()),data['generated_source_files'])
    for tool in data['tools'].values():
        if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('LibLAS tool differs')
    boost=root/'source/libLAS/find_package/boost'
    if not re.search(r'^#define BOOST_VERSION 107700$',(boost/'boost/version.hpp').read_text(),re.M):raise ValueError('actual Boost1.77 required')
    return boost,{'receipt_sha256':native.digest(root/'complete.json'),'boost_headers':inventory(boost/'boost')}


def verify_cesium_lineage(complete,snapshot):
    lineage=complete.get('lineage')
    if lineage is None:
        if complete.get('fresh_dependency_build') is not True or complete.get('fresh_cesium_build') is not True:
            raise ValueError('fresh Cesium build evidence required')
        if snapshot is not None:
            raise ValueError('fresh Cesium producer has no stopped snapshot')
        return
    if complete.get('fresh_dependency_build') is not False or snapshot is None:
        raise ValueError('continued Cesium requires original stopped snapshot')
    previous=Path(lineage['previous_output'])
    if native.digest(snapshot)!=lineage['stopped_inventory_sha256'] or inventory(previous)!=json.loads(snapshot.read_text()):
        raise ValueError('Cesium original dependency producer changed')


def verify_cesium(root,snapshot):
    data=json.loads((root/'observed-products.json').read_text());complete=json.loads((root/'complete.json').read_text())
    if not complete.get('full_cesium_build_acceptance') or native.digest(root/'complete.json')!=data['complete_sha256']:raise ValueError('Cesium actual graph evidence missing')
    for name,item in data['all_files'].items():
        p=root/native.relative(name)
        if p.is_symlink() or p.stat().st_size!=item['bytes'] or native.digest(p)!=item['sha256']:raise ValueError('Cesium producer files changed')
    verify_cesium_lineage(complete,snapshot)
    for tool in complete['tools'].values():
        if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('Cesium tool differs')
    prefix=root/'install';header=(prefix/'include/uriparser/UriBase.h').read_text()
    for name,value in [('MAJOR','0'),('MINOR','9'),('RELEASE','8')]:
        if not re.search(r'#\s*define URI_VER_'+name+r'\s+'+value+r'\b',header):raise ValueError('actual uriparser0.9.8 required')
    return prefix,{'observed_receipt_sha256':native.digest(root/'observed-products.json'),'uriparser_archive_sha256':native.digest(prefix/'lib/liburiparser.a'),'uriparser_headers':inventory(prefix/'include/uriparser')}


def verify_minizip(root,proof,reference):
    data=scene.producer.normalize(json.loads((proof/'dependencies-built.json').read_text()))
    if data.get('schema_exercise_only'):raise ValueError('schema exercise is not product evidence')
    prefix='libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip/'
    expected={k[len(prefix):]:v for k,v in data['source_postimages'].items() if k.startswith(prefix)}
    actual=root/'source/libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip'
    if not expected or inventory(actual)!=expected or inventory(reference)!=expected:raise ValueError('minizip actual source/header identity differs')
    for name,sha in data['bindings']['files'].items():
        p=root/native.relative(name)
        if p.is_symlink() or native.digest(p)!=sha:raise ValueError('minizip completed binding changed')
    for path,sha in data['bindings']['tools'].items():
        if native.digest(Path(path))!=sha:raise ValueError('minizip producer tool changed')
    if (root/'minizip-positive-controls.log').read_bytes()!=b'real_minizip_binary_crc_correct_and_wrong_password_controls=true\n':raise ValueError('minizip controls missing')
    archive=root/'minizip/libminizip.a';objects=[root/'minizip'/(name+'.o') for name in ('ioapi','iomem_simple','unzip','zip')]
    if scene_kernel.archive_members(archive)!=Counter(native.digest(p) for p in objects):raise ValueError('minizip four whole objects differ')
    return archive,{'receipt_sha256':native.digest(proof/'dependencies-built.json'),'archive_sha256':native.digest(archive),'source_postimages':expected,'objects':{p.name:native.digest(p) for p in objects}}


def recipe():
    names=['build.py','CMakeLists.txt','KMLProbe.cpp','ExpatProbe.c','inputs.lock.json','source-postimages.json','patches/libkml-pgsc.patch','patches/minizip-zlib-crc-type.patch','patches/expat-pgsc.patch','../native-deps/build.py','../native-las/build.py','../native-assimp/build.py','../kernel-scene/build.py','../kernel-scene/kernel.py','../kernel-scene/producer.py']
    return {name:native.digest(HERE/name) for name in names}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','libkml-archive','expat-archive','las-proof','assimp-proof','minizip-root','minizip-proof','cesium-proof'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--cesium-stopped-snapshot',type=Path)
    args=p.parse_args();out=native.external(args.output)
    if out.exists():raise ValueError('new external output required')
    for name,value in vars(args).items():
        if name=='output' or value is None:continue
        if out==value.resolve() or out in value.resolve().parents or value.resolve() in out.parents:raise ValueError('output overlaps input')
    if HERE==out or HERE in out.parents or out in HERE.parents:raise ValueError('output overlaps recipe')
    lock=json.loads((HERE/'inputs.lock.json').read_text());post=json.loads((HERE/'source-postimages.json').read_text())
    if native.digest(HERE/'source-postimages.json')!=lock['source_postimages_sha256']:raise ValueError('source postimage lock changed')
    if sum(lock[key]['bytes'] for key in ('expat','libkml'))>32*1024**2:raise ValueError('compressed source budget exceeded')
    for name,sha in lock['patches'].items():
        if native.digest(HERE/'patches'/name)!=sha:raise ValueError('patch identity differs')
    initial=recipe();tools={name:{'path':str(Path(shutil.which(name)).resolve()),'sha256':native.digest(Path(shutil.which(name)).resolve())} for name in ('gcc','g++','ar','patch','readelf')}
    cm=Path('/workspace/takx-native-tools/venv/bin/cmake');nj=Path('/workspace/takx-native-tools/venv/bin/ninja')
    for name,path in [('cmake',cm),('ninja',nj)]:tools[name]={'path':str(path),'sha256':native.digest(path)}
    out.mkdir();out.chmod(0o700);(out/'source').mkdir();deadline=time.monotonic()+1200;current='source'
    env=os.environ.copy()
    for name in ('CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','LD_LIBRARY_PATH','CMAKE_PREFIX_PATH'):env.pop(name,None)
    env.update({'LC_ALL':'C','CMAKE_BUILD_PARALLEL_LEVEL':'1','MAKEFLAGS':'-j1'})
    def run(argv,name,seconds=120,capture=False):
        child=None;data=bytearray();count=0;check=0;limit=min(deadline,time.monotonic()+seconds)
        try:
            with (out/(name+'.log')).open('xb') as log:
                child=subprocess.Popen(list(map(str,argv)),cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
                with selectors.DefaultSelector() as poll:
                    poll.register(child.stdout,selectors.EVENT_READ)
                    while poll.get_map():
                        if time.monotonic()>limit:raise ValueError('owned stage deadline exceeded')
                        if time.monotonic()>check:
                            if sum(f.stat().st_size for f in out.rglob('*') if f.is_file() and not f.is_symlink())>OUTPUT:raise ValueError('output budget exceeded')
                            check=time.monotonic()+1
                        for key,_ in poll.select(.1):
                            b=os.read(key.fileobj.fileno(),65536)
                            if not b:poll.unregister(key.fileobj);continue
                            count+=len(b)
                            if count>16*1024**2:raise ValueError('stage log limit exceeded')
                            log.write(b)
                            if capture:data.extend(b)
                if child.wait(timeout=max(.001,limit-time.monotonic())):raise ValueError('owned command failed')
        finally:
            if child:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait();child.stdout.close()
        return bytes(data)
    try:
        expanded=extract(args.libkml_archive,out/'source/libkml',lock['libkml'])+extract(args.expat_archive,out/'source/expat',lock['expat'])
        if expanded>512*1024**2:raise ValueError('combined source bound exceeded')
        kml=out/'source/libkml';expat=out/'source/expat';mz=kml/'third_party/zlib-1.2.3/contrib/minizip'
        run(['/usr/bin/patch','--batch','--fuzz=0','-p0','-d',kml,'-i',HERE/'patches/libkml-pgsc.patch'],'patch-libkml')
        run(['/usr/bin/patch','--batch','--fuzz=0','-p1','-d',mz,'-i',HERE/'patches/minizip-zlib-crc-type.patch'],'patch-minizip-reference')
        if inventory(kml)!=post['libkml'] or inventory(expat)!=post['expat']:raise ValueError('exact whole source postimages differ')
        current='providers';boost,boost_fact=verify_las(args.las_proof)
        scene.verify_dependency(args.assimp_proof,'assimp');zprefix=args.assimp_proof/'zlib-install'
        uprefix,uri_fact=verify_cesium(args.cesium_proof,args.cesium_stopped_snapshot)
        minizip,mz_fact=verify_minizip(args.minizip_root,args.minizip_proof,mz)
        providers={'boost':boost_fact,'uriparser':uri_fact,'minizip':mz_fact,'assimp_zlib_receipt_sha256':native.digest(args.assimp_proof/'complete.json')}
        (out/'configuration.json').write_text(json.dumps({'recipe':initial,'tools':tools,'providers':providers,'fresh_libkml_build':True,'fresh_expat_build':True,'new_source_compressed':sum(lock[x]['bytes'] for x in ('libkml','expat')),'expanded_source_bytes':expanded},indent=2)+'\n')
        current='expat';eprefix=out/'expat-install'
        common=['-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DCMAKE_MAKE_PROGRAM='+str(nj),'-DCMAKE_C_COMPILER='+tools['gcc']['path'],'-DCMAKE_CXX_COMPILER='+tools['g++']['path'],'-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF']
        run([cm,'-S',expat,'-B',out/'expat-build',*common,'-DCMAKE_INSTALL_PREFIX='+str(eprefix),'-DEXPAT_BUILD_TOOLS=OFF','-DEXPAT_BUILD_EXAMPLES=OFF','-DEXPAT_BUILD_TESTS=OFF','-DEXPAT_SHARED_LIBS=OFF'],'expat-configure')
        run([cm,'--build',out/'expat-build','--parallel','1'],'expat-build',1200)
        run([cm,'--install',out/'expat-build'],'expat-install')
        run([tools['gcc']['path'],'-I'+str(eprefix/'include'),HERE/'ExpatProbe.c',eprefix/'lib/libexpat.a','-o',out/'expat-probe'],'expat-probe-link')
        if run([out/'expat-probe'],'expat-probe',10,True)!=b'expat_2.10.0_real_parser=true\n':raise ValueError('actual Expat version/parser differs')
        current='libkml';prefix=out/'install'
        options=['-DKML_SOURCE='+str(kml),'-DEXPAT_PREFIX='+str(eprefix),'-DBOOST_SOURCE='+str(boost),'-DMINIZIP_ARCHIVE='+str(minizip),'-DMINIZIP_INCLUDE='+str(mz.parent),'-DZLIB_PREFIX='+str(zprefix),'-DURIPARSER_PREFIX='+str(uprefix),'-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_CXX_STANDARD=17']
        run([cm,'-S',HERE,'-B',out/'kml-build',*common,*options],'kml-configure')
        run([cm,'--build',out/'kml-build','--parallel','1'],'kml-build',1200)
        run([cm,'--install',out/'kml-build'],'kml-install')
        current='strict-shared';libs=[prefix/'lib'/('libkml'+family+'.a') for family in lock['families']]
        shared=out/'libkml-profile.so';run([tools['g++']['path'],'-shared','-Wl,--no-undefined','-Wl,--exclude-libs,libexpat.a','-Wl,--whole-archive',*libs,minizip,eprefix/'lib/libexpat.a',uprefix/'lib/liburiparser.a',zprefix/'lib/libz.a','-Wl,--no-whole-archive','-o',shared],'strict-pic-shared')
        symbols=run([tools['readelf']['path'],'--dyn-syms','--wide',shared],'shared-dynamic-symbols',30,True)
        if re.search(rb'\bXML_[A-Za-z0-9_]+',symbols):raise ValueError('private Expat escaped dynamic symbol table')
        current='consumer';probe=out/'kml-probe'
        run([tools['g++']['path'],'-std=c++17','-I'+str(prefix/'include'),'-I'+str(boost),'-I'+str(eprefix/'include'),HERE/'KMLProbe.cpp',shared,'-Wl,-rpath,'+str(out),'-ldl','-o',probe],'probe-compile')
        text=run([probe,out],'probe',20,True)
        if not text.startswith(b'kml_dom_coordinates_kmz_uri_negative_controls=true\n'):raise ValueError('actual KML controls missing')
        providers_loaded={line[9:] for line in text.decode().splitlines() if line.startswith('provider=')}
        allowed=re.compile(r'^(?:libc|libm|libpthread|libdl|librt|libstdc\+\+|libgcc_s)\.so(?:\..*)?$|^ld-linux-x86-64\.so\.2$')
        if str(shared) not in providers_loaded or any(Path(x)!=shared and not allowed.fullmatch(Path(x).name) for x in providers_loaded):raise ValueError('unexpected runtime provider')
        if inventory(kml)!=post['libkml'] or inventory(expat)!=post['expat']:raise ValueError('vendor source changed')
        if recipe()!=initial or any(native.digest(Path(tool['path']))!=tool['sha256'] for tool in tools.values()):raise ValueError('recipe or tools changed')
        if verify_las(args.las_proof)[1]!=boost_fact or verify_cesium(args.cesium_proof,args.cesium_stopped_snapshot)[1]!=uri_fact or verify_minizip(args.minizip_root,args.minizip_proof,mz)[1]!=mz_fact:raise ValueError('reused provider changed')
        scene.verify_dependency(args.assimp_proof,'assimp')
        data={'schema_version':1,'profile':'public-libkml-native','version':'1.3.0','expat_version':'2.10.0','private_static_expat_dynsym_verified':True,'recipe':initial,'tools':tools,'providers':providers,'source_postimages':post,'installed':inventory(prefix),'expat_installed':inventory(eprefix),'production_tus':lock['families'],'strict_whole_archive_pic':True,'dom_kmz_uri_controls':True,'network_io_acceptance':False,'full_kernel_sdk_acceptance':False,'loaded_providers':sorted(providers_loaded),'objects':inventory(out/'kml-build'),'shared':{'bytes':shared.stat().st_size,'sha256':native.digest(shared)},'probe_outputs':{p.name:{'bytes':p.stat().st_size,'sha256':native.digest(p)} for p in (probe,out/'probe.log')}}
        (out/'complete.json').write_text(json.dumps(data,indent=2)+'\n')
        (out/'all-products.json').write_text(json.dumps(inventory(out),indent=2)+'\n')
        print('genuine_six_library_libkml_controls=true full_kernel_sdk_acceptance=false')
    except Exception as exc:
        (out/'failed.json').write_text(json.dumps({'stage':current,'failure_class':str(exc),'full_kernel_sdk_acceptance':False},indent=2)+'\n');raise RuntimeError('bounded KML profile stopped; inspect private failure evidence') from None
if __name__=='__main__':main()
