#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Opt-in complete public CommonCommo JNI source build; not a TAKX client."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import lzma
import shutil
import subprocess
import sys
import tarfile
import time
HERE = Path(__file__).resolve().parent
MODULES = {}
for name, rel in {'native':'native-deps/build.py','las':'native-las/build.py',
                  'db':'kernel-spatial-db/build.py','crypto':'native-crypto/build.py',
                  'inputs':'source_inputs.py','tls':'test-tls.py'}.items():
    spec = importlib.util.spec_from_file_location('commo_'+name,HERE.parent/rel)
    MODULES[name] = importlib.util.module_from_spec(spec);spec.loader.exec_module(MODULES[name])
native,las,db,crypto,inputs,tls = (MODULES[n] for n in ['native','las','db','crypto','inputs','tls'])
LOCK = json.loads((HERE/'inputs.lock.json').read_text())
FILES = ('build.py','inputs.lock.json','run-in.py','runner.py','0102-jni-exception-boundaries.patch','producer-c992.lock.json','stage.py','resume.py','CommonCommoThrowingLogger.java')
spec = importlib.util.spec_from_file_location('commo_owned_runner',HERE/'runner.py')
runner = importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
SMOKES = ('CommonCommoSmoke','CommonCommoSignalSmoke','CommonCommoRoutingSmoke','CommonCommoTlsSmoke')

def smoke_path(name):
    return HERE/'CommonCommoThrowingLogger.java' if name=='CommonCommoThrowingLogger' else HERE.parent/(name+'.java')

def recipe():
    paths = [HERE/n for n in FILES]+[Path(m.__file__) for m in MODULES.values()]
    paths += [smoke_path(n) for n in (*SMOKES,'CommonCommoThrowingLogger')]
    paths += [HERE.parent/'sources.lock.json']
    paths += list((HERE.parent/'patches').glob('010*.patch'))+list((HERE.parent/'dependency-patches').glob('curl*.patch'))
    return {str(p.relative_to(HERE.parent)):native.digest(p) for p in paths}

def check_record(root, record):
    for name,entry in record.items():
        path = root/native.relative(name)
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=entry['bytes'] or native.digest(path)!=entry['sha256']:
            raise ValueError('bound source changed: '+name)

def archive_mtimes(archive, destination, entry):
    """Retain real release-tar ordering; safe extraction already rejected links."""
    with tarfile.open(archive) as tf:
        for member in tf:
            if member.isfile():
                if not 0 <= member.mtime <= 2**32:raise ValueError('archive timestamp outside bound')
                path=destination/native.relative(member.name)
                if path.is_symlink() or not path.is_file():raise ValueError('mtime target not regular')
                os.utime(path,(member.mtime,member.mtime))

def record(root):
    return {str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':native.digest(p)}
            for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}

def verify_providers(spatial,zlib,quictls):
    zr = db.dependency(zlib,'zlib')
    dr = json.loads((spatial/'complete.json').read_text())
    if dr['recipe']!=db.recipe() or dr.get('real_kernel_spatial_database_controls') is not True or dr.get('strict_pic') is not True:
        raise ValueError('joined DB producer/scope differs')
    for n in ['libiconv','libxml2']:
        check_record(spatial/(n+'-source'),dr['source_inventories'][n])
        if native.inventory(spatial/(n+'-install'))!=dr['installed'][n]:raise ValueError('DB provider inventory differs')
    qr=json.loads((quictls/'complete.json').read_text())
    if qr['recipe']!=crypto.recipe() or qr['lock']!=crypto.LOCK or not qr.get('both_rtld_global_orders') or not qr.get('quictls_clienthello_callback'):
        raise ValueError('quictls normative producer/source/scope differs')
    check_record(quictls/'source',qr['source_inventory'])
    if native.inventory(quictls/'quictls-install')!=qr['quictls_installed']:raise ValueError('quictls installed bytes differ')
    for r in [dr,qr]:
        for tool in r['tools'].values():
            if native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('provider tool differs')
    return {n:{'sha256':native.digest(p/'complete.json'),'recipe':r['recipe']} for n,p,r in [('spatial',spatial,dr),('zlib',zlib,zr),('quictls',quictls,qr)]}

