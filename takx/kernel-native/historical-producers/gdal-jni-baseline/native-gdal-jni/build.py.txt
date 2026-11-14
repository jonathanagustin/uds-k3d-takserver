#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Link the verified reduced GDAL PIC closure once and its real GIS Java SWIG JNI."""
import argparse, importlib.util, json, os, shlex, shutil, time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
kernel=module('gdal_jni_kernel',HERE.parent/'kernel-scene/kernel.py')
java=module('gdal_jni_java',HERE.parent/'kernel-java/build.py')
b=kernel.build
RECIPE_PATHS=('native-gdal-jni/build.py','native-gdal-jni/GdalJniProbe.java',
    'kernel-scene/kernel.py','kernel-scene/build.py','kernel-scene/producer.py',
    'kernel-scene/normalize_la.py','kernel-scene/inputs.lock.json',
    'native-deps/build.py','native-las/build.py','native-assimp/build.py','native-proj/build.py',
    'native-deps/inputs.lock.json','native-las/inputs.lock.json','native-assimp/inputs.lock.json','native-proj/inputs.lock.json',
    'kernel-java/build.py','kernel-java/inputs.lock.json','gis-java/build.py','gis-java/sources.lock.json','gis-java/CompileApiProbe.java')

def recipe():
    return {n:b.native.digest(HERE.parent/n) for n in RECIPE_PATHS}

def file_hashes(root):
    result={}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError('symlink inventory input')
        if p.is_file():result[str(p.relative_to(root))]=b.native.digest(p)
    return result

def unchanged(values):
    for name,sha in values.items():
        if Path(name).is_symlink() or b.native.digest(Path(name))!=sha:raise ValueError('bound file changed: '+name)

def audit_dynamic(path,text):
    if 'TEXTREL' in text:raise ValueError('ELF text relocations')
    import re
    needed=re.findall(r'\(NEEDED\).*?\[(.*?)\]',text)
    allowed={'libstdc++.so.6','libm.so.6','libgcc_s.so.1','libc.so.6','ld-linux-x86-64.so.2'}
    if path.name=='libgdalalljni.so':allowed.add('libgdal.so')
    if not needed or not set(needed)<=allowed:raise ValueError('unexpected ELF dependency')
    if path.name=='libgdalalljni.so' and 'libgdal.so' not in needed:raise ValueError('shared provider dependency absent')
    if path.name=='libgdal.so' and any('gdal' in n for n in needed):raise ValueError('foreign GDAL engine dependency')
    return needed

def replay(proof):
    data=json.loads((proof/'complete.json').read_text())
    if data['recipe']!=recipe():raise ValueError('replay recipe differs')
    if file_hashes(proof/'lib')!=data['products']:raise ValueError('replay products differ')
    if file_hashes(proof/'classes')!=data['probe_classes']:raise ValueError('replay probe classes differ')
    unchanged(data['bound_files']);unchanged(data['mapped_providers'])
    for n,sha in data['evidence'].items():
        if b.native.digest(proof/n)!=sha:raise ValueError('replay evidence differs')
    if data.get('native_kernel_or_client_acceptance') is not False:raise ValueError('invalid acceptance')
    return data

