#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline source-backed public Kernel native profile; scaffold acceptance gates explicit."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
sys.dont_write_bytecode=True
import providers as p
import sources
import audit
import toolchain
HERE=Path(__file__).resolve().parent
RUNNER_PATH=HERE.parent/'native-commoncommo/runner.py'
_runner_spec=importlib.util.spec_from_file_location('kernel_native_runner',RUNNER_PATH)
runner=importlib.util.module_from_spec(_runner_spec);_runner_spec.loader.exec_module(runner)
LOCK_SHA='40f09c3ecb8020fb8d9e402f4c3a0415ecad6ef8b80c69d37aa4d25809f4a70e'

def validate_lock(lock):
    if hashlib.sha256(json.dumps(lock,sort_keys=True).encode()).hexdigest()!=LOCK_SHA:raise ValueError('unreviewed Kernel source/tool/patch/feature contract')
    for name,sha in lock['locks'].items():
        if p.digest(p.regular(HERE/name))!=sha:raise ValueError('source registry differs')
    for name,entry in lock['patches'].items():
        if p.digest(p.regular(HERE/'patches'/name))!=entry['sha256']:raise ValueError('owned source patch differs')
    if p.digest(p.regular(HERE/'core-sqlcipher.map'))!=lock['sqlcipher_map_sha256']:raise ValueError('Core backend map differs')
    if p.digest(p.regular(HERE/'producer-history.lock.json'))!=lock['historical_producer_sources_sha256']:raise ValueError('consumed producer history differs')
    return lock

def recipe():
    consumed=['build.py','providers.py','sources.py','audit.py','toolchain.py','CMakeLists.txt','inputs.lock.json',
              'native-sources.lock.json','gltf-inputs.lock.json','gles1-headers.lock.json',
              'producer-history.lock.json','core-sqlcipher.map','patches/atomic-counter-platform.patch',
              'patches/jni-exception-correctness.patch','KernelRuntimeSmoke.java',
              'NativeDatabaseCandidate.java','KernelThrowingLoggerCandidate.java']
    for entry in p.load(HERE/'producer-history.lock.json').values():
        consumed += [v['snapshot'] for v in entry['variants'].values()]
    result={name:p.digest(p.regular(HERE/name)) for name in consumed}
    shared={'native-commoncommo/runner.py','native-cesium/acquire.py','native-cesium/providers.cmake','kernel-scene/kernel.py','gis-java/build.py'}
    shared.update(folder+'/build.py' for folder in p.FAMILIES.values())
    for name in sorted(shared):result['../'+name]=p.digest(p.regular(HERE.parent/name))
    return result

def external(path):
    path=Path(path).absolute()
    if any(part.is_symlink() for part in [path,*path.parents]):raise ValueError('symlink input/output root refused')
    return path.resolve()

def disjoint(output,inputs):
    output=external(output)
    if output.exists():raise ValueError('new absent output required; no private-build adoption')
    for candidate in inputs:
        candidate=external(candidate)
        if output==candidate or output in candidate.parents or candidate in output.parents:raise ValueError('output/input overlap')
    return output

def environment(java_home,cc,cxx,output):
    removed={'CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','COMPILER_PATH','GCC_EXEC_PREFIX','CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CC','CXX','MAKEFLAGS','GNUMAKEFLAGS','MFLAGS','MAKEFILES','BASH_ENV','ENV','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','JDK_JAVAC_OPTIONS','_JAVA_OPTIONS','CLASSPATH','PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','PYTHONUSERBASE'}
    env={k:v for k,v in os.environ.items() if k not in removed and not k.startswith(('LD_','CMAKE_','PKG_CONFIG','BASH_FUNC_','GDAL_','PROJ_'))}
    env.update(JAVA_HOME=str(java_home),CC=cc,CXX=cxx,LC_ALL='C',PKG_CONFIG_PATH='',PKG_CONFIG_LIBDIR=str(output/'absent-pkgconfig'),CMAKE_BUILD_PARALLEL_LEVEL='1',PYTHONNOUSERSITE='1',OPENSSL_CONF='/dev/null',OPENSSL_MODULES=str(output/'absent-openssl-modules'))
    return env