def verify_tools(root,metadata):
    if native.digest(metadata/'InRelease')!=LOCK['tools']['inrelease_sha256'] or native.digest(metadata/'Packages.xz')!=LOCK['tools']['packages_sha256']:
        raise ValueError('signed Debian metadata differs')
    # Debian archive keyring is an explicit trusted host prerequisite, never fetched from the package being verified.
    subprocess.run(['/usr/bin/gpg','--batch','--no-options','--no-default-keyring','--keyring','/usr/share/keyrings/debian-archive-keyring.gpg',
                    '--homedir',str(metadata),'--verify',str(metadata/'InRelease')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=20)
    if f"{LOCK['tools']['packages_sha256']}  {LOCK['tools']['packages_bytes']} main/binary-amd64/Packages.xz" not in (metadata/'InRelease').read_text():
        raise ValueError('index is not bound by signed release metadata')
    entries={};entry={}
    with lzma.open(metadata/'Packages.xz','rt') as stream:
        for line in stream:
            if line=='\n':
                if entry.get('Package') in ('ant','dos2unix'):
                    entries[entry['Package']]={k:entry[k] for k in ('Package','Version','Filename','Size','SHA256')}
                entry={}
            elif ': ' in line and not line.startswith(' '):
                k,v=line.rstrip('\n').split(': ',1);entry[k]=v
    if entries!={e['Package']:e for e in LOCK['tools']['packages']}:raise ValueError('tool pins differ from signed package index')
    expected=set()
    for entry in LOCK['tools']['packages']:
        path=metadata/Path(entry['Filename']).name
        if native.digest(path)!=entry['SHA256'] or path.stat().st_size!=int(entry['Size']):raise ValueError('Debian tool package differs')
        # Compare actual extracted package files with the signed package payload, resolving only package-owned relative links.
        listing=subprocess.run(['/usr/bin/dpkg-deb','--fsys-tarfile',str(path)],stdout=subprocess.PIPE,check=True,timeout=20).stdout
        import io
        with tarfile.open(fileobj=io.BytesIO(listing)) as tf:
            for member in tf:
                if member.isdir():continue
                rel=native.relative(member.name.removeprefix('./'));expected.add(str(rel));dest=root/rel
                if member.isfile():
                    if not dest.is_file() or dest.is_symlink() or hashlib.sha256(tf.extractfile(member).read()).hexdigest()!=native.digest(dest):
                        raise ValueError('Debian tool installed file differs')
                elif member.issym():
                    if not dest.is_symlink() or os.readlink(dest)!=member.linkname or root.resolve() not in dest.resolve().parents:raise ValueError('Debian tool link differs')
                else:raise ValueError('unsupported Debian payload member')
    inventory=native.inventory(root)
    if {x['path'] for x in inventory}!=expected:raise ValueError('extra tool-prefix files refused')
    return inventory

def exports(text,crypto_symbols):
    escaped=set();public=set()
    for line in text.splitlines():
        cols=line.split()
        if len(cols)<8 or not cols[0].endswith(':'):continue
        name=cols[7].split('@')[0]
        if name in crypto_symbols:escaped.add(name)
        if cols[6]!='UND' and cols[4] in ['GLOBAL','WEAK'] and name:public.add(name)
    if escaped:raise ValueError('crypto symbols escape JNI group')
    if not public or any(not(n in ['JNI_OnLoad','JNI_OnUnload'] or n.startswith('Java_com_atakmap_commoncommo_')) for n in public):
        raise ValueError('unexpected JNI export')
    if 'JNI_OnLoad' not in public:raise ValueError('genuine JNI initialization missing')
    return sorted(public)

def runtime_closure(text):
    allowed={'libc.so.6','libm.so.6','libdl.so.2','libpthread.so.0','ld-linux-x86-64.so.2','libstdc++.so.6','libgcc_s.so.1'}
    result={}
    for line in text.splitlines():
        if not line.strip() or 'linux-vdso.so.1' in line:continue
        match=re.search(r'(?:=>\s*)?(/[^\s()]+)',line)
        if not match or Path(match[1]).name not in allowed:raise ValueError('foreign JNI runtime dependency')
        path=Path(match[1]).resolve()
        if not path.is_file() or not str(path).startswith('/usr/lib/'):raise ValueError('non-system JNI runtime dependency')
        result[str(path)]=native.digest(path)
    if not result:raise ValueError('empty JNI runtime closure')
    return result

def host_tools(java,env):
    result={}
    for name in ['gcc','g++','ar','ranlib','nm','readelf','make','perl','patch','pkg-config','openssl','ld','as','git','gpg','dpkg-deb','ldd']:
        path=Path(shutil.which(name,path='/usr/bin:/bin')).resolve()
        args=[str(path),'version' if name=='openssl' else '--version']
        version=subprocess.check_output(args,stderr=subprocess.STDOUT,env=env,timeout=10).decode().strip()
        result[name]={'path':str(path),'sha256':native.digest(path),'version':version}
    python=Path(sys.executable).resolve();result['python']={'path':str(python),'sha256':native.digest(python),'version':sys.version}
    for name in ['java','javac']:
        path=(java/'bin'/name).resolve();version=subprocess.check_output([str(path),'-version'],stderr=subprocess.STDOUT,env=env,timeout=10).decode().strip()
        if '17.0.21' not in version:raise ValueError('tested JDK17.0.21 required')
        result[name]={'path':str(path),'sha256':native.digest(path),'version':version}
    for name,driver in [('cc1','gcc'),('cc1plus','g++'),('collect2','g++')]:
        path=Path(subprocess.check_output([result[driver]['path'],'-print-prog-name='+name],env=env,text=True,timeout=10).strip()).resolve()
        if not path.is_file():raise ValueError('compiler backend missing')
        result[name]={'path':str(path),'sha256':native.digest(path)}
    if any(not result[n]['version'].splitlines()[0].endswith(' 14.2.0') for n in ['gcc','g++']):raise ValueError('tested GCC14.2.0 required')
    return result

def ant_config_guard(home=None):
    home=Path.home() if home is None else home
    if any(p.exists() or p.is_symlink() for p in [home/'.ant/ant.conf',home/'.antrc']):
        raise ValueError('user Ant configuration refused; use a clean existing account configuration')

def hard_deadline(signum,frame):
    raise TimeoutError('30minute total profile deadline exceeded')

def apply_jni_patch(source,run):
    entry=LOCK['jni_patch'];patch=HERE/entry['path']
    if patch.stat().st_size!=entry['bytes'] or native.digest(patch)!=entry['sha256']:raise ValueError('owned JNI patch bytes differ')
    for name,images in entry['files'].items():
        if native.digest(source/name)!=images['before']:raise ValueError('owned JNI patch preimage differs')
    run(['patch','--fuzz=0','--batch','--no-backup-if-mismatch','-p1','-i',patch],'owned-jni-exception-patch',source)
    for name,images in entry['files'].items():
        if native.digest(source/name)!=images['after']:raise ValueError('owned JNI patch postimage differs')

def environment(tools_root,java_home,prefix,output):
    env=dict(os.environ)
    for key in list(env):
        if key.startswith(('LD_','DYLD_','PKG_CONFIG','OPENSSL','SSL','CMAKE','BASH_FUNC_')) or key in ['CFLAGS','CPPFLAGS','CXXFLAGS','LDFLAGS','LIBS','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','LIBRARY_PATH','MAKEFLAGS','MAKEFILES','GNUMAKEFLAGS','BASH_ENV','ENV','CONFIG_SITE','PYTHONPATH','CC','CXX','AR','ARFLAGS','RANLIB','LD','AS','NM','CPP','MFLAGS','MAKEOVERRIDES','SHELL','CONFIG_SHELL','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','_JAVA_OPTIONS','ANT_ARGS','ANT_OPTS','CLASSPATH','JAVACMD','JDK_JAVAC_OPTIONS','ANT_LIB','LOCALCLASSPATH','CLASSPATH_OVERRIDE','JIKESPATH','usejikes','rpm_mode']:
            env.pop(key)
    env.update(JAVA_HOME=str(java_home),ANT_HOME=str(tools_root/'usr/share/ant'),
        PATH=str(tools_root/'usr/share/ant/bin')+':'+str(tools_root/'usr/bin')+':/usr/bin:/bin',
        CFLAGS='-O2 -fPIC',CXXFLAGS='-O2 -fPIC',CONFIG_SITE='/dev/null',PKG_CONFIG_LIBDIR=str(prefix/'lib/pkgconfig'),PKG_CONFIG_PATH='',
        CPPFLAGS='-I'+str(prefix/'include'),LDFLAGS='-L'+str(prefix/'lib'),OPENSSL_CONF='/dev/null',OPENSSL_MODULES=str(output/'no-provider-modules'),LC_ALL='C',TZ='UTC',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',ANT_ARGS='-nouserlib')
    tools=host_tools(java_home,env);jdk_inventory=native.inventory(java_home);debian_keyring_sha=native.digest(Path('/usr/share/keyrings/debian-archive-keyring.gpg'))
    env.update({key:tools[name]['path'] for key,name in [('CC','gcc'),('CXX','g++'),('AR','ar'),('RANLIB','ranlib'),('LD','ld'),('AS','as'),('NM','nm'),('PKG_CONFIG','pkg-config')]})
    env['CPP']=tools['gcc']['path']+' -E';env['JAVACMD']=tools['java']['path'];ant_config_guard()
    return env,tools,jdk_inventory,debian_keyring_sha

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['output','cache','source','spatial-proof','zlib-proof','quictls-proof','tools-root','tool-metadata','java-home']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--fetch-dependencies',action='store_true');a=p.parse_args()
    if (platform.system(),platform.machine())!=('Linux','x86_64'):raise ValueError('Linux amd64 only')
    signal.signal(signal.SIGALRM,hard_deadline);signal.alarm(1800)
    for path in vars(a).values():
        if isinstance(path,Path) and (not path.is_absolute() or any(c.isspace() for c in str(path))):raise ValueError('upstream Make requires absolute paths without whitespace')
    output,cache=db.paths(a.output,a.cache)
    for r in [a.source,a.spatial_proof,a.zlib_proof,a.quictls_proof,a.tools_root,a.tool_metadata,a.java_home]:
        if output==r.resolve() or output in r.resolve().parents or r.resolve() in output.parents:raise ValueError('output overlaps input')
    output.mkdir(mode=0o700);cache.mkdir(exist_ok=True)
    initial=recipe();deadline=time.monotonic()+1800;commands=[]
    providers=verify_providers(a.spatial_proof,a.zlib_proof,a.quictls_proof);tool_inventory=verify_tools(a.tools_root,a.tool_metadata)
    prefix=output/'install';prefix.mkdir()
    env,tools,jdk_inventory,debian_keyring_sha=environment(a.tools_root,a.java_home,prefix,output)
    def bound():
        size=sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink())
        if size>2*1024**3:raise ValueError('2GiB output bound exceeded')
        return size
    def run(argv,label,cwd=None,timeout=60,capture=False):
        left=deadline-time.monotonic()
        if left<=0:raise ValueError('30minute total command deadline exceeded')
        argv=list(map(str,argv));commands.append({'stage':label,'argv':argv,'timeout':min(timeout,left)})
        (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if cwd:argv=[sys.executable,str(HERE/'run-in.py'),str(cwd)]+argv
        result=runner.execute(argv,output,label,timeout=min(timeout,left),env=env,capture=capture);bound();return result
    try:
        if native.git(a.source,'rev-parse','HEAD').decode().strip()!=LOCK['revision']:raise ValueError('official source revision differs')
        # Stage exact Git blobs, never rely on sparse working-tree contents or untracked files.
        gitfiles=native.git(a.source,'ls-tree','-r','-z',LOCK['revision'],'--','commoncommo').rstrip(b'\0').split(b'\0');cc=output/'commoncommo';git_inventory={}
        for row in gitfiles:
            meta,name=row.split(b'\t');mode,kind,oid=meta.decode().split();rel=name.decode()
            if kind!='blob' or mode not in ['100644','100755']:raise ValueError('nonregular CommonCommo Git source')
            data=native.git(a.source,'cat-file','blob',oid);dest=output/native.relative(rel);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);dest.chmod(int(mode,8)&0o777)
            git_inventory[rel]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'git_blob':oid}
        license_data=native.git(a.source,'show',LOCK['revision']+':'+LOCK['license']['source'])
        if len(license_data)!=LOCK['license']['bytes'] or hashlib.sha256(license_data).hexdigest()!=LOCK['license']['sha256']:raise ValueError('official license differs')
        (prefix/'licenses').mkdir();(prefix/'licenses/ATAK-LICENSE.md').write_bytes(license_data)
        shutil.copy2(cc/'README-DISTRIBUTION.txt',prefix/'licenses/CommonCommo-NOTICES.txt')
        oldlock=json.loads((HERE.parent/'sources.lock.json').read_text())
        for patch in inputs.verify_patches(HERE.parent/'sources.lock.json',oldlock):run(['patch','--fuzz=0','--batch','--no-backup-if-mismatch','-p1','-i',patch],'source-patch-'+patch.stem,output)
        apply_jni_patch(cc,run)
        source_post=record(cc);(output/'commoncommo-sources.json').write_text(json.dumps({'git':git_inventory,'patched':source_post},indent=2)+'\n')
        # Verified leaf bytes only; merge actual includes/libs and path-specific metadata.
        leaves=[a.zlib_proof/'zlib-install',a.spatial_proof/'libiconv-install',a.spatial_proof/'libxml2-install',a.quictls_proof/'quictls-install']
        for leaf in leaves:
            for sub in ['include','lib']:
                for f in (leaf/sub).rglob('*'):
                    if not f.is_file():continue
                    if f.suffix=='.la':continue
                    dest=prefix/f.relative_to(leaf);dest.parent.mkdir(parents=True,exist_ok=True)
                    data=f.read_bytes()
                    if f.suffix=='.pc':
                        for original in leaves:data=data.replace(str(original).encode(),str(prefix).encode())
                    if dest.exists() and dest.read_bytes()!=data:raise ValueError('provider prefix collision')
                    dest.write_bytes(data)
        srcroot=output/'dependencies';srcroot.mkdir();sources={};patches={}
        for e in LOCK['archives']:
            archive=native.acquire(cache,e,a.fetch_dependencies);inv=las.unpack(archive,srcroot,e['root'],e);archive_mtimes(archive,srcroot,e);src=srcroot/e['root'];sources[e['name']]=inv
            for lic in e['licenses']:
                if native.digest(srcroot/lic['source'])!=lic['sha256']:raise ValueError('source license differs')
                shutil.copy2(srcroot/lic['source'],prefix/'licenses'/(e['name']+'-'+Path(lic['source']).name))
            if e['name'] in LOCK['official_patches']:
                pe=LOCK['official_patches'][e['name']];b=native.git(a.source,'show',LOCK['revision']+':'+pe['path'])
                if hashlib.sha256(b).hexdigest()!=pe['sha256']:raise ValueError('official patch differs')
                pp=output/(e['name']+'-official.patch');pp.write_bytes(b)
                # Upstream patch uses package-normalized root names.
                src.rename(srcroot/e['name']);src=srcroot/e['name']
                before=record(src);run(['patch','--fuzz=0','--batch','--no-backup-if-mismatch','-p0','-i',pp],e['name']+'-official-patch',srcroot)
                patches[e['name']]={'before':before,'after':record(src)}
            if e['name']=='curl':inputs.stage_dependency_patches(srcroot,HERE.parent/'sources.lock.json',oldlock,apply=True)
            epath=srcroot/(e['name'] if e['name'] in patches else e['root']);sources[e['name']]={'path':str(epath),'postimages':record(epath)}
        (output/'source-inputs.json').write_text(json.dumps(sources,indent=2)+'\n')
        freeze={'recipe':initial,'providers':providers,'tools':tool_inventory,'tool_lock':LOCK['tools'],'host_tools':tools,'jdk_inventory':jdk_inventory,'debian_keyring_sha256':debian_keyring_sha,'source':LOCK['revision'],'commoncommo_source':native.digest(output/'commoncommo-sources.json'),'dependency_sources':native.digest(output/'source-inputs.json')}
        (output/'prepared.json').write_text(json.dumps(freeze,indent=2)+'\n')
        env.update(GIT_DIR=native.git(a.source,'rev-parse','--absolute-git-dir').decode().strip(),GIT_WORK_TREE=str(a.source))
        # No synthetic upstream stamps; each configure and install really executes.
        def configure(name,flags,host=False):
            src=Path(sources[name]['path']);build=output/(name+('-host-build' if host else '-build'));build.mkdir()
            run([src/'configure','--prefix='+str(output/'host-protobuf' if host else prefix),*flags],name+('-host-configure' if host else '-configure'),build,120)
            return build
        n=configure('nghttp2',['--enable-lib-only','--disable-shared','--enable-static']);run(['make','-j1'], 'nghttp2-build',n,240);run(['make','-j1','install'],'nghttp2-install',n)
        c=configure('curl',['--with-openssl='+str(prefix),'--with-zlib='+str(prefix),'--with-nghttp2='+str(prefix),'--disable-shared','--enable-static','--disable-ldap','--disable-symbol-hiding','--without-ca-bundle','--without-ca-path','--without-libpsl','--without-libidn2','--without-brotli','--without-zstd','--without-libssh2','--without-gssapi','--without-librtmp']);run(['make','-j1'],'curl-build',c,300);run(['make','-j1','install'],'curl-install',c,90)
        n=configure('ngtcp2',['--with-openssl','--disable-shared','--enable-static','--enable-lib-only']);run(['make','-j1'],'ngtcp2-build',n,240);run(['make','-j1','install'],'ngtcp2-install',n)
        n=configure('libmicrohttpd',['--disable-shared','--enable-static','--disable-epoll','--disable-https','--disable-curl','--disable-postprocessor','--disable-dauth']);run(['make','-j1'],'microhttpd-build',n,180);run(['make','-j1','install'],'microhttpd-install',n)
        env['DIST_LANG']='cpp';host=configure('protobuf',['--disable-shared','--enable-static','--without-zlib'],True)
        run(['make','-j1','-C','src','protoc'],'protoc-build',host,600);(output/'host-protobuf/bin').mkdir(parents=True);shutil.copy2(host/'src/protoc',output/'host-protobuf/bin/protoc')
        run([output/'host-protobuf/bin/protoc','--version'],'protoc-version',capture=True)
        pb=configure('protobuf',['--enable-static','--disable-shared','--without-zlib','--with-protoc='+str(output/'host-protobuf/bin/protoc')]);run(['make','-j1','-C','src','libprotobuf-lite.la'],'protobuf-lite-build',pb,240);run(['make','-j1','-C','src','install-nobase_includeHEADERS'],'protobuf-headers',pb);shutil.copy2(pb/'src/.libs/libprotobuf-lite.a',prefix/'lib/libprotobuf-lite.a')
        core=['make','-j1','TAKTHIRDPARTYDIR='+str(prefix),'COMMO_CXXFLAGS=-O2 -fPIC','CXX='+tools['g++']['path'],'AR='+tools['ar']['path'],'RANLIB='+tools['ranlib']['path'],'PROTOC='+str(output/'host-protobuf/bin/protoc')]
        run(core+['libcommoncommo.a'],'commoncommo-core',cc/'core/impl',600);shutil.copy2(cc/'core/impl/libcommoncommo.a',prefix/'lib/libcommoncommo.a')
        ant_config_guard();run(['ant','-Dnative-init=internal','jar'],'commoncommo-java',cc/'jni',90)
        exportmap=output/'jni-exports.map';exportmap.write_text('{ global: JNI_OnLoad; JNI_OnUnload; Java_com_atakmap_commoncommo_*; local: *; };\n')
        link='-shared -Wl,--hash-style=both -Wl,--no-undefined -Wl,--exclude-libs,ALL -Wl,--version-script='+str(exportmap)
        ant_config_guard();run(core+['TARGET=linux-amd64','LINK_FLAGS='+link],'commoncommo-jni',cc/'jni/native',180)
        shutil.copy2(cc/'jni/native/libcommoncommojni.so',prefix/'lib/libcommoncommojni.so');(prefix/'java').mkdir();shutil.copy2(cc/'jni/jcommoncommo.jar',prefix/'java/jcommoncommo.jar')
        symbolset=set()
        for name in ['libssl.a','libcrypto.a']:
            nm=run(['nm','-g','--defined-only',prefix/'lib'/name],'symbols-'+name,capture=True).decode()
            symbolset|={x.split()[-1] for x in nm.splitlines() if len(x.split())>=3 and x.split()[-2].upper()!='U'}
        dyn=run(['readelf','--dyn-syms','--wide',prefix/'lib/libcommoncommojni.so'],'jni-dynsym',capture=True).decode();public=exports(dyn,symbolset)
        dynamic=run(['readelf','-d',prefix/'lib/libcommoncommojni.so'],'jni-dynamic',capture=True).decode()
        if 'TEXTREL' in dynamic or any(n in dynamic for n in ['libssl.so','libcrypto.so','libxml2.so','libcurl.so','libngtcp2.so']):raise ValueError('provider fallback/textrel')
        closure=run(['ldd',prefix/'lib/libcommoncommojni.so'],'jni-runtime',capture=True).decode();runtime=runtime_closure(closure)
        for f in (prefix/'lib').glob('*.a'):db.archive_objects(f)
        classes=output/'smoke-classes';classes.mkdir();run([a.java_home/'bin/javac','--release','17','-cp',prefix/'java/jcommoncommo.jar','-d',classes,*[smoke_path(n) for n in (*SMOKES,'CommonCommoThrowingLogger')]],'compile-smokes',timeout=60)
        outcomes={}
        for n in SMOKES[:3]:outcomes[n]=run([a.java_home/'bin/java','-Xcheck:jni','-Djava.library.path='+str(prefix/'lib'),'-cp',str(prefix/'java/jcommoncommo.jar')+':'+str(classes),n],n,timeout=90,capture=True).decode()
        env['TAKX_TLS_PASSWORD']=secrets.token_hex(24);credentials=output/'private-tls';credentials.mkdir(mode=0o700)
        # Preserve genuine shared fixture semantics; route every child through this profile's bounded runner.
        old_tls_run=tls.run;credential_counter=[0]
        def credential_run(label,args,env=None,timeout=30):
            credential_counter[0]+=1
            return run(args,'tls-credential-'+str(credential_counter[0]),timeout=timeout,capture=True).decode()
        tls.run=credential_run
        try:tls.credentials(credentials,env)
        finally:tls.run=old_tls_run
        outcomes['CommonCommoTlsSmoke']=run([a.java_home/'bin/java','-Xcheck:jni','-Djava.library.path='+str(prefix/'lib'),'-cp',str(prefix/'java/jcommoncommo.jar')+':'+str(classes),'CommonCommoTlsSmoke',credentials],'CommonCommoTlsSmoke',timeout=120,capture=True).decode();shutil.rmtree(credentials)
        outcomes['CommonCommoThrowingLogger']=run([a.java_home/'bin/java','-Xcheck:jni','-Djava.library.path='+str(prefix/'lib'),'-cp',str(prefix/'java/jcommoncommo.jar')+':'+str(classes),'CommonCommoThrowingLogger'],'CommonCommoThrowingLogger',timeout=90,capture=True).decode()
        if any('WARNING in native method' in s or 'WARNING: JNI' in s or 'FATAL ERROR' in s for s in outcomes.values()):raise ValueError('JNI checker warning/fatal')
        for e in sources.values():check_record(Path(e['path']),e['postimages'])
        check_record(cc,source_post)
        if native.digest(Path('/usr/share/keyrings/debian-archive-keyring.gpg'))!=debian_keyring_sha:raise ValueError('Debian bootstrap keyring changed')
        if any(native.digest(Path(t['path']))!=t['sha256'] for t in tools.values()) or native.inventory(a.java_home)!=jdk_inventory:raise ValueError('host compiler/JDK identity changed')
        ant_config_guard()
        if initial!=recipe() or providers!=verify_providers(a.spatial_proof,a.zlib_proof,a.quictls_proof) or tool_inventory!=verify_tools(a.tools_root,a.tool_metadata):raise ValueError('input changed')
        receipt={'profile':'public-commoncommo-native-jni','version':LOCK['version'],'project_variant':'owned JNI enum/load and best-effort logger exception handling','jni_patch':LOCK['jni_patch'],'throwing_logger_exceptions_isolated':True,'all_callback_exception_paths':False,'fresh_dependency_build':True,'fresh_core_build':True,'fresh_jni_build':True,'source_revision':LOCK['revision'],'recipe':initial,'providers':providers,'archives':LOCK['archives'],'license':LOCK['license'],'official_patches':LOCK['official_patches'],'installed':native.inventory(prefix),'runtime_closure':runtime,'host_tools':tools,'jdk_inventory':jdk_inventory,'debian_keyring_sha256':debian_keyring_sha,'generator':{'version':run([output/'host-protobuf/bin/protoc','--version'],'final-protoc-version',capture=True).decode().strip(),'sha256':native.digest(output/'host-protobuf/bin/protoc')},'generated_protobuf':{str(f.relative_to(cc)):native.digest(f) for f in (cc/'core/impl/protobuf').glob('*.pb.*') if f.suffix in ['.cc','.h']},'exports':public,'hidden_crypto_symbols':len(symbolset),'outcomes':outcomes,'source_inputs_sha256':native.digest(output/'source-inputs.json'),'prepared_sha256':native.digest(output/'prepared.json'),'disk_bytes':bound(),'single_job':True,'budget_seconds':1800,'actual_commoncommo_jni':True,'quic_compiled':True,'quic_peer_handshake':False,'takserver_interoperability':False,'full_sdk':False,'takx_client':False}
        signal.alarm(0)
        (output/'complete.json').write_text(json.dumps(receipt,indent=2)+'\n');print('Complete genuine CommonCommo JNI source profile controls passed')
    except Exception:
        (output/'failed.json').write_text(json.dumps({'status':'stopped; no success inferred','last_stage':commands[-1]['stage'] if commands else 'preflight'})+'\n');raise
if __name__=='__main__':main()
