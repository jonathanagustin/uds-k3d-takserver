#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Direct bounded build of the pinned public Cesium dependency graph; no vcpkg fetch."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import signal
import selectors
import threading
import time
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('acquire',HERE/'acquire.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
CM=Path('/workspace/takx-native-tools/venv/bin/cmake')
NJ=Path('/workspace/takx-native-tools/venv/bin/ninja')
TARGETS=['CesiumUtility','CesiumGltf','CesiumGeometry','CesiumGeospatial','CesiumJsonReader','CesiumJsonWriter','CesiumGltfContent','CesiumGltfReader','CesiumGltfWriter','CesiumAsync','Cesium3DTiles','Cesium3DTilesReader','Cesium3DTilesWriter','Cesium3DTilesContent','CesiumRasterOverlays','Cesium3DTilesSelection','CesiumIonClient','CesiumQuantizedMeshTerrain']


def replace(path,old,new,transforms):
    before=path.read_bytes();raw=before.decode()
    if raw.count(old)!=1:raise ValueError('exact packaging transform preimage missing')
    path.write_text(raw.replace(old,new))
    transforms.append({'path':str(path),'preimage':a.native.digest_bytes(before) if hasattr(a.native,'digest_bytes') else __import__('hashlib').sha256(before).hexdigest(),'postimage':a.native.digest(path)})


def verify_resume(previous,snapshot,tools,providers,acquisition_sha256,order):
    """Rehash the complete retained producer before adopting any installed file."""
    frozen=json.loads(snapshot.read_text())
    if a.inventory(previous)!=frozen:raise ValueError('stopped dependency inputs changed')
    original=json.loads((previous/'producer.json').read_text())
    if original['tools']!=tools or original['providers']!=providers or original['sources_receipt_sha256']!=acquisition_sha256:raise ValueError('resume producer tools or sources differ')
    completed=json.loads((previous/'failed.json').read_text())['completed']
    if not completed or len(completed)!=len(set(completed)) or completed!=order[:len(completed)]:raise ValueError('resume action prefix differs')
    lineage={'fresh_dependency_build':False,'previous_output':str(previous),'stopped_inventory_sha256':a.native.digest(snapshot),'original_producer':original,'completed_actions':completed}
    if any(a.native.digest(Path(tool['path']))!=tool['sha256'] for tool in tools.values()):
        raise ValueError('actual resume tool changed')
    return lineage,completed,frozen


def relocate_pkgconfig(prefix,previous,transforms):
    """Change only the copied owned prefix literal in regular pkg-config metadata."""
    for path in prefix.rglob('*.pc'):
        if path.is_symlink() or not path.is_file():raise ValueError('pkg-config metadata must be regular')
        before=path.read_bytes();old=str(previous/'install').encode();new=str(prefix).encode()
        if old in before:
            path.write_bytes(before.replace(old,new))
            transforms.append({'path':str(path),'preimage':__import__('hashlib').sha256(before).hexdigest(),'postimage':a.native.digest(path)})
    for path in prefix.rglob('*.cmake'):
        if str(previous).encode() in path.read_bytes():raise ValueError('CMake export retained stopped producer path')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('sources','output','sqlcipher-proof','draco-proof'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--resume',type=Path)
    p.add_argument('--snapshot',type=Path)
    args=p.parse_args();out=a.native.external(args.output);src=args.sources.resolve()
    if out.exists():raise ValueError('fresh external output required')
    for root in (src,HERE,args.sqlcipher_proof.resolve(),args.draco_proof.resolve()):
        if out==root or root in out.parents or out in root.parents:raise ValueError('output overlaps input')
    receipt=json.loads((src/'acquired.json').read_text());plan=json.loads((HERE/'build-plan.json').read_text())
    providers=a.verify_providers(args.sqlcipher_proof,args.draco_proof)
    if providers!=receipt['providers']:raise ValueError('provider identity differs')
    for name,entry in receipt['sources'].items():
        if a.inventory(src/'source'/name)!=entry['files']:raise ValueError('acquired sources changed')
    tools={name:{'path':str(path.resolve()),'sha256':a.native.digest(path.resolve())} for name,path in [('cmake',CM),('ninja',NJ),('cc',Path(shutil.which('gcc'))),('cxx',Path(shutil.which('g++'))),('patch',Path(shutil.which('patch')))]}
    lineage=None;completed=[]
    if bool(args.resume)!=bool(args.snapshot):raise ValueError('resume requires exact stopped inventory')
    if args.resume:
        previous=args.resume.resolve();snapshot=args.snapshot.resolve()
        if out==previous or out in previous.parents or previous in out.parents:raise ValueError('resume output overlaps stopped producer')
        lineage,completed,frozen=verify_resume(previous,snapshot,tools,providers,a.native.digest(src/'acquired.json'),plan['topological_order'])
    out.mkdir();(out/'source').mkdir();(out/'build').mkdir();prefix=out/'install'
    transforms=[]
    if lineage:
        shutil.copytree(previous/'install',prefix)
        relocate_pkgconfig(prefix,previous,transforms)
    else:prefix.mkdir()
    env=os.environ.copy();env.update({'CMAKE_BUILD_PARALLEL_LEVEL':'1','MAKEFLAGS':'-j1','LC_ALL':'C','CC':tools['cc']['path'],'CXX':tools['cxx']['path'],'PKG_CONFIG_PATH':str(prefix/'lib/pkgconfig')})
    for key in ('CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','LD_LIBRARY_PATH','CMAKE_PREFIX_PATH'):env.pop(key,None)
    sql=args.sqlcipher_proof.resolve();draco=args.draco_proof.resolve()
    roots=';'.join(map(str,[prefix,sql/'openssl-install',draco/'install']))
    common=['-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DBUILD_SHARED_LIBS=OFF','-DCMAKE_C_STANDARD=99','-DCMAKE_CXX_STANDARD=17','-DCMAKE_CXX_EXTENSIONS=OFF','-DCMAKE_C_COMPILER='+tools['cc']['path'],'-DCMAKE_CXX_COMPILER='+tools['cxx']['path'],'-DCMAKE_MAKE_PROGRAM='+str(NJ),'-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_PREFIX_PATH='+roots,'-DCMAKE_FIND_ROOT_PATH='+roots,'-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY','-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DOPENSSL_ROOT_DIR='+str(sql/'openssl-install'),'-DOPENSSL_USE_STATIC_LIBS=TRUE']
    recipe=a.inventory(HERE);stages=list(completed);current='prepare'
    (out/'producer.json').write_text(json.dumps({'recipe':recipe,'tools':tools,'sources_receipt_sha256':a.native.digest(src/'acquired.json'),'providers':providers,'lineage':lineage,'fresh_dependency_build':not bool(lineage)},indent=2)+'\n')
    def command(argv,label,seconds=180):
        child=None;deadline=time.monotonic()+seconds;total=0;check=0
        try:
            with (out/(label+'.log')).open('xb') as log:
                child=subprocess.Popen(list(map(str,argv)),cwd=out,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
                with selectors.DefaultSelector() as poll:
                    poll.register(child.stdout,selectors.EVENT_READ)
                    while poll.get_map():
                        if time.monotonic()>deadline:raise ValueError('owned stage deadline exceeded')
                        if time.monotonic()>check:
                            if sum(f.stat().st_size for f in out.rglob('*') if f.is_file() and not f.is_symlink())>a.BUILD:raise ValueError('build output budget exceeded')
                            check=time.monotonic()+1
                        for key,_ in poll.select(.1):
                            block=os.read(key.fileobj.fileno(),65536)
                            if not block:poll.unregister(key.fileobj);continue
                            total+=len(block)
                            if total>16*1024**2:raise ValueError('stage log bound exceeded')
                            log.write(block)
                if child.wait(timeout=max(.001,deadline-time.monotonic())):raise ValueError('owned stage command failed')
        finally:
            if child:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait();child.stdout.close()
    try:
        for name in plan['topological_order']:
            if name in completed:continue
            current=name;entry=plan['plans'][name]
            if entry['selected_action']!='acquire_source':continue
            source=out/'source'/name;shutil.copytree(src/'source'/name,source)
            for number,patch in enumerate(entry['patches']):
                command([tools['patch']['path'],'--binary','--batch','--fuzz=0','-p1','-d',source,'-i',HERE/'ports'/name/patch],name+'-patch-'+str(number),30)
            if name=='ktx':(source/'other_include/zstd_errors.h').unlink()
            if entry['kind']=='install-real-headers':
                headers=([source/'picosha2.h'] if name=='picosha2' else list(source.glob('*.h')) if name=='stb' else [source/'include/mapbox/earcut.hpp'])
                for header in headers:
                    target=prefix/'include'/('mapbox/earcut.hpp' if name=='earcut-hpp' else header.name);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(header,target)
            else:
                selected=HERE/'ports/modp-base64' if name=='modp-base64' else source/entry['source_subdir']
                options=[x.replace('<verified-source>',str(source)) for x in entry['cmake_options']]
                command([CM,'-S',selected,'-B',out/'build'/name,*common,*options],name+'-configure')
                command([CM,'--build',out/'build'/name,'--parallel','1'],name+'-build',1800)
                command([CM,'--install',out/'build'/name],name+'-install')
            if name=='spdlog':
                replace(prefix/'include/spdlog/tweakme.h','// #define SPDLOG_FMT_EXTERNAL','#ifndef SPDLOG_FMT_EXTERNAL\n#define SPDLOG_FMT_EXTERNAL\n#endif',transforms)
                bundled=prefix/'include/spdlog/fmt/bundled'
                if bundled.exists():shutil.rmtree(bundled)
            if name=='uriparser':replace(prefix/'include/uriparser/UriBase.h','defined(URI_STATIC_BUILD)','1 /* defined(URI_STATIC_BUILD) */',transforms)
            stages.append(name);(out/'progress.json').write_text(json.dumps({'completed':stages,'current':current},indent=2)+'\n')
        # Minimal project-owned packaging adapter is emitted below; genuine upstream TUs stay intact.
        current='cesium';source=out/'source/cesium';shutil.copytree(src/'source/cesium',source)
        root=source/'CMakeLists.txt'
        text=root.read_text();start=text.index('if (NOT CMAKE_TOOLCHAIN_FILE)');end=text.index('# Set defaults',start)
        replace(root,text[start:end],'if(NOT CESIUM_PUBLIC_PREFIX)\n message(FATAL_ERROR "Explicit verified public prefix required")\nendif()\n\n',transforms)
        replace(root,'set(PACKAGE_BASE_DIR "${EZVCPKG_PACKAGES_DIR}")','set(PACKAGE_BASE_DIR "${CESIUM_PUBLIC_PREFIX}")',transforms)
        replace(root,'set(PACKAGE_BUILD_DIR "${EZVCPKG_DIR}")','set(PACKAGE_BUILD_DIR "${CESIUM_PUBLIC_PREFIX}")',transforms)
        text=root.read_text();start=text.index('if(VCPKG_MANIFEST_MODE)\n    set(PACKAGE_BUILD_DIR');end=text.index('\nendif()',start)+len('\nendif()')
        replace(root,text[start:end],'# Explicit verified public prefix replaces only vcpkg layout selection.',transforms)
        replace(root,'find_package(unofficial-sqlite3 CONFIG REQUIRED)','if(NOT TARGET SQLCipher::SQLCipher)\n message(FATAL_ERROR "Actual verified SQLCipher target required")\nendif()',transforms)
        replace(source/'CesiumAsync/CMakeLists.txt','unofficial::sqlite3::sqlite3','SQLCipher::SQLCipher',transforms)
        adapter=out/'parent';adapter.mkdir()
        (adapter/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.24)\nproject(PublicCesium LANGUAGES C CXX)\ninclude("'+str(HERE/'providers.cmake')+'")\nadd_subdirectory("'+str(source)+'" cesium)\n')
        (out/'prepared.json').write_text(json.dumps({'tools':tools,'recipe':recipe,'sources_receipt_sha256':a.native.digest(src/'acquired.json'),'provider_receipts':providers,'lineage':lineage,'transforms':transforms,'stages':stages},indent=2)+'\n')
        options=['-DVCPKG_MANIFEST_MODE=ON','-DVCPKG_MANIFEST_INSTALL=OFF','-DCESIUM_PUBLIC_PREFIX='+str(prefix),'-DCESIUM_TESTS_ENABLED=OFF','-DCESIUM_GLM_STRICT_ENABLED=ON','-DCESIUM_INSTALL_STATIC_LIBS=OFF','-DCESIUM_INSTALL_HEADERS=OFF','-DPUBLIC_SQLCIPHER_PREFIX='+str(sql/'sqlcipher-install')]
        command([CM,'-S',adapter,'-B',out/'build/cesium',*common,*options],'cesium-configure')
        command([CM,'--build',out/'build/cesium','--parallel','1','--target',*TARGETS],'cesium-build',1800)
        if lineage and a.inventory(previous)!=frozen:raise ValueError('stopped dependency producer changed during continuation')
        if any(a.native.digest(Path(tool['path']))!=tool['sha256'] for tool in tools.values()):raise ValueError('build tool changed')
        if a.inventory(HERE)!=recipe:raise ValueError('current recipe changed')
        if a.verify_providers(args.sqlcipher_proof,args.draco_proof)!=providers:raise ValueError('providers changed')
        (out/'complete.json').write_text(json.dumps({'actual_targets':TARGETS,'fresh_dependency_build':not bool(lineage),'fresh_cesium_build':True,'lineage':lineage,'full_cesium_build_acceptance':True,'full_kernel_sdk_acceptance':False,'prepared_sha256':a.native.digest(out/'prepared.json'),'installed':a.inventory(prefix),'tools':tools,'recipe':recipe},indent=2)+'\n')
        products=a.inventory(out)
        archives={name:item for name,item in products.items() if name.startswith('build/cesium/cesium/') and name.endswith('.a')}
        if len(archives)!=18:raise ValueError('eighteen genuine Cesium archive products required')
        (out/'observed-products.json').write_text(json.dumps({'schema_version':1,'kind':'observed-completed-public-cesium-graph','full_kernel_sdk_acceptance':False,'fresh_dependency_build':not bool(lineage),'fresh_cesium_build':True,'complete_sha256':a.native.digest(out/'complete.json'),'prepared_sha256':a.native.digest(out/'prepared.json'),'all_files':products,'actual_cesium_archives':archives},indent=2)+'\n')
        print('complete_cesium_graph_build=true full_kernel_sdk_acceptance=false')
    except Exception as exc:
        (out/'failed.json').write_text(json.dumps({'stage':current,'failure_class':str(exc),'completed':stages,'full_cesium_build_acceptance':False},indent=2)+'\n');raise RuntimeError('bounded public Cesium graph stopped; inspect private failed.json') from None
if __name__=='__main__':main()
