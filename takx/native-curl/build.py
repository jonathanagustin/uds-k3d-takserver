#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded genuine current Curl provider for the modern Core crypto group."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tarfile
import time
HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
native=module('curl_native',HERE.parent/'native-deps/build.py')
sql=module('curl_sql',HERE.parent/'native-sqlcipher/build.py')
scene=module('curl_scene',HERE.parent/'kernel-scene/build.py')


def inventory(root):
    found={}
    for p in root.rglob('*'):
        if p.is_symlink() or not(p.is_file() or p.is_dir()):raise ValueError('nonregular source input')
        if p.is_file():found[str(p.relative_to(root))]={'bytes':p.stat().st_size,'sha256':native.digest(p)}
    return found


def extract(path,output,lock):
    if path.is_symlink() or path.stat().st_size!=lock['bytes'] or native.digest(path)!=lock['sha256']:raise ValueError('Curl archive identity differs')
    with tarfile.open(path) as tar:
        members=tar.getmembers();names=set();roots=set();total=0
        for m in members:
            p=native.relative(m.name);roots.add(p.parts[0]);total+=m.size if m.isfile() else 0
            if m.name in names or not(m.isdir() or m.isfile()):raise ValueError('nonregular or duplicate source member')
            names.add(m.name)
        if len(roots)!=1 or len(members)>10000 or total!=lock['expanded_bytes'] or total>64*1024**2:raise ValueError('Curl expansion bound differs')
        output.mkdir()
        for m in members:
            if not m.isfile():continue
            target=output/Path(*native.relative(m.name).parts[1:]);target.parent.mkdir(parents=True,exist_ok=True)
            with tar.extractfile(m) as incoming,target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)
            target.chmod(0o755 if m.mode&0o111 else 0o644)


def providers(openssl,zlib):
    data=json.loads((openssl/'complete.json').read_text())
    if data['recipe']!=sql.recipe() or not data.get('whole_archive_PIC') or not data.get('encryption_controls'):raise ValueError('OpenSSL producer recipe/controls differ')
    if data['archives']['openssl']['sha256']!=sql.PINNED['archives']['openssl']['sha256']:raise ValueError('OpenSSL3.5.9 source pin differs')
    for name,expected in data['installed'].items():
        if native.inventory(openssl/(name+'-install'))!=expected:raise ValueError('OpenSSL producer installation changed')
    sql.check_sources(openssl/'source',json.loads((openssl/'source-inputs.json').read_text()))
    for tool in data['tools'].values():
        if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('OpenSSL producer tool changed')
    for name,item in data['probe_outputs'].items():
        p=openssl/native.relative(name)
        if p.is_symlink() or p.stat().st_size!=item['bytes'] or native.digest(p)!=item['sha256']:raise ValueError('OpenSSL controls changed')
    scene.verify_dependency(zlib,'assimp')
    return {'openssl_receipt_sha256':native.digest(openssl/'complete.json'),'zlib_receipt_sha256':native.digest(zlib/'complete.json'),'openssl_products':inventory(openssl/'openssl-install'),'zlib_products':inventory(zlib/'zlib-install')}


def disk(root):
    size=0
    for p in root.rglob('*'):
        try:s=p.lstat()
        except FileNotFoundError:continue
        if stat.S_ISREG(s.st_mode):size+=s.st_size
    return size


