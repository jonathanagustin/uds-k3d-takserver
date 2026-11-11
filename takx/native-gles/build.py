#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Build genuine GLVND dispatch and prove local Mesa surfaceless ES3 rendering."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import time
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
MODULES={}
for name,rel in {'native':'native-deps/build.py','las':'native-las/build.py'}.items():
    spec=importlib.util.spec_from_file_location('gles_'+name,HERE.parent/rel)
    MODULES[name]=importlib.util.module_from_spec(spec);spec.loader.exec_module(MODULES[name])
native,las=MODULES['native'],MODULES['las']
LOCK_SHA='176ba6f599c01bd815f23174cd0fdbff4f56a963854614ffb49e91e5f90df7cf'


def validate_lock(lock):
    if hashlib.sha256(json.dumps(lock,sort_keys=True).encode()).hexdigest()!=LOCK_SHA:
        raise ValueError('unreviewed GLVND source/tool/header selection')


def recipe():
    return {n:native.digest(HERE/n) for n in ('build.py','inputs.lock.json','SurfacelessES3.c')}|{
        '../native-deps/build.py':native.digest(HERE.parent/'native-deps/build.py'),
        '../native-las/build.py':native.digest(HERE.parent/'native-las/build.py')}


def wheel_unpack(path,output,entry):
    with zipfile.ZipFile(path) as z:
        info=z.infolist()
        if len(info)!=entry['members'] or sum(i.file_size for i in info)!=entry['expanded_bytes']:
            raise ValueError('Meson package expansion differs')
        seen=set()
        for i in info:
            relative=native.relative(i.filename)
            if i.filename in seen or stat.S_IFMT(i.external_attr>>16) not in (0,stat.S_IFREG,stat.S_IFDIR):
                raise ValueError('duplicate or special package path')
            seen.add(i.filename);p=output/relative
            if i.is_dir():p.mkdir(parents=True,exist_ok=True)
            else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(i))


def source_unpack(path,output,entry,links):
    """Materialize only the exact upstream in-tree uthash directory layout."""
    with tarfile.open(path) as t:
        members=t.getmembers();regular=[m for m in members if m.isfile()]
        if (len(members),len(regular),sum(m.size for m in regular))!=(entry['members'],entry['regular_files'],entry['expanded_bytes']):
            raise ValueError('source archive inventory differs')
        seen=set();actual_links={}
        for m in members:
            rel=native.relative(m.name)
            if m.name in seen or rel.parts[0]!=entry['root']:raise ValueError('duplicate or foreign source member')
            seen.add(m.name)
            if m.issym():
                if m.name not in links or m.linkname!=links[m.name]['target']:
                    raise ValueError('unreviewed source link')
                rule=links[m.name]
                if str(rel.parent / native.relative(m.linkname))+'/'!=rule['source_subtree']:
                    raise ValueError('source link target is not the exact in-tree subtree')
                subtree={x.name[len(rule['source_subtree']):]:{'bytes':x.size,'sha256':hashlib.sha256(t.extractfile(x).read()).hexdigest()} for x in regular if x.name.startswith(rule['source_subtree'])}
                if not subtree or subtree!=rule['files']:raise ValueError('archive-owned source-link subtree differs')
                actual_links[m.name]=rule
            elif not (m.isdir() or m.isfile()):raise ValueError('special source member')
        if set(actual_links)!=set(links):raise ValueError('required source layout link missing')
        for m in regular:
            dst=output/native.relative(m.name);dst.parent.mkdir(parents=True,exist_ok=True)
            with t.extractfile(m) as src,dst.open('xb') as target:shutil.copyfileobj(src,target)
            dst.chmod(0o755 if m.mode & 0o111 else 0o644)
        for name,rule in actual_links.items():
            for tail,record in rule['files'].items():
                src=output/native.relative(rule['source_subtree']+tail);dst=output/native.relative(name)/native.relative(tail)
                if native.digest(src)!=record['sha256']:raise ValueError('materialization source changed')
                dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    return inventory(output)


