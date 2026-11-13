#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline assembly and real EngineLibrary resource-loader qualification."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import sys
import time
import zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import resource_inputs
import source_families
import composition
NATIVE=HERE.parent/'kernel-native'
sys.path.insert(0,str(NATIVE))
spec=importlib.util.spec_from_file_location('sdk_package_native',NATIVE/'build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
p=b.p;runner=b.runner;audit=b.audit

def safe(name):
    path=PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name:raise ValueError('unsafe archive member')
    return str(path)

def jar_write(path,entries):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as jar:
        for name,data in sorted(entries.items()):
            info=zipfile.ZipInfo(safe(name),(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;jar.writestr(info,data)
    with zipfile.ZipFile(path) as jar:
        if len(jar.namelist())!=len(set(jar.namelist())):raise ValueError('duplicate archive member')
        if set(jar.namelist())!=set(entries):raise ValueError('archive allowlist differs')
        for name,data in entries.items():
            if jar.read(name)!=data:raise ValueError('archive member bytes differ')

def contained_java_argv(argv, java, out):
    argv=list(map(str,argv))
    if Path(argv[0]).resolve()==(java/'bin/java').resolve():
        argv[1:1]=['-XX:ErrorFile='+str(out/'hs_err_java_pid%p.log')]
    elif Path(argv[0]).resolve()==(java/'bin/javac').resolve():
        argv[1:1]=['-J-Xmx256m','-J-XX:ErrorFile='+str(out/'hs_err_javac_pid%p.log')]
    return argv

def apply_source_patch(run, stage, patch, label):
    patch=Path(patch)
    if patch.suffix!='.patch' or not patch.is_file():raise ValueError('one regular source patch required')
    return run(['patch','--batch','--fuzz=0','--no-backup-if-mismatch','-p1','-d',stage,'-i',patch],label,30)

def compile_java(run, java, classpath, destination, sources, label):
    sources=list(sources)
    if not sources or any(not isinstance(path,Path) or path.suffix!='.java' or not path.is_file() for path in sources):
        raise ValueError('only regular Java source inputs allowed')
    return run([java/'bin/javac','--release','17','-proc:none','-implicit:none','-sourcepath','','-cp',
                os.pathsep.join(map(str,classpath)),'-d',destination,*sources],label)

def runtime_control_sources(selected_composition):
    return [NATIVE/n for n in ('KernelRuntimeSmoke.java','NativeDatabaseCandidate.java','KernelThrowingLoggerCandidate.java')]+[
        HERE/n for n in ('StockLoaderSmoke.java','RuntimeResourcesSmoke.java','DefaultIoReadonlySmoke.java')]+(
        [HERE/'GdalReducedProfileSmoke.java'] if selected_composition else [])

def recipe():
    files=['build.py','resource_inputs.py','runtime-resources.lock.json','StockLoaderSmoke.java','RuntimeResourcesSmoke.java','inputs.lock.json','notices.lock.json','patches/engine-library-public-linux.patch','patches/default-io-readonly.patch','DefaultIoReadonlySmoke.java','source_families.py','patches/gles-null-shader-lengths.patch','composition.py','patches/obj-buffer-capacity.patch','patches/gdal-reduced-profile-skip.patch','GdalReducedProfileSmoke.java','patches/obj-two-fixture-regression.patch']
    return {'owned':{n:p.digest(HERE/n) for n in files},'resources_adapter':p.digest(HERE.parent/'compat/src/main/java/android/content/res/Resources.java'),'kernel_native':b.recipe(),'native_finalization_validation':composition.source_closure()}

def verify_native(root,providers):
    raw=p.load(root/'complete.json');current=b.recipe()
    if raw.get('native_translation_units')!={'core':483,'jni':159,'cesium':173} or not raw.get('fresh_native_build') or not raw.get('specified_runtime_controls_passed'):raise ValueError('actual fresh native component producer required')
    prefixes={'CMakeLists.txt':'# Copyright 2026 uds-takserver authors\n# SPDX-License-Identifier: GPL-3.0-only\n',**{n:'// Copyright 2026 uds-takserver authors\n// SPDX-License-Identifier: GPL-3.0-only\n' for n in ['KernelRuntimeSmoke.java','NativeDatabaseCandidate.java','KernelThrowingLoggerCandidate.java']}}
    if current.keys()!=raw['recipe'].keys():raise ValueError('native consumed recipe shape differs')
    for name,digest in raw['recipe'].items():
        data=(NATIVE/name).read_bytes()
        if p.digest(NATIVE/name)!=digest:
            prefix=prefixes.get(name,'').encode()
            if not prefix or not data.startswith(prefix) or hashlib.sha256(data[len(prefix):]).hexdigest()!=digest:raise ValueError('native producer differs beyond exact reviewed license comments')
    results,errors=p.verify_all(providers)
    if errors or raw['providers']!=results:raise ValueError('actual native providers differ')
    p.check_files(root/'layout',raw['staged_sources']);p.check_files(root/'gltf-headers',raw['gltf_headers']);p.check_files(root/'gles1-declarations',raw['gles1_declarations'])
    p.check_files(root/'cesium-source',p.inventory(p.root_of(providers,'cesium')/'source/cesium'))
    b.toolchain.verify(raw['actual_toolchain'])
    for value in raw['elf_audit']['elfs'].values():
        if p.digest(p.regular(root/value['relative_path']))!=value['sha256']:raise ValueError('native ELF differs from fresh producer')
    return raw,results

def native_files(root,roots):
    return {'GLdispatch':roots['gles']/'install/lib/libGLdispatch.so.0.0.0','GLESv2':roots['gles']/'install/lib/libGLESv2.so.2.1.0','las':roots['las']/'install/lib/liblas.so.2.4.0','las_c':roots['las']/'install/lib/liblas_c.so.2.4.0','gdal':roots['gdal_jni']/'lib/libgdal.so','gdalalljni':roots['gdal_jni']/'lib/libgdalalljni.so','assimp':roots['assimp']/'install/lib/libassimp.so.4.1.0','takengine':root/'build/kernel-cpp/libtakengine.so','takenginejni':root/'build/kernel-jni/libtakenginejni.so'}

def mapped_provider(name,sha,packaged,allowed,original_project):
    resolved=str(Path(name).resolve())
    if resolved in original_project or (resolved not in packaged and allowed.get(resolved)!=sha) or (resolved in packaged and packaged[resolved]!=sha) or p.digest(Path(resolved))!=sha:raise ValueError('unmanifested/original project provider mapped: '+resolved)
    if Path(resolved).name.startswith(('libcrypto.so','libssl.so','libsqlite3.so')):raise ValueError('shared backend mapped')
    if Path(resolved).name.startswith(('libGLdispatch.so','libGLESv2.so')) and resolved not in packaged:raise ValueError('host graphics substitution')
    return resolved

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ['native-proof','providers','source','output']:parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--composition',type=Path,help='Explicit reduced GDAL composition declaration; baseline providers remain unchanged')
    parser.add_argument('--composition-sha256')
    parser.add_argument('--java-home',type=Path,required=True)
    parser.add_argument('--resource-payloads',type=Path,help='Declared offline store: one regular file named by each reviewed LFS SHA-256')
    parser.add_argument('--phase',choices=['verify','package','qualify'],default='verify')
    for n,default in [('git','git'),('patch','patch'),('nm','nm'),('readelf','readelf')]:parser.add_argument('--'+n,default=default)
    args=parser.parse_args();lock=p.load(HERE/'inputs.lock.json');providers=p.load(args.providers);roots={k:p.root_of(providers,k) for k in providers}
    if bool(args.composition)!=bool(args.composition_sha256):raise ValueError('composition path and SHA required together')
    selected_composition=composition.inspect(args.composition,args.composition_sha256) if args.composition else None
    inputs=[HERE.parent.parent,args.native_proof,args.source,args.providers,args.java_home,*p.declared_paths(providers),*([args.resource_payloads] if args.resource_payloads else [])]
    if selected_composition:inputs.extend(selected_composition[3])
    out=b.disjoint(args.output,inputs);before=recipe();raw,verified=verify_native(args.native_proof,providers)
    java=args.java_home.resolve()
    for name in ['java','javac']:
        if p.digest(p.regular(java/'bin'/name))!=raw['tools'][name]['sha256']:raise ValueError('same actual qualified JDK required')
    out.mkdir(parents=True,mode=0o700);started=time.monotonic();commands=[];tools={name:Path(shutil.which(getattr(args,name)) or getattr(args,name)).resolve() for name in ['git','patch','nm','readelf']}
    for name,path in tools.items():
        if p.digest(p.regular(path))!=raw['utility_tools'][name]['sha256']:raise ValueError('same actual qualified metadata tools required')
    env=b.environment(java,raw['tools']['cc']['path'],raw['tools']['cxx']['path'],out)
    if selected_composition:env={k:v for k,v in env.items() if not k.startswith(('GDAL_','CPL_','PROJ_','LD_','JAVA_','JDK_','_JAVA')) or k=='JAVA_HOME'}
    def run(argv,name,timeout=120):
        remaining=lock['total_seconds']-(time.monotonic()-started)
        if remaining<=0:raise ValueError('package total command deadline exhausted')
        argv=contained_java_argv(argv,java,out);argv[0]=str(tools.get(argv[0],argv[0]));commands.append({'name':name,'argv':argv,'timeout':min(timeout,remaining)});(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        return runner.execute(argv,out,name,timeout=min(timeout,remaining),env=env,capture=True,disk_limit=lock['output_limit_bytes'])
    elf=audit.elf_audit(args.native_proof,roots,run)
    if elf!=raw['elf_audit']:raise ValueError('actual native ABI/privacy audit differs')
    record={'recipe':before,'interpreter':{'path':str(Path(sys.executable).resolve()),'sha256':p.digest(Path(sys.executable).resolve()),'version':sys.version},'tools':{name:{'path':str(path),'sha256':p.digest(path)} for name,path in tools.items()},'jdk_tools':{name:raw['tools'][name] for name in ['java','javac']},'actual_toolchain':raw['actual_toolchain'],'original_native_producer':{'sha256':p.digest(args.native_proof/'complete.json'),'recipe':raw['recipe']},'fresh_native_build':False,'component_runtime_acceptance':False,'sdk_acceptance':False,'renderer_acceptance':False,'client_acceptance':False,'phase':args.phase}
    if selected_composition:record['native_composition']=selected_composition[1]
    if args.phase=='verify':(out/'verified.json').write_text(json.dumps(record,indent=2)+'\n');return
    package=out/'package';package.mkdir();licenses=package/'notices';licenses.mkdir();notice_lock=p.load(HERE/'notices.lock.json')
    notice_roots={**roots,'cesium_ancestor':Path(providers['cesium']['dependency_root']),'gdal_dependency':Path(providers['gdal_jni']['dependency_root'])}
    for item in notice_lock['files']:
        source=p.regular(notice_roots[item['provider']]/item['path'])
        if p.digest(source)!=item['sha256'] or source.stat().st_size!=item['bytes']:raise ValueError('locked notice differs')
        dest=licenses/item['provider']/safe(item['path']);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    for index,item in enumerate(notice_lock['official_git']):
        data=run(['git','--no-lazy-fetch','-C',args.source,'show',lock['official_revision']+':'+item['path']],'official-notice-'+str(index),20)
        if hashlib.sha256(data).hexdigest()!=item['sha256'] or len(data)!=item['bytes']:raise ValueError('official notice differs')
        (licenses/('Kernel-'+item['path'])).write_bytes(data)
    source=roots['kernel_java']/'stage'/lock['source_file'];stage=out/'patched-source';stage.mkdir();shutil.copyfile(p.regular(source),stage/'EngineLibrary.java')
    if p.digest(stage/'EngineLibrary.java')!=lock['engine_before'] or p.digest(HERE/'patches/engine-library-public-linux.patch')!=lock['patch_sha256']:raise ValueError('EngineLibrary patch preimage differs')
    apply_source_patch(run,stage,HERE/'patches/engine-library-public-linux.patch','patch-stock-loader')
    if p.digest(stage/'EngineLibrary.java')!=lock['engine_after']:raise ValueError('EngineLibrary patch postimage differs')
    readonly=lock['default_io_readonly'];provider_source=stage/'DefaultIOProvider.java'
    shutil.copyfile(p.regular(roots['kernel_java']/'stage'/readonly['source_file']),provider_source)
    if p.digest(provider_source)!=readonly['before'] or p.digest(HERE/'patches/default-io-readonly.patch')!=readonly['patch_sha256']:raise ValueError('DefaultIOProvider patch preimage differs')
    apply_source_patch(run,stage,HERE/'patches/default-io-readonly.patch','patch-default-io-readonly')
    if p.digest(provider_source)!=readonly['after']:raise ValueError('DefaultIOProvider patch postimage differs')
    shader=lock['gles_null_shader_lengths'];shader_source=stage/'GLES20.java'
    shutil.copyfile(p.regular(roots['kernel_java']/'stage'/shader['source_file']),shader_source)
    if p.digest(shader_source)!=shader['before'] or p.digest(HERE/'patches/gles-null-shader-lengths.patch')!=shader['patch_sha256']:raise ValueError('GLES20 shader-source patch preimage differs')
    apply_source_patch(run,stage,HERE/'patches/gles-null-shader-lengths.patch','patch-gles-null-shader-lengths')
    if p.digest(shader_source)!=shader['after']:raise ValueError('GLES20 shader-source patch postimage differs')
    extra_sources=[];extra_families=['com/atakmap/map/layer/model/obj/ObjModelSpi']
    def patch_family(item,filename,patchname):
        target=stage/filename;shutil.copyfile(p.regular(roots['kernel_java']/'stage'/item['source_file']),target)
        if p.digest(target)!=item['before'] or p.digest(HERE/'patches'/patchname)!=item['patch_sha256']:raise ValueError('profile source/patch preimage differs')
        apply_source_patch(run,stage,HERE/'patches'/patchname,'patch-'+filename)
        if p.digest(target)!=item['after']:raise ValueError('profile source postimage differs')
        extra_sources.append(target)
    patch_family(lock['obj_buffer_capacity'],'ObjModelSpi.java','obj-buffer-capacity.patch')
    if selected_composition:
        profile=lock['reduced_gdal'];patch_family({'source_file':profile['source_file'],'before':profile['source_before_sha256'],'after':profile['source_after_sha256'],'patch_sha256':profile['patch_sha256']},'GdalLibrary.java','gdal-reduced-profile-skip.patch')
        extra_families.append('com/atakmap/map/gdal/GdalLibrary')
    java_input=p.load(roots['kernel_java']/'inputs.json');cp=[roots['kernel_java']/'classes']+[Path(x['path']) for x in java_input['classpath']]
    replacement=out/'replacement-classes';replacement.mkdir()
    resources_source=HERE.parent/'compat/src/main/java/android/content/res/Resources.java'
    compile_java(run,java,cp,replacement,[stage/'EngineLibrary.java',resources_source,provider_source,shader_source,*extra_sources],'compile-real-stock-loader')
    classes={name:(roots['kernel_java']/'classes'/name).read_bytes() for name in p.inventory(roots['kernel_java']/'classes')}
    replaced=p.inventory(replacement)
    family_preimages=dict(lock['obj_buffer_capacity']['class_preimages'])
    if selected_composition:family_preimages.update(lock['reduced_gdal']['class_preimages'])
    if any(name not in classes or hashlib.sha256(classes[name]).hexdigest()!=sha for name,sha in family_preimages.items()):raise ValueError('profile original class preimage differs')
    classes=source_families.merge(classes,{name:(replacement/name).read_bytes() for name in replaced},extra_families)
    record['replaced_class_families']={name:replaced[name] for name in replaced}
    record['gles_null_shader_lengths']={'source_before':shader['before'],'source_after':shader['after'],'scope':shader['scope'],'headed_runtime_qualified':False}
    libraries=native_files(args.native_proof,roots)
    if selected_composition:
        libraries.update({'gdal':selected_composition[0]['libgdal.so'],'gdalalljni':selected_composition[0]['libgdalalljni.so']})
    if list(libraries)!=lock['native_order']:raise ValueError('reviewed resource load order differs')
    resource_lock=p.load(HERE/'runtime-resources.lock.json')
    if resource_lock['official_revision']!=lock['official_revision']:raise ValueError('resource revision differs')
    mapping=resource_lock['mapping_recipe']
    mapping_bytes=run(['git','--no-lazy-fetch','-C',args.source,'show',lock['official_revision']+':'+mapping['path']],'resource-gradle-mapping',20)
    if len(mapping_bytes)!=mapping['bytes'] or hashlib.sha256(mapping_bytes).hexdigest()!=mapping['sha256']:raise ValueError('official Gradle mapping differs')
    resource_tree={}
    tree=run(['git','--no-lazy-fetch','-C',args.source,'ls-tree','-r','--long',lock['official_revision'],'--',*[root.rstrip('/') for root in resource_inputs.ROOTS]],'resource-tree',20)
    for row in tree.decode().splitlines():
        metadata,name=row.split('\t');mode,kind,blob,size=metadata.split()
        if kind!='blob':raise ValueError('non-blob runtime resource')
        resource_tree[name]=(mode,blob,int(size))
    payload_root=b.external(args.resource_payloads) if args.resource_payloads else None
    payload_sizes={item['lfs_payload']['sha256']:item['lfs_payload']['bytes'] for item in resource_lock['files'] if item.get('lfs_payload')}
    def payload(sha):
        if payload_root is None:raise ValueError('declared resource payload store required')
        source=p.regular(payload_root/sha)
        if source.stat().st_size!=payload_sizes[sha]:raise ValueError('resource payload size differs')
        return source.read_bytes()
    resources=resource_inputs.collect(resource_lock,resource_tree,lambda name:run(['git','--no-lazy-fetch','-C',args.source,'show',lock['official_revision']+':'+name],'resource-'+str(len(commands)),20),payload)
    record['resource_payloads']={sha:{'path':str(payload_root/sha),'sha256':sha,'bytes':size} for sha,size in payload_sizes.items()}
    expected_resources=out/'runtime-resources.sha256'
    expected_resources.write_text(''.join(item.get('lfs_payload',item)['sha256']+' '+item['kind']+' '+item['destination']+'\n' for item in resource_lock['files']))
    natives={'lib'+n+'.so':p.regular(path).read_bytes() for n,path in libraries.items()}
    entries=resource_inputs.merge(classes,{'libs/linux64/'+n:data for n,data in natives.items()},resources)
    entries['META-INF/MANIFEST.MF']=('Manifest-Version: 1.0\nImplementation-Title: Public-source Kernel CPU JNI component\nImplementation-Version: '+lock['version']+'\n\n').encode()
    native_manifest={n:hashlib.sha256(data).hexdigest() for n,data in natives.items()}
    (out/'native-resources.sha256').write_text(''.join(sha+' '+name+'\n' for name,sha in native_manifest.items()))
    artifact=package/('kernel-'+lock['version']+'-linux-amd64-public-cpu.jar');jar_write(artifact,entries)
    dependencies=package/'third-party';dependencies.mkdir();jar_records=[]
    for index,item in enumerate(java_input['classpath']):
        path=p.regular(Path(item['path']));dest=dependencies/path.name
        if dest.exists() or p.digest(path)!=item['sha256']:raise ValueError('duplicate/changed dependency JAR')
        with zipfile.ZipFile(path) as jar:
            names=jar.namelist()
            if len(names)!=len(set(names)) or any(n.lower().endswith(('.so','.dll','.dylib','.jnilib')) for n in names):raise ValueError('dependency JAR contains duplicate entries or prebuilt native libraries')
            for n in names:safe(n)
        shutil.copyfile(path,dest);jar_records.append({'path':str(dest.relative_to(package)),'sha256':item['sha256'],'role':item['role']})
    headers=package/'headers'
    for name,item in raw['staged_sources'].items():
        if name.startswith('takkernel/engine/src/main/cpp/') and Path(name).suffix in ('.h','.hpp','.inl'):
            dest=headers/'native'/name.removeprefix('takkernel/engine/src/main/cpp/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.native_proof/'layout'/name,dest)
    for name in p.inventory(roots['kernel_java']/'jni-headers'):
        dest=headers/'jni'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(roots['kernel_java']/'jni-headers'/name,dest)
    manifest={'version':lock['version'],'official_revision':lock['official_revision'],'abi':lock['abi'],'runtime_resources':{'namespace':resource_lock['namespace'],'source_inventory':resource_lock['files'],'entries':{name:hashlib.sha256(data).hexdigest() for name,data in resources.items()},'unindexed_values_xml':True,'android_values_semantics':False},'default_io_readonly_patch':readonly,'resource_adapter_source_sha256':p.digest(resources_source),'class_count':len(classes),'class_inventory':{name:hashlib.sha256(data).hexdigest() for name,data in classes.items()},'patched_class_family':replaced,'native_resource_order':lock['native_order'],'native_resources':native_manifest,'dependencies':jar_records,'headers':p.inventory(headers),'notices':p.inventory(licenses),'excluded_features':['proprietary codecs','renderer qualification','client qualification','CommonCommo','stock unmodified Linux preload list','cross-host ABI portability'],'native_elf_audit':elf,'original_native_producer_sha256':record['original_native_producer']['sha256'],'stock_loader_java_library_path':'${java.io.tmpdir}/takkernel/engine/'+hashlib.md5(artifact.read_bytes()).hexdigest()+'/lib/linux64','source_patch':{'before':lock['engine_before'],'after':lock['engine_after'],'patch_sha256':lock['patch_sha256']}}
    manifest['obj_buffer_capacity_patch']=lock['obj_buffer_capacity']
    if selected_composition:
        manifest['native_composition']=selected_composition[1]
        manifest['reduced_gdal_source_patch']=lock['reduced_gdal']
    (package/'version-abi-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    record.update(package_inventory=p.inventory(package),manifest=manifest)
    bundle=out/('kernel-'+lock['version']+'-linux-amd64-public-cpu.zip')
    jar_write(bundle,{name:(package/name).read_bytes() for name in record['package_inventory']})
    record['bundle']={'name':bundle.name,'sha256':p.digest(bundle),'bytes':bundle.stat().st_size}
    if runner.disk_bytes(out)>lock['output_limit_bytes']:raise ValueError('package output bound exceeded')
    if args.phase=='qualify':
        runtime_classes=out/'runtime-classes';runtime_classes.mkdir();class_path=[artifact,*[package/v['path'] for v in jar_records]]
        controls=runtime_control_sources(selected_composition)
        compile_java(run,java,class_path,runtime_classes,controls,'compile-stock-loader-controls')
        # Only exact validated JDK/host inputs may accompany the nine packaged providers.
        # Do not permit any original installed provider merely because its proof is valid.
        allowed=dict(raw['actual_toolchain']['jdk_runtime']['bound_files'])
        gles_record=p.load(roots['gles']/'complete.json')
        for group in ('host_inputs','runtime_providers'):
            for name,item in gles_record[group].items():
                path=Path(name).resolve()
                if any(path.is_relative_to(root) for root in roots.values()):continue
                audit.add_elf(allowed,path,item)
        if selected_composition:
            for name,sha in selected_composition[2].items():
                if name not in map(str,selected_composition[0].values()):allowed[name]=sha
        original_project={str(x.resolve()) for x in libraries.values()}
        allowed={name:sha for name,sha in allowed.items() if name not in original_project}
        p.bound_files(allowed)
        relocated=out/'relocated-package';shutil.copytree(package,relocated)
        if p.inventory(relocated)!=record['package_inventory']:raise ValueError('relocated package differs')
        phases={}
        for phase in ['basic','database','logger','relocated']:
            app=out/'runtime'/phase;app.mkdir(parents=True);(app/'home').mkdir();(app/'data').mkdir()
            selected=relocated if phase=='relocated' else package
            selected_jar=selected/artifact.name
            selected_class_path=[selected_jar,*[selected/v['path'] for v in jar_records]]
            mode='database' if phase=='relocated' else phase
            stock_tmp=out/('stock-tmp-relocated' if phase=='relocated' else 'stock-tmp-package');stock_tmp.mkdir(exist_ok=True)
            library_path=stock_tmp/'takkernel/engine'/hashlib.md5(selected_jar.read_bytes()).hexdigest()/'lib/linux64'
            text=run([java/'bin/java','-Djava.library.path='+str(library_path),'-Xcheck:jni','-Xmx256m','-XX:ActiveProcessorCount=2','-Djava.awt.headless=true','-Duser.home='+str(app/'home'),'-Djava.io.tmpdir='+str(stock_tmp),'-DTAK_APP_DATA_PATH='+str(app/'data'),'-cp',os.pathsep.join(map(str,[runtime_classes,*selected_class_path])),('GdalReducedProfileSmoke' if selected_composition else 'StockLoaderSmoke'),selected_jar,mode,out/'native-resources.sha256',expected_resources],'stock-'+phase).decode()
            required=['PASS_GENUINE_118_RESOURCES_91_ASSETS_25_CATALOG_15_STOCK_GLSL','PASS_STOCK_ENGINE_RESOURCE_LOADER_SCOPED_COMPONENT','PASS_ENGINE_INITIALIZER_AND_NATIVE_CONFIG_GDAL','PASS_KERNEL_JNI_MATRIX_POINT_WKB_NATIVE_PROJECTION']
            if selected_composition:required+=['PASS_REAL_REDUCED_PROFILE_GDAL_SKIP_INIT_REGISTRY_NO_SUPPRESSION']
            if mode=='database':required+=['PASS_REAL_DEFAULT_IO_READONLY_WRITE_REJECTION_NO_CREATE_MBTILES','PASS_PREPARED_NATIVE_DATABASE2_ENCRYPTED_OPEN_REOPEN_WRONG_KEY_CONTROL','PASS_REAL_GDAL_MEM_EXACT_WRITE_READ']
            if phase=='logger':required+=['PASS_REAL_THROWING_LOGGER_BASELINE_REJECTION_MATCH_AND_CORRECT_KEY_RECOVERY']
            if any(n not in text for n in required) or audit.strict_jni_diagnostics(text) or any(n in text for n in ['EngineLibrary: Failed to load','UnsatisfiedLinkError','NoClassDefFoundError']):raise ValueError('real strict stock loader control failed: '+phase)
            extraction=re.findall(r'^EXTRACTION_DIRECTORY (.+)$',text,re.M)
            if len(extraction)!=1 or not Path(extraction[0]).resolve().is_relative_to(stock_tmp.resolve()):raise ValueError('stock extraction must use new owned runtime directory')
            extraction=Path(extraction[0])
            if extraction!=library_path:raise ValueError('actual EngineLibrary extraction differs from documented startup configuration')
            packaged={str(extraction/name):sha for name,sha in native_manifest.items()}
            observed=dict((name,sha) for sha,name in re.findall(r'^PACKAGED_NATIVE ([0-9a-f]{64}) (.+)$',text,re.M))
            if observed!=packaged:raise ValueError('package native extraction inventory differs')
            maps={}
            for sha,name in re.findall(r'^ELF ([0-9a-f]{64}) (.+)$',text,re.M):
                resolved=mapped_provider(name,sha,packaged,allowed,original_project)
                maps[resolved]=sha
            if any(maps.get(name)!=sha for name,sha in packaged.items()):raise ValueError('packaged project provider absent from maps')
            if phase=='logger':
                m=re.search(r'LOGGER_CALLBACKS=(\d+) BASELINE_WRONG_KEY=(\S+) LISTENER_WRONG_KEY=(\S+)',text)
                if not m or int(m[1])<1 or m[2]!=m[3]:raise ValueError('real throwing callback control differs')
            phases[phase]={'mapped_elfs':maps,'strict_jni_warnings':0,'extracted_native_providers':packaged,'required_controls':required,'jar_path':str(selected_jar),'startup_java_library_path':str(library_path)}
        omitted=out/'negative-only-missing-shader-no-native.jar';shader=next(item['destination'] for item in resource_lock['files'] if Path(item['destination']).name.startswith('gl20fp_'))
        negative_entries={k:v for k,v in entries.items() if k!=shader and not k.startswith('libs/linux64/')}
        negative_entries['META-INF/MANIFEST.MF']=b'Manifest-Version: 1.0\nImplementation-Title: Negative-only omitted-shader catalog fixture; no native payloads\n\n'
        jar_write(omitted,negative_entries)
        negative_resource=out/'negative-resource';negative_resource.mkdir()
        for name in ['home','data','tmp']:(negative_resource/name).mkdir()
        text=run([java/'bin/java','-Xmx64m','-Djava.awt.headless=true','-Duser.home='+str(negative_resource/'home'),'-Djava.io.tmpdir='+str(negative_resource/'tmp'),'-DTAK_APP_DATA_PATH='+str(negative_resource/'data'),'-cp',os.pathsep.join(map(str,[runtime_classes,omitted,*class_path[1:]])),'RuntimeResourcesSmoke',omitted],'stock-missing-shader').decode()
        if 'PASS_GENUINE_MISSING_SHADER_CATALOG_REJECTION' not in text:raise ValueError('genuine missing shader catalog negative failed')
        negative=out/'missing-resource.jar';jar_write(negative,{k:v for k,v in entries.items() if k!='libs/linux64/libGLdispatch.so'})
        app=out/'negative';app.mkdir();(app/'home').mkdir();(app/'data').mkdir()
        text=run([java/'bin/java','-Xcheck:jni','-Xmx256m','-Djava.awt.headless=true','-Djava.io.tmpdir='+str(app),'-Duser.home='+str(app/'home'),'-DTAK_APP_DATA_PATH='+str(app/'data'),'-cp',os.pathsep.join(map(str,[runtime_classes,negative,*class_path[1:]])),'StockLoaderSmoke',negative,'missing',out/'native-resources.sha256'],'stock-missing-resource').decode()
        if 'PASS_REAL_STOCK_LOADER_MISSING_REQUIRED_RESOURCE' not in text:raise ValueError('real missing resource control failed')
        if selected_composition:
            record['composition_driver_absence_runtime_qualified']=True
        record.update(component_runtime_acceptance=True,stock_resource_loader_controls_passed=True,runtime=phases,missing_resource_negative_control=True,missing_shader_catalog_negative_control=True,runtime_resource_consumers_passed=True,negative_resource_fixture={'path':str(omitted.relative_to(out)),'native_payloads':False,'sdk_artifact':False,'omitted_genuine_shader':shader},owned_runtime_classes=p.inventory(runtime_classes))
    if selected_composition and composition.inspect(args.composition,args.composition_sha256)[1]['products']!=selected_composition[1]['products']:raise ValueError('composition products changed')
    again,errors=p.verify_all(providers)
    if errors or again!=verified:raise ValueError('provider inputs changed')
    b.toolchain.verify(raw['actual_toolchain'])
    for name,tool in record['tools'].items():
        if p.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('metadata tool changed')
    if p.digest(Path(record['interpreter']['path']))!=record['interpreter']['sha256']:raise ValueError('interpreter changed')
    for item in resource_lock['files']:
        if item.get('lfs_payload'):
            declared=item['lfs_payload'];actual=payload(declared['sha256'])
            if len(actual)!=declared['bytes'] or hashlib.sha256(actual).hexdigest()!=declared['sha256']:raise ValueError('resource payload changed')
    if recipe()!=before or p.load(args.native_proof/'complete.json')!=raw or p.inventory(package)!=record['package_inventory']:raise ValueError('recipe/original proof/package changed')
    for n,path in libraries.items():
        if p.digest(path)!=native_manifest['lib'+n+'.so']:raise ValueError('original native input changed')
    if runner.disk_bytes(out)>lock['output_limit_bytes']:raise ValueError('package output bound exceeded')
    record.update(elapsed_seconds=time.monotonic()-started,output_bytes=runner.disk_bytes(out))
    (out/'complete.json').write_text(json.dumps(record,indent=2)+'\n');print('Genuine package assembly completed; runtime acceptance:',record['component_runtime_acceptance'],'; SDK/client/renderer acceptance: false')
if __name__=='__main__':main()