def cmake_paths(paths,output):
    roots={k:Path(v['root'] if isinstance(v,dict) else v).resolve() for k,v in paths.items()}
    dependency=Path(paths['gdal_jni']['dependency_root']).resolve()
    values={'CESIUM_OUTPUT':roots['cesium'],'CESIUM_SOURCE':output/'cesium-source','CESIUM_RECIPE':HERE.parent/'native-cesium','KERNEL_LAYOUT':output/'layout','JNI_HEADERS':roots['kernel_java']/'jni-headers','GDAL_JNI':roots['gdal_jni'],'GDAL_INSTALL':dependency/'gdal-install','MINIZIP':dependency/'minizip','GLES':roots['gles'],'SPATIAL':roots['spatial'],'GEOS':roots['geos'],'PROJ':roots['proj'],'SQLCIPHER':roots['sqlcipher'],'ASSIMP':roots['assimp'],'LAS':roots['las'],'MDB':roots['mdb'],'DRACO':roots['draco'],'KML':roots['kml'],'CURL_ROOT':roots['curl'],'GLTF':output/'gltf-headers/tinygltf','GLTFLOADER':output/'gltf-headers/tinygltfloader','GLES_EXTRA':output/'gles1-declarations'}
    return values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['providers','source','cache','output']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['verify','prepare','configure','build'],default='verify')
    parser.add_argument('--java-home',type=Path)
    for name,default in [('cmake','cmake'),('ninja','ninja'),('cc','gcc'),('cxx','g++'),('nm','nm'),('readelf','readelf'),('patch','patch'),('git','git')]:parser.add_argument('--'+name,default=default)
    args=parser.parse_args();lock=validate_lock(p.load(HERE/'inputs.lock.json'));paths=p.load(args.providers)
    if args.phase in ('configure','build') and not lock['jni_patch_finalized']:raise ValueError('final strict JNI acceptance gate pending; no configure/build launch')
    roots=p.declared_paths(paths)
    output=disjoint(args.output,[HERE.parent.parent,args.source,args.cache,*roots,*([args.java_home] if args.java_home else [])]);initial=recipe()
    results,errors=p.verify_all(paths)
    if errors:
        print(json.dumps({'provider_validation':'blocked','errors':errors},indent=2));raise ValueError('genuine producer verification failed; no fallback')
    output.mkdir(mode=0o700,parents=True)
    record={'interpreter':{'path':str(Path(sys.executable).resolve()),'sha256':p.digest(Path(sys.executable).resolve()),'version':sys.version},'recipe':initial,'lock':lock,'providers':results,'fresh_dependency_build':False,'fresh_native_build':False,'private_prototype_adopted':False,'phase':args.phase,'native_build_performed':False,'runtime_acceptance':False,'sdk_acceptance':False}
    (output/'verified-inputs.json').write_text(json.dumps(record,indent=2)+'\n')
    if args.phase=='verify':print('Pure producer verification passed; no staging/configure/build/runtime.');return
    native=p.module('draco');env=environment(args.java_home or Path('/missing-jdk'),args.cc,args.cxx,output)
    started=time.monotonic();deadline=started+3600;build_command_log=[]
    utility_tools={name:Path(shutil.which(getattr(args,name)) or getattr(args,name)).resolve() for name in ('nm','readelf','patch','git')}
    record['utility_tools']={name:{'path':str(path),'sha256':p.digest(p.regular(path))} for name,path in utility_tools.items()}
    def disk():
        size=runner.disk_bytes(output)
        if size>lock['budgets']['output_bytes']:raise ValueError('native output3GiB bound exceeded')
        return size
    def run(argv,label,timeout):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('native profile total3600s budget exhausted')
        command=list(map(str,argv))
        if command[0] in utility_tools:command[0]=str(utility_tools[command[0]])
        limit=min(timeout,remaining)
        build_command_log.append({'name':label,'argv':command,'timeout_s':limit});(output/'commands.json').write_text(json.dumps(build_command_log,indent=2)+'\n')
        result=runner.execute(command,output,label,timeout=limit,env=env,capture=True,disk_limit=lock['budgets']['output_bytes']);disk();return result
    patch_tool=utility_tools['patch']
    record['source_patch_tool']={'path':str(patch_tool),'sha256':p.digest(p.regular(patch_tool))}
    sources.project(args.source,output,lock,run,utility_tools['git']);sources.gltf_headers(external(args.cache),output)
    cesium_source=p.root_of(paths,'cesium')/'source/cesium';cesium_files=p.inventory(cesium_source)
    shutil.copytree(cesium_source,output/'cesium-source');p.check_files(output/'cesium-source',cesium_files)
    record['staged_sources']=p.inventory(output/'layout');record['gltf_headers']=p.inventory(output/'gltf-headers');record['gles1_declarations']=p.inventory(output/'gles1-declarations');record['source_patches_finalized']=lock['jni_patch_finalized']
    (output/'prepared.json').write_text(json.dumps(record,indent=2)+'\n')
    if args.phase=='prepare':print('Locked source projection prepared; no native build/runtime.');return
    if not lock['jni_patch_finalized']:raise ValueError('final JNI source/runtime gate pending; configure/build not accepted')
    if (platform.system(),platform.machine())!=('Linux','x86_64') or not args.java_home:raise ValueError('Linux amd64 and explicit JDK17 required')
    tools={name:Path(shutil.which(getattr(args,name)) or getattr(args,name)).resolve() for name in ['cmake','ninja','cc','cxx']}
    identities={name:{'path':str(path),'sha256':p.digest(p.regular(path)),'version':run([path,'--version'],'tool-'+name,20).decode().strip()} for name,path in tools.items()}
    if not identities['cmake']['version'].startswith('cmake version '+lock['tools']['cmake']) or not identities['ninja']['version'].startswith(lock['tools']['ninja']) or any(not identities[n]['version'].splitlines()[0].endswith(' '+lock['tools']['gcc']) for n in ['cc','cxx']):raise ValueError('reviewed native toolchain required')
    for name in ('java','javac'):
        path=args.java_home.resolve()/'bin'/name
        version=run([path,'--version'],'tool-'+name,20).decode().strip()
        if not (version.startswith('openjdk 17.') if name=='java' else version.startswith('javac 17.')):raise ValueError('actual JDK17 required')
        identities[name]={'path':str(path),'sha256':p.digest(p.regular(path)),'version':version}
    actual_toolchain=toolchain.capture(tools,output,run,env)
    actual_toolchain['jdk_runtime']=toolchain.jdk_runtime(args.java_home,run)
    actual_toolchain['bound_files'].update(actual_toolchain['jdk_runtime']['bound_files'])
    actual_toolchain['bound_files'].update(actual_toolchain['jdk_runtime']['metadata_tools'])
    (output/'actual-toolchain.json').write_text(json.dumps(actual_toolchain,indent=2)+'\n')
    build=output/'build';values=cmake_paths(paths,output)
    command=[tools['cmake'],'-S',HERE,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_MAKE_PROGRAM='+str(tools['ninja']),'-DCMAKE_C_COMPILER='+str(tools['cc']),'-DCMAKE_CXX_COMPILER='+str(tools['cxx']),'-DCMAKE_AR='+actual_toolchain['compiler_and_binutils']['ar'],'-DCMAKE_RANLIB='+actual_toolchain['compiler_and_binutils']['ranlib'],'-DCMAKE_LINKER='+actual_toolchain['compiler_and_binutils']['ld'],*['-D'+name+'='+str(value) for name,value in values.items()]]
    run(command,'configure',lock['budgets']['configure_seconds']);compilation_db=p.load(build/'compile_commands.json')
    prefixes={'core':str(output/'layout/takkernel/engine/src/main/cpp')+'/','jni':str(output/'layout/takkernel/engine/src/main/jni')+'/','cesium':str(output/'cesium-source')+'/'}
    counts={name:len({v['file'] for v in compilation_db if v['file'].startswith(prefix)}) for name,prefix in prefixes.items()}
    if counts!=lock['source_counts']:raise ValueError('complete original815TU graph required')
    if args.phase=='configure':print('Real complete native graph configured; no build/runtime acceptance.');return
    for target,key in [('takengine','core_seconds'),('takenginejni','jni_seconds')]:
        run([tools['ninja'],'-C',build,'-j1',target],'build-'+target,lock['budgets'][key])
        if sum(v['bytes'] for v in p.inventory(output).values())>lock['budgets']['output_bytes']:raise ValueError('native output3GiB bound exceeded')
    rooted={k:Path(v['root'] if isinstance(v,dict) else v).resolve() for k,v in paths.items()}
    elf=audit.elf_audit(output,rooted,run)
    runtime=audit.runtime(output,rooted,args.java_home.resolve(),run,env,jdk_runtime=actual_toolchain['jdk_runtime'])
    again,errors=p.verify_all(paths)
    if errors or again!=results:raise ValueError('read-only producer inputs changed during native build')
    expected_sources=dict(record['staged_sources'])
    p.check_files(output/'layout',expected_sources);p.check_files(output/'cesium-source',cesium_files)
    p.check_files(output/'gltf-headers',record['gltf_headers']);p.check_files(output/'gles1-declarations',record['gles1_declarations'])
    toolchain.verify(actual_toolchain)
    for tool in identities.values():
        if p.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('actual tool changed during qualification')
    if recipe()!=initial:raise ValueError('profile recipe changed during build/runtime')
    record.update(phase='complete',native_build_performed=True,fresh_native_build=True,
                  native_translation_units=counts,tools=identities,actual_toolchain=actual_toolchain,elf_audit=elf,runtime=runtime,
                  specified_runtime_controls_passed=True,component_runtime_acceptance=True,
                  elapsed_seconds=time.monotonic()-started,output_bytes=disk(),total_budget_seconds=3600)
    (output/'complete.json').write_text(json.dumps(record,indent=2)+'\n')
    print('Fresh815TU native component build and specified strict JNI controls passed; no full SDK/client claim.')
if __name__=='__main__':main()