def inventory(root):
    if any(p.is_symlink() for p in root.rglob('*')):raise ValueError('source symlink refused')
    return {str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':native.digest(p)} for p in root.rglob('*') if p.is_file()}


def providers(text,prefix):
    try:lines=text.split('providers_begin\n',1)[1].split('providers_end\n',1)[0].splitlines()
    except IndexError:raise ValueError('actual loader provider list missing') from None
    found={}
    for line in lines:
        if line=='linux-vdso.so.1':continue
        p=Path(line)
        if not p.is_absolute() or not p.is_file():raise ValueError('non-file runtime provider')
        p=p.resolve()
        if not (p.is_relative_to(prefix.resolve()) or p.is_relative_to(Path('/usr/lib/x86_64-linux-gnu'))):
            raise ValueError('unreviewed runtime provider directory')
        found[str(p)]={'sha256':native.digest(p),'bytes':p.stat().st_size}
    for name in ('libEGL.so.1.1.0','libGLESv2.so.2.1.0','libGLdispatch.so.0.0.0'):
        if str((prefix/'lib'/name).resolve()) not in found:raise ValueError('owned genuine dispatch provider missing')
    if not any(Path(p).name.startswith('libEGL_mesa.so.') for p in found) or not any('libgallium' in Path(p).name for p in found):
        raise ValueError('actual Mesa software provider missing')
    return found


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','cache','headers'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--ninja',type=Path,default=Path('/workspace/takx-native-tools/venv/bin/ninja'))
    p.add_argument('--fetch-dependencies',action='store_true');args=p.parse_args()
    if (platform.system(),platform.machine())!=('Linux','x86_64'):raise ValueError('Linux amd64 host profile only')
    lock=json.loads((HERE/'inputs.lock.json').read_text());validate_lock(lock);initial=recipe()
    output,cache=native.external(args.output),native.external(args.cache)
    if output.exists() or output==cache or output in cache.parents or cache in output.parents:raise ValueError('new separate output required')
    if output==args.headers.resolve() or args.headers.resolve() in output.parents or output in args.headers.resolve().parents:raise ValueError('output overlaps verified headers')
    output.mkdir(parents=True,mode=0o700);cache.mkdir(parents=True,exist_ok=True)
    deadline=time.monotonic()+600;commands=[]
    cc=Path('/usr/bin/gcc').resolve();ninja=args.ninja.resolve();python=Path(sys.executable).resolve()
    tools={str(x):native.digest(x) for x in (cc,ninja,python)}
    env=las.environment({'cc':{'path':str(cc)},'cxx':{'path':str(cc)}})
    for key in list(env):
        if key.startswith(('LD_','MESA_','EGL_','GLVND_','GALLIUM_','LIBGL_','__EGL_','PYTHON','PKG_CONFIG','CMAKE_','BASH_FUNC_')) or key in ('CPP','LIBS','MAKEFLAGS','CONFIG_SITE','AR','RANLIB','CC','CXX'):
            env.pop(key,None)
    env.update(CC=str(cc),CFLAGS='-O2 -fPIC',LC_ALL='C',PYTHONDONTWRITEBYTECODE='1',PKG_CONFIG_PATH='',PKG_CONFIG_LIBDIR=str(output/'absent-pkgconfig'))
    def run(cmd,name,timeout=60,capture=False,extra=None):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ValueError('GLES total command deadline exhausted')
        commands.append({'name':name,'argv':list(map(str,cmd))});(output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        data=native.run(list(map(str,cmd)),output,name,timeout=min(timeout,remaining),env=env|(extra or {}),capture=capture)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink())>lock['bounds']['output_bytes']:
            raise ValueError('GLES output exceeds1GiB')
        return data.decode() if capture else ''
    headers={}
    include=output/'include';include.mkdir()
    for h in lock['headers']:
        src=args.headers/h['destination'];native.verified(src,h)
        dst=include/h['destination'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst);headers[h['destination']]=native.digest(dst)
    vendor=Path('/usr/share/glvnd/egl_vendor.d/50_mesa.json');vendor_data=json.loads(vendor.read_text())
    if vendor_data!={'file_format_version':'1.0.0','ICD':{'library_path':'libEGL_mesa.so.0'}}:raise ValueError('unexpected Mesa EGL vendor contract')
    mesa=Path('/usr/lib/x86_64-linux-gnu/libEGL_mesa.so.0').resolve();dri=Path('/usr/lib/x86_64-linux-gnu/dri/swrast_dri.so').resolve()
    host={str(x):native.digest(x) for x in (vendor,mesa,dri)}
    archive=native.acquire(cache,lock['source'],args.fetch_dependencies);wheel=native.acquire(cache,lock['meson'],args.fetch_dependencies)
    sources=output/'source';sources.mkdir();source_before=source_unpack(archive,sources,lock['source'],lock['source_links'])
    src=sources/lock['source']['root']
    for name,sha in lock['license_notices'].items():
        if native.digest(sources/name)!=sha:raise ValueError('source license notice differs')
    meson=output/'meson';meson.mkdir();wheel_unpack(wheel,meson,lock['meson']);meson_before=inventory(meson)
    (output/'frozen-inputs.json').write_text(json.dumps({'recipe':initial,'source':lock['source'],'meson':lock['meson'],'headers':headers,'host':host,'tools':tools},indent=2)+'\n')
    if not run([cc,'--version'],'cc-version',capture=True).splitlines()[0].endswith(' 14.2.0'):raise ValueError('GCC differs')
    menv={'PYTHONPATH':str(meson),'NINJA':str(ninja)}
    if run([python,'-m','mesonbuild.mesonmain','--version'],'meson-version',capture=True,extra=menv).strip()!='1.7.2':raise ValueError('Meson version differs')
    build,prefix=output/'build',output/'install'
    run([python,'-m','mesonbuild.mesonmain','setup',build,src,'--prefix='+str(prefix),'--libdir=lib','--buildtype=release','-Dx11=disabled','-Dglx=disabled','-Degl=true','-Dgles1=false','-Dgles2=true','-Dhgl=false','-Dheaders=false','--wrap-mode=nodownload'],'configure',90,extra=menv)
    run([ninja,'-C',build,'-j1'],'source-build',300,extra=menv)
    run([python,'-m','mesonbuild.mesonmain','install','-C',build,'--no-rebuild'],'source-install',60,extra=menv)
    ownvendor=output/'mesa-vendor.json';ownvendor.write_text(json.dumps({'file_format_version':'1.0.0','ICD':{'library_path':str(mesa)}})+'\n')
    probe=output/'surfaceless-es3';run([cc,'-std=c11','-O1','-I'+str(include),HERE/'SurfacelessES3.c',prefix/'lib/libEGL.so.1',prefix/'lib/libGLESv2.so.2','-ldl','-Wl,-rpath,'+str(prefix/'lib'),'-o',probe],'probe-compile')
    runtimeenv={'LD_LIBRARY_PATH':str(prefix/'lib'),'__EGL_VENDOR_LIBRARY_FILENAMES':str(ownvendor),'LIBGL_DRIVERS_PATH':'/usr/lib/x86_64-linux-gnu/dri','LIBGL_ALWAYS_SOFTWARE':'1','GALLIUM_DRIVER':'llvmpipe','EGL_PLATFORM':'surfaceless'}
    text=run([probe],'real-es3-control',30,True,runtimeenv)
    if text.splitlines().count('real_surfaceless_es3_clear_readback=true')!=1:raise ValueError('actual ES3 control incomplete')
    runtime=providers(text,prefix)
    provenance={}
    for name in runtime:
        if Path(name).is_relative_to(prefix):continue
        result=subprocess.run(['dpkg-query','-S',name],capture_output=True,text=True,timeout=10)
        if result.returncode:raise ValueError('host package provenance unavailable')
        package=result.stdout.strip().split(': /',1)[0]
        version=subprocess.check_output(['dpkg-query','-W','-f=${Package} ${Version}',package],timeout=10).decode()
        provenance[name]=version
    if inventory(sources)!=source_before or inventory(meson)!=meson_before or recipe()!=initial:raise ValueError('source/tool package/recipe changed')
    for path,sha in (tools|host).items():
        if native.digest(Path(path))!=sha:raise ValueError('host/tool input changed')
    for path,entry in runtime.items():
        if native.digest(Path(path))!=entry['sha256']:raise ValueError('runtime provider changed')
    record={'schema_version':1,'profile':lock['profile'],'recipe':initial,'lock':lock,'tools':tools,'headers':headers,'host_inputs':host,'source_inventory':source_before,'meson_inventory':meson_before,'installed':native.inventory(prefix),'runtime_providers':runtime,'host_package_provenance':provenance,'probe':{'sha256':native.digest(probe),'bytes':probe.stat().st_size},'runtime_env':runtimeenv,'genuine_surfaceless_es3_clear_readback':True,'fresh_source_build':True,'host_mesa_source_built_here':False,'full_kernel_sdk_acceptance':False,'renderer_integration_acceptance':False,'takx_acceptance':False,'target_abi_acceptance':False,'security_acceptance':False}
    (output/'complete.json').write_text(json.dumps(record,indent=2)+'\n');print('Genuine source-built GLVND + host Mesa surfaceless ES3 clear/readback passed')


if __name__=='__main__':main()