def execute(argv,root,name,deadline,env,capture=False,disk_limit=512*1024**2,log_limit=16*1024**2):
    child=None;result=bytearray();total=0;check=0
    try:
        with (root/(name+'.log')).open('xb') as log:
            child=subprocess.Popen(list(map(str,argv)),cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
            with selectors.DefaultSelector() as poll:
                poll.register(child.stdout,selectors.EVENT_READ)
                while poll.get_map() or child.poll() is None:
                    now=time.monotonic()
                    if now>=deadline:raise ValueError('ten minute total command deadline exceeded')
                    if now>=check:
                        if disk(root)>disk_limit:raise ValueError('512MiB output bound exceeded')
                        check=now+1
                    for key,_ in poll.select(min(.1,deadline-now)):
                        b=os.read(key.fileobj.fileno(),65536)
                        if not b:poll.unregister(key.fileobj);continue
                        total+=len(b)
                        if total>log_limit:raise ValueError('command log bound exceeded')
                        log.write(b)
                        if capture:result.extend(b)
            if child.wait(timeout=max(.001,deadline-time.monotonic())):raise ValueError('owned command failed')
            if disk(root)>disk_limit:raise ValueError('512MiB output bound exceeded')
    finally:
        if child:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait();child.stdout.close()
    return bytes(result)


def recipe():
    return {name:native.digest(HERE/name) for name in ('build.py','CurlProbe.c','inputs.lock.json','source.lock.json','../native-deps/build.py','../native-sqlcipher/build.py','../native-las/build.py','../kernel-scene/build.py','../native-assimp/build.py','../kernel-scene/producer.py')}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','archive','openssl-proof','zlib-proof'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    def expired(signum,frame):raise TimeoutError('ten minute total profile deadline exceeded')
    signal.signal(signal.SIGALRM,expired);signal.alarm(600)
    out=native.external(args.output)
    if out.exists():raise ValueError('new output required')
    for root in (HERE,args.archive,args.openssl_proof,args.zlib_proof):
        if out==root.resolve() or root.resolve() in out.parents or out in root.resolve().parents:raise ValueError('output overlaps input')
    lock=json.loads((HERE/'inputs.lock.json').read_text());post=json.loads((HERE/'source.lock.json').read_text())
    if lock['bytes']>8*1024**2 or native.digest(HERE/'source.lock.json')!=lock['source_inventory_sha256']:raise ValueError('input bounds/source lock differs')
    initial=recipe();provider=providers(args.openssl_proof,args.zlib_proof)
    tools={name:{'path':str(Path(shutil.which(name)).resolve()),'sha256':native.digest(Path(shutil.which(name)).resolve())} for name in ('gcc','ar','ranlib','ld','as','nm','readelf','ldd','perl')}
    for name in ('cc1','collect2'):
        path=Path(subprocess.check_output([tools['gcc']['path'],'-print-prog-name='+name],text=True,timeout=10).strip()).resolve();tools[name]={'path':str(path),'sha256':native.digest(path)}
    cm=Path('/workspace/takx-native-tools/venv/bin/cmake');nj=Path('/workspace/takx-native-tools/venv/bin/ninja')
    for name,path in [('cmake',cm),('ninja',nj)]:tools[name]={'path':str(path),'sha256':native.digest(path)}
    out.mkdir(mode=0o700);deadline=time.monotonic()+600;current='source'
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('LD_','DYLD_','CMAKE','PKG_CONFIG','OPENSSL')) or key in ('CC','CXX','CPP','AR','RANLIB','LD','AS','NM','CFLAGS','CPPFLAGS','CXXFLAGS','LDFLAGS','LIBS','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','MAKEFLAGS','MAKEFILES','GNUMAKEFLAGS','BASH_ENV','ENV','CONFIG_SITE'):env.pop(key,None)
    env.update({'PATH':'/usr/bin:/bin','LC_ALL':'C','CMAKE_BUILD_PARALLEL_LEVEL':'1','MAKEFLAGS':'-j1','OPENSSL_CONF':'/dev/null','OPENSSL_MODULES':str(out/'no-provider-modules')})
    def run(argv,name,capture=False):return execute(argv,out,name,deadline,env,capture)
    try:
        source=out/'source';extract(args.archive,source,lock)
        if inventory(source)!=post or native.digest(source/'COPYING')!=lock['license_sha256']:raise ValueError('Curl whole source/license changed')
        prefix=out/'install';op=args.openssl_proof.resolve()/'openssl-install';zp=args.zlib_proof.resolve()/'zlib-install'
        flags=['-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DCMAKE_C_COMPILER='+tools['gcc']['path'],'-DCMAKE_MAKE_PROGRAM='+str(nj),'-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF','-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF','-DCMAKE_FIND_ROOT_PATH='+str(op)+';'+str(zp),'-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY','-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY','-DOPENSSL_ROOT_DIR='+str(op),'-DOPENSSL_USE_STATIC_LIBS=TRUE','-DOPENSSL_SSL_LIBRARY='+str(op/'lib/libssl.a'),'-DOPENSSL_CRYPTO_LIBRARY='+str(op/'lib/libcrypto.a'),'-DOPENSSL_INCLUDE_DIR='+str(op/'include'),'-DZLIB_ROOT='+str(zp),'-DZLIB_LIBRARY='+str(zp/'lib/libz.a'),'-DZLIB_INCLUDE_DIR='+str(zp/'include'),*['-D'+f for f in lock['cmake_flags']]]
        (out/'configuration.json').write_text(json.dumps({'recipe':initial,'tools':tools,'providers':provider,'flags':flags},indent=2)+'\n')
        current='configure';run([cm,'-S',source,'-B',out/'build',*flags],'configure')
        cache=(out/'build/CMakeCache.txt').read_text()
        for flag in lock['cmake_flags']:
            name,value=flag.split('=',1)
            if name in ('CURL_CA_BUNDLE','CURL_CA_PATH') and value=='none':continue  # upstream deliberately unsets these cache keys
            if not re.search(r'^'+re.escape(name)+r':(?!UNINITIALIZED)[^=]+='+re.escape(value)+r'$',cache,re.M):raise ValueError('requested Curl feature flag not recognized')
        current='compile';run([cm,'--build',out/'build','--parallel','1'],'compile');run([cm,'--install',out/'build'],'install')
        current='strict-shared';shared=out/'libcurl-profile.so';archives=[prefix/'lib/libcurl.a',op/'lib/libssl.a',op/'lib/libcrypto.a',zp/'lib/libz.a']
        run([tools['gcc']['path'],'-shared','-Wl,--no-undefined','-Wl,--exclude-libs,libssl.a:libcrypto.a','-Wl,--whole-archive',*archives,'-Wl,--no-whole-archive','-pthread','-ldl','-o',shared],'strict-pic')
        symbols=set()
        for index,archive in enumerate(archives[1:3]):
            text=run([tools['nm']['path'],'-g','--defined-only',archive],'crypto-symbols-'+str(index),True).decode()
            symbols|={row.split()[-1] for row in text.splitlines() if len(row.split())>=3 and row.split()[-2].upper()!='U'}
        dyn=run([tools['readelf']['path'],'--dyn-syms','--wide',shared],'dynamic-symbols',True).decode()
        for line in dyn.splitlines():
            cols=line.split()
            if len(cols)>=8 and cols[0].endswith(':') and cols[7].split('@')[0] in symbols:raise ValueError('crypto symbol escaped or shared backend imported')
        current='consumer';probe=out/'curl-probe'
        run([tools['gcc']['path'],'-DCURL_STATICLIB','-I'+str(prefix/'include'),HERE/'CurlProbe.c',shared,'-Wl,-rpath,'+str(out),'-ldl','-o',probe],'probe-compile')
        text=run([probe],'probe',True).decode()
        if not text.startswith('curl_8.23.0_escape_free_backend_feature_controls=true\n'):raise ValueError('Curl actual controls incomplete')
        loaded={line[9:] for line in text.splitlines() if line.startswith('provider=')};allowed=re.compile(r'^(?:libc|libm|libdl|libpthread|librt)\.so(?:\..*)?$|^ld-linux-x86-64\.so\.2$')
        if str(shared) not in loaded or any(x!=str(shared) and not allowed.fullmatch(Path(x).name) for x in loaded):raise ValueError('foreign runtime provider')
        if initial!=recipe() or inventory(source)!=post or providers(args.openssl_proof,args.zlib_proof)!=provider or any(native.digest(Path(t['path']))!=t['sha256'] for t in tools.values()):raise ValueError('recipe/source/provider/tool changed')
        data={'schema_version':1,'profile':'public-core-curl','version':lock['version'],'openssl_version':'3.5.9','zlib_version':'1.3.1','recipe':initial,'tools':tools,'providers':provider,'flags':flags,'source_inventory_sha256':lock['source_inventory_sha256'],'installed':inventory(prefix),'objects':inventory(out/'build'),'strict_whole_archive_pic':True,'hidden_crypto_symbol_union':len(symbols),'escape_free_backend_feature_controls':True,'network_transfer_acceptance':False,'full_kernel_sdk_acceptance':False,'loaded_providers':sorted(loaded),'shared':{'bytes':shared.stat().st_size,'sha256':native.digest(shared)},'probe_sha256':native.digest(probe)}
        signal.alarm(0)
        (out/'complete.json').write_text(json.dumps(data,indent=2)+'\n');(out/'all-products.json').write_text(json.dumps(inventory(out),indent=2)+'\n');print('genuine_current_curl_controls=true full_kernel_sdk_acceptance=false')
    except Exception as exc:
        (out/'failed.json').write_text(json.dumps({'stage':current,'failure_class':str(exc),'full_kernel_sdk_acceptance':False},indent=2)+'\n');raise RuntimeError('bounded Curl profile stopped; inspect private failure') from None
if __name__=='__main__':main()
