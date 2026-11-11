#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Owned two-crypto ELF integration experiment, not CommonCommo or SDK."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
HERE=Path(__file__).resolve().parent
MODULES={}
for name,relative in [('native','native-deps/build.py'),('las','native-las/build.py'),('sql','native-sqlcipher/build.py')]:
    spec=importlib.util.spec_from_file_location('crypto_'+name,HERE.parent/relative)
    MODULES[name]=importlib.util.module_from_spec(spec);spec.loader.exec_module(MODULES[name])
native,las,sql=(MODULES[n] for n in ['native','las','sql'])
LOCK=json.loads((HERE/'inputs.lock.json').read_text())
LOCK_SHA='29e9ccbaaf03373dab9eafb4af18305ab6b39937dacff367e2e27681bc77cc9b'
FILES=('build.py','inputs.lock.json','Group.c','LoadOrders.c','exports.map','run-in.py')
CRYPTO=re.compile(r'^(?:SSL_|OPENSSL_|OpenSSL_|EVP_|OSSL_|BIO_|X509_|RSA_|EC_|BN_|CRYPTO_|sqlite3_)')
def validate_lock(lock):
    if hashlib.sha256(json.dumps(lock,sort_keys=True).encode()).hexdigest()!=LOCK_SHA:
        raise ValueError('unreviewed crypto source/patch/tool selection')
def recipe():
    result={n:native.digest(HERE/n) for n in FILES}
    for producer in [native,las,sql]:result['../'+str(Path(producer.__file__).relative_to(HERE.parent))]=native.digest(Path(producer.__file__))
    result['../native-sqlcipher/SqlcipherSourceProbe.c']=native.digest(sql.HERE/'SqlcipherSourceProbe.c')
    return result
def reused(root):
    root=native.external(root);path=root/'complete.json'
    if path.is_symlink():raise ValueError('receipt symlink refused')
    sha=native.digest(path);r=json.loads(path.read_text());sql.validate_lock(json.loads((sql.HERE/'inputs.lock.json').read_text()))
    if r.get('recipe')!=sql.recipe() or r.get('archives')!=sql.PINNED['archives'] or r.get('licenses')!=sql.PINNED['licenses']:
        raise ValueError('modern normative producer/source identity differs')
    for key in ['source_posthash_verified','encryption_controls','whole_archive_PIC','fresh_entrypoint']:
        if r.get(key) is not True:raise ValueError('modern proof incomplete')
    version_checks={'cc':lambda s:s.splitlines()[0].endswith(' '+LOCK['tools']['gcc']),
                    'make':lambda s:s.splitlines()[0]=='GNU Make '+LOCK['tools']['make'],
                    'perl':lambda s:'(v'+LOCK['tools']['perl']+')' in s,
                    'ar':lambda s:s.splitlines()[0].endswith(' '+LOCK['tools']['binutils']),
                    'ranlib':lambda s:s.splitlines()[0].endswith(' '+LOCK['tools']['binutils']),
                    'readelf':lambda s:s.splitlines()[0].endswith(' '+LOCK['tools']['binutils'])}
    if any(not check(r['tools'][name]['version']) for name,check in version_checks.items()):
        raise ValueError('modern normative tool versions differ')
    inputs=json.loads((root/'source-inputs.json').read_text())
    if len(inputs)!=r['source_files']:raise ValueError('modern source count differs')
    sql.check_sources(root/'source',inputs);sql.verify_probes(root,r['probe_outputs'])
    for name in ['tcl','openssl','sqlcipher']:
        if native.inventory(root/(name+'-install'))!=r['installed'][name]:raise ValueError('modern installed bytes differ')
    las.verify_runtime(r['runtime_closure'])
    for tool in r['tools'].values():
        if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('modern tool differs')
    if native.digest(path)!=sha:raise ValueError('modern receipt changed')
    return r,sha
def environment(tools,output):
    env=sql.environment(tools,output)
    for key in list(env):
        if key.startswith(('SSL','CRYPTO','QUIC','BASH_FUNC_')) or key in ['MAKEFILES','GNUMAKEFLAGS','MFLAGS','SHELL','CONFIG_SHELL']:
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC',CXXFLAGS='-O2 -fPIC',CONFIG_SITE='/dev/null')
    return env