def consumed_headers(path, roots):
    """Bind compiler-emitted non-system dependencies to verified input trees."""
    text=path.read_text().replace('\\\n',' ')
    names=shlex.split(text.split(':',1)[1])
    result={}
    for name in names:
        item=Path(name)
        if item.is_symlink() or not item.is_file():raise ValueError('invalid compiler input')
        item=item.resolve()
        if not any(root.resolve() in item.parents for root in roots):raise ValueError('foreign wrapper include')
        result[str(item)]=b.native.digest(item)
    if not result:raise ValueError('empty compiler dependency inventory')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','dependency-root','dependency-proof','dependency-producer','gdal-archive','libkml-archive','proj-proof','assimp-proof','gis-build','java-home'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    for key,value in vars(a).items():setattr(a,key,value.absolute())
    inputs=[v for k,v in vars(a).items() if k!='output']+[HERE]
    out=b.validate_output(a.output,inputs);out.mkdir(mode=0o700)
    initial=recipe()
    (out/'recipe.json').write_text(json.dumps(initial,indent=2)+'\n')
    env=b.assimp.environment('/usr/bin/gcc','/usr/bin/g++')
    for k in list(env):
        if k.startswith(('LD_','PROJ_','GDAL_','PKG_CONFIG','BASH_FUNC_')) or k in ('CPATH','LIBRARY_PATH','LD_LIBRARY_PATH','LD_PRELOAD','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','CLASSPATH'):
            env.pop(k)
    deadline=time.monotonic()+600;commands=[]
    def run(command,name,timeout=60,capture=False):
        left=deadline-time.monotonic()
        if left<=0:raise ValueError('ten minute deadline exhausted')
        commands.append({'name':name,'command':list(map(str,command))});(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        result=b.native.run(list(map(str,command)),out,name,min(left,timeout),env,capture)
        if sum(x.stat().st_size for x in out.rglob('*') if x.is_file())>1024**3:raise ValueError('one GiB output bound exceeded')
        return result
    try:
        lock=json.loads((HERE.parent/'kernel-scene/inputs.lock.json').read_text())
        deps={f:b.verify_dependency(root,f) for f,root in [('proj',a.proj_proof),('assimp',a.assimp_proof)]}
        reference=kernel.reference_sources(a,out,lock,run)
        accepted=kernel.verify_producer(a,reference,deps)
        artifacts,gis=java.verified_gis(a.gis_build,json.loads((HERE.parent/'kernel-java/inputs.lock.json').read_text()))
        state=json.loads((a.gis_build/'build-state.json').read_text())
        gis_inputs=json.loads((a.gis_build/'build-inputs.json').read_text())
        tools={}
        for name in ('java','javac'):
            tool=a.java_home/'bin'/name
            if b.native.digest(tool)!=gis_inputs['tools'][name]['sha256']:raise ValueError('JDK differs from GIS Java toolchain')
            tools[str(tool.resolve())]=b.native.digest(tool)
        for name in ('gcc','g++','ld','as','readelf','nm'):
            tool=Path('/usr/bin')/name;tools[str(tool.resolve())]=b.native.digest(tool)
        bound_files=dict(tools)
        runtime_before=dict(tools)
        for item in (a.java_home/'lib').rglob('*'):
            if item.is_file():
                with item.open('rb') as stream:magic=stream.read(4)
                if magic==b'\x7fELF':runtime_before[str(item.resolve())]=b.native.digest(item)
        for name in ('libc.so.6','libm.so.6','libstdc++.so.6','libgcc_s.so.1','libpthread.so.0','libdl.so.2','librt.so.1','ld-linux-x86-64.so.2'):
            item=Path('/usr/lib/x86_64-linux-gnu')/name
            if item.exists():runtime_before[str(item.resolve())]=b.native.digest(item)
        bound_files.update(runtime_before)
        (out/'tools.json').write_text(json.dumps(tools,indent=2)+'\n')
        wrappers=['gdal_wrap.cpp','gdalconst_wrap.c','gnm_wrap.cpp','ogr_wrap.cpp','osr_wrap.cpp']
        frozen=out/'wrappers';frozen.mkdir();wrapper_hashes={}
        for name in wrappers:
            src=a.gis_build/'generated'/name
            if src.is_symlink() or b.native.digest(src)!=state['outputs']['generated/'+name]:raise ValueError('wrapper output differs')
            shutil.copyfile(src,frozen/name)
            wrapper_hashes[str(frozen/name)]=b.native.digest(frozen/name)
        (out/'accepted-inputs.json').write_text(json.dumps({'native':accepted,'gis_java':gis,'dependency_receipts':deps},indent=2)+'\n')
        lib=out/'lib';lib.mkdir()
        jar=a.gis_build/'gdal-2.4.4-mod-java.jar'
        bound_files[str(jar)]=b.native.digest(jar)
        gdal=a.dependency_root/'gdal-install';proj=a.proj_proof/'install/lib/libproj.a';zlib=a.assimp_proof/'zlib-install/lib/libz.a'
        run(['/usr/bin/g++','-shared','-Wl,--no-undefined','-Wl,-soname,libgdal.so','-o',lib/'libgdal.so','-Wl,--whole-archive',gdal/'lib/libgdal.a','-Wl,--no-whole-archive',proj,zlib,'-pthread','-lm','-lrt','-ldl'],'gdal-shared',180)
        header_root=out/'source-reference/gdal/gdal'
        header_dirs=[header_root/n for n in ('apps','gnm','gcore','alg','ogr','ogr/ogrsf_frmts','port')]
        offered_headers={str(x.relative_to(header_root)):b.native.digest(x) for d in header_dirs for x in d.glob('*.h')}
        (out/'wrapper-header-hashes.json').write_text(json.dumps(offered_headers,sort_keys=True,indent=2)+'\n')
        for folder in (gdal/'include',header_root,a.java_home/'include'):
            for n,sha in file_hashes(folder).items():bound_files[str(folder/n)]=sha
        objects=[]; actual_headers={}
        for name in wrappers:
            obj=out/(name+'.o');objects.append(obj)
            run(['/usr/bin/gcc' if name.endswith('.c') else '/usr/bin/g++','-O2','-fPIC','-MMD','-MF',out/(name+'.d'),'-I'+str(gdal/'include'),*['-I'+str(d) for d in header_dirs],'-I'+str(a.java_home/'include'),'-I'+str(a.java_home/'include/linux'),'-c',frozen/name,'-o',obj],'compile-'+name,180)
            actual_headers[name]=consumed_headers(out/(name+'.d'),[frozen,gdal/'include',header_root,a.java_home/'include'])
        unchanged(wrapper_hashes)
        for depset in actual_headers.values():
            for n,sha in depset.items():
                if n not in wrapper_hashes and bound_files.get(n)!=sha:raise ValueError('compiler input changed')
        bound_files.update(wrapper_hashes)
        (out/'consumed-header-hashes.json').write_text(json.dumps(actual_headers,sort_keys=True,indent=2)+'\n')
        bound_files.update({str(n):b.native.digest(n) for n in objects})
        unchanged(bound_files)
        run(['/usr/bin/g++','-shared','-Wl,--no-undefined','-Wl,-soname,libgdalalljni.so','-o',lib/'libgdalalljni.so',*objects,'-L'+str(lib),'-lgdal','-Wl,-rpath,$ORIGIN'],'jni-shared',90)
        products=file_hashes(lib);dynamic={}
        for name in ('libgdal.so','libgdalalljni.so'):
            run(['/usr/bin/readelf','-d',lib/name],'dynamic-'+name)
            dynamic[name]=audit_dynamic(lib/name,(out/('dynamic-'+name+'.log')).read_text())
        run(['/usr/bin/nm','-D','--defined-only',lib/'libgdalalljni.so'],'jni-defined-symbols')
        if ' GDALVersionInfo' in (out/'jni-defined-symbols.log').read_text():raise ValueError('duplicate GDAL engine in JNI')
        jar=a.gis_build/'gdal-2.4.4-mod-java.jar';classes=out/'classes';classes.mkdir()
        run([a.java_home/'bin/javac','--release','11','-cp',jar,'-d',classes,HERE/'GdalJniProbe.java'],'probe-compile')
        probe_classes=file_hashes(classes)
        runtime_before.update({str((lib/n).resolve()):sha for n,sha in products.items()})
        unchanged(runtime_before)
        for n,sha in probe_classes.items():bound_files[str(classes/n)]=sha
        unchanged(bound_files)
        env['GDAL_DATA']=str(gdal/'share/gdal')
        run([a.java_home/'bin/java','-Xmx128m','-Djava.library.path='+str(lib),'-cp',str(classes)+':'+str(jar),'GdalJniProbe'],'probe',60)
        maps=(out/'probe.log').read_text(); providers={line[4:] for line in maps.splitlines() if line.startswith('ELF ')}
        expected={str((lib/n).resolve()) for n in ('libgdal.so','libgdalalljni.so')}
        gdal_providers={n for n in providers if 'gdal' in Path(n).name}
        if gdal_providers!=expected:raise ValueError('unexpected mapped GDAL provider')
        if not providers or not providers<=set(runtime_before):raise ValueError('unexpected mapped ELF provider')
        mapped={n:runtime_before[n] for n in sorted(providers)}
        if kernel.verify_producer(a,reference,deps)!=accepted:raise ValueError('native producer changed')
        if java.verified_gis(a.gis_build,json.loads((HERE.parent/'kernel-java/inputs.lock.json').read_text()))[1]!=gis:raise ValueError('GIS producer changed')
        for path,sha in tools.items():
            if b.native.digest(Path(path))!=sha:raise ValueError('tool changed')
        unchanged(bound_files);unchanged(mapped)
        if products!=file_hashes(lib) or probe_classes!=file_hashes(classes):raise ValueError('output changed')
        if initial!=recipe():raise ValueError('recipe changed')
        evidence={str(n.relative_to(out)):b.native.digest(n) for n in out.iterdir() if n.is_file()}
        result={'evidence':evidence,'recipe':initial,'bound_files':bound_files,'products':products,'probe_classes':probe_classes,'dynamic_needed':dynamic,'genuine_gdal_jni':True,'gdal_version':'2.4.4','gdal_archive_objects':len(json.loads((a.dependency_proof/'dependencies-built.json').read_text())['objects_after']),'consumed_header_receipt_sha256':b.native.digest(out/'consumed-header-hashes.json'),'tools':tools,'wrappers':{n:b.native.digest(frozen/n) for n in wrappers},'mapped_providers':mapped,'recipe_sha256':b.native.digest(HERE/'build.py'),'probe_sha256':b.native.digest(HERE/'GdalJniProbe.java'),'native_kernel_or_client_acceptance':False}
        (out/'complete.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception:
        (out/'failed.json').write_text(json.dumps({'last_command':commands[-1]['name'] if commands else None,'native_kernel_or_client_acceptance':False},indent=2)+'\n');raise
if __name__=='__main__':
    import sys
    if len(sys.argv)==3 and sys.argv[1]=='--replay':
        replay(Path(sys.argv[2]));print('verified GDAL JNI receipt replay')
    else:main()