def disk_bound(output,cache):
    size=sum(p.stat().st_size for r in [output,cache] for p in r.rglob('*') if p.is_file() and not p.is_symlink())
    if size>2*1024**3:raise ValueError('crypto output/cache exceeds2GiB')
    return size
def symbols(text,expected):
    exported=set()
    for line in text.splitlines():
        words=line.split()
        if len(words)<8 or not words[0].endswith(':'):continue
        name=words[7].split('@')[0]
        if CRYPTO.match(name):raise ValueError('crypto/SQLite symbol escapes local group: '+name)
        if words[6]!='UND' and words[4] in ['GLOBAL','WEAK']:exported.add(name)
    if exported!=set(expected):raise ValueError('owned experiment exports differ: '+repr(exported))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--modern-proof',type=Path,required=True);p.add_argument('--fetch-dependencies',action='store_true');a=p.parse_args()
    if (platform.system(),platform.machine())!=('Linux','x86_64'):raise ValueError('Linux amd64 only')
    validate_lock(LOCK);initial=recipe();modern=native.external(a.modern_proof);mr,msha=reused(modern)
    output,cache=sql.validate_paths(a.output,a.cache)
    if any(r==modern or r in modern.parents or modern in r.parents for r in [output,cache]):raise ValueError('modern input must be separate')
    output.mkdir(parents=True);cache.mkdir(parents=True,exist_ok=True)
    tools=mr['tools'];env=environment(tools,output);deadline=time.monotonic()+1200;commands=[]
    def run(args,name,cwd=None,timeout=30,capture=False):
        left=deadline-time.monotonic()
        if left<=0:raise ValueError('20minute command budget exhausted')
        argv=list(map(str,args))
        if cwd:argv=[sys.executable,str(HERE/'run-in.py'),str(cwd)]+argv
        commands.append({'name':name,'argv':argv,'timeout':min(timeout,left)});(output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        result=native.run(argv,output,name,timeout=min(timeout,left),env=env,capture=capture);disk_bound(output,cache);return result
    try:
        archive=native.acquire(cache,LOCK['archive'],a.fetch_dependencies);patch=native.acquire(cache,LOCK['patch'],a.fetch_dependencies)
        source=output/'source';source.mkdir();expected=las.unpack(archive,source,LOCK['archive']['root'],LOCK['archive']);sql.check_sources(source,expected)
        src=source/LOCK['archive']['root']
        for name,images in LOCK['patch']['files'].items():
            if native.digest(src/name)!=images['before']:raise ValueError('patch preimage differs')
        patchtool=Path(shutil.which('patch')).resolve();patch_identity=native.digest(patchtool)
        run([patchtool,'--fuzz=0','--batch','--no-backup-if-mismatch','-p0','-i',patch],'official-patch',src)
        for name,images in LOCK['patch']['files'].items():
            if native.digest(src/name)!=images['after']:raise ValueError('patch postimage differs')
            path=LOCK['archive']['root']+'/'+name;expected[path]={'bytes':(src/name).stat().st_size,'sha256':images['after']}
        sql.check_sources(source,expected)
        if native.digest(src/LOCK['license']['source'])!=LOCK['license']['sha256']:raise ValueError('license differs')
        (output/'sources.json').write_text(json.dumps(expected,sort_keys=True)+'\n')
        build=output/'quictls-build';build.mkdir();prefix=output/'quictls-install'
        run([tools['perl']['path'],src/'Configure','linux-x86_64','no-shared','no-tests','no-module','--prefix='+str(prefix),'--libdir=lib','-O2','-fPIC'],'quictls-configure',build,90)
        run([tools['make']['path'],'-j1','build_libs'],'quictls-build',build,1000)
        run([tools['make']['path'],'-j1','install_dev'],'quictls-install',build,90)
        installed=native.inventory(prefix);sql.check_sources(source,expected)
        cc=tools['cc']['path'];link=['-shared','-fPIC','-O2','-Wl,--no-undefined','-Wl,--exclude-libs,libcrypto.a:libssl.a:libsqlite3.a','-Wl,--version-script='+str(HERE/'exports.map')]
        for group in ['quictls','modern']:
            q=group=='quictls';inc=prefix/'include' if q else modern/'openssl-install/include';lib=prefix/'lib' if q else modern/'openssl-install/lib'
            libs=([lib/'libssl.a'] if q else [modern/'sqlcipher-install/lib/libsqlite3.a'])+[lib/'libcrypto.a']
            args=[cc]+link+['-I'+str(inc),'-I'+str(sql.HERE),'-I'+str(modern/'sqlcipher-install/include')]
            if q:args+=['-DQUICTLS_GROUP']
            else:args+=['-DSQLITE_HAS_CODEC']
            run(args+[HERE/'Group.c']+libs+['-ldl','-pthread','-lm','-Wl,-Map='+str(output/(group+'.map')),'-o',output/(group+'-group.so')],group+'-link',timeout=60)
            text=run([tools['readelf']['path'],'--dyn-syms','--wide',output/(group+'-group.so')],group+'-dynsym',capture=True).decode();symbols(text,['q_version','q_aes','q_quic'] if q else ['m_version','m_aes','m_database'])
            dynamic=run([tools['readelf']['path'],'-d',output/(group+'-group.so')],group+'-dynamic',capture=True).decode()
            if 'TEXTREL' in dynamic or any(x in dynamic for x in ['libcrypto.so','libssl.so','libsqlite3.so']):raise ValueError('shared crypto/SQLite or textrel')
            sql.runtime_closure(run(['ldd',output/(group+'-group.so')],group+'-closure',capture=True).decode())
        run([cc,'-O2',HERE/'LoadOrders.c','-ldl','-o',output/'load-orders'],'driver-link')
        maps={}
        for order in ['qm','mq']:
            text=run([output/'load-orders',order,output/'quictls-group.so',output/'modern-group.so',output/(order+'.db')],order+'-load',timeout=30,capture=True).decode()
            if any(word not in text for word in ['aes_both=PASS','quictls_clienthello_callback=PASS','encrypt_reopen_wrong_key=PASS','OpenSSL 3.0.14','OpenSSL 3.5.9']):raise ValueError('both-load-order controls incomplete')
            paths=set(re.findall(r'^map=.*?(/[^\n]+)$',text,re.M))
            if any(Path(x).name.startswith(('libssl.so','libcrypto.so')) for x in paths):raise ValueError('shared crypto mapped')
            if not all(str(output/(g+'-group.so')) in paths for g in ['quictls','modern']):raise ValueError('actual group maps missing')
            maps[order]={x:native.digest(Path(x)) for x in paths}
        reused(modern);sql.check_sources(source,expected);native.verified(archive,LOCK['archive']);native.verified(patch,LOCK['patch'])
        if initial!=recipe() or installed!=native.inventory(prefix) or native.digest(patchtool)!=patch_identity:raise ValueError('recipe/install/tool changed')
        outputs={str(x.relative_to(output)):{'sha256':native.digest(x),'bytes':x.stat().st_size} for x in output.iterdir() if x.is_file() and x.suffix in ['.so','.db'] or x==output/'load-orders'}
        receipt={'profile':'two-real-crypto-groups','recipe':initial,'lock':LOCK,'modern_receipt_sha256':msha,'source_inventory':expected,'quictls_installed':installed,'tools':tools,'patch_tool':{'path':str(patchtool),'sha256':patch_identity},'outputs':outputs,'maps':maps,'disk_bytes':disk_bound(output,cache),'single_job':True,'command_budget_s':1200,'both_rtld_global_orders':True,'aes_known_vector_both':True,'quictls_clienthello_callback':True,'modern_sqlcipher_encrypted_wrong_key':True,'full_quic_handshake':False,'commoncommo_acceptance':False,'kernel_sdk_acceptance':False,'takx_acceptance':False}
        (output/'complete.json').write_text(json.dumps(receipt,indent=2)+'\n');print('Genuine two-crypto static hidden-symbol load orders passed')
    except Exception:
        (output/'failed.json').write_text('{"status":"stopped; private logs retained; no success inferred"}\n');raise
if __name__=='__main__':main()
