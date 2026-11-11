# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Actual archive-union, complete dynsym and real-JVM acceptance controls."""
import json
from pathlib import Path
import re
import providers as p
HERE=Path(__file__).resolve().parent
SYSTEM=re.compile(r'^(lib(c|m|dl|pthread|rt|stdc\+\+|gcc_s)\.so(?:\..*)?|ld-linux-x86-64\.so\.2)$')
def symbols(text):
    exports=set();imports=set();all_names=set()
    for line in text.splitlines():
        f=line.split()
        if len(f)<8 or not f[0].endswith(':') or not f[0][:-1].isdigit():continue
        name=f[7].split('@')[0];all_names.add(name)
        if f[6]=='UND':imports.add(name)
        elif f[4]!='LOCAL':exports.add(name)
    return exports,imports,all_names

def elf_audit(output,roots,run):
    required={'sqlite3_config','sqlite3_errstr'}
    archives={name:roots['sqlcipher']/'openssl-install/lib'/('lib'+name+'.a') for name in ('ssl','crypto')}
    archives['sqlite']=roots['sqlcipher']/'sqlcipher-install/lib/libsqlite3.a';archives['expat']=roots['kml']/'expat-install/lib/libexpat.a'
    definitions={};archive_records={}
    for name,path in archives.items():
        raw=run(['nm','--defined-only',path],'archive-'+name,30).decode();names=set()
        for line in raw.splitlines():
            f=line.split()
            if len(f)>=3 and f[-2] not in ('U','u'):names.add(f[-1])
        if not names:raise ValueError('empty real backend archive')
        definitions[name]=names;archive_records[name]={'sha256':p.digest(path),'definitions':len(names)}
    result={}
    for name,target,project_needed in [('Core','kernel-cpp/libtakengine.so',{'libGLESv2.so.2','libgdal.so','libassimp.so.4','liblas_c.so.3'}),('JNI','kernel-jni/libtakenginejni.so',{'libtakengine.so','libGLESv2.so.2','libgdal.so'})]:
        path=output/'build'/target;exports,imports,all_names=symbols(run(['readelf','--dyn-syms','--wide',path],name+'-dynsym',30).decode())
        for family in ('ssl','crypto','expat'):
            if all_names&definitions[family]:raise ValueError('backend escaped full dynsym: '+family)
        sql_exports=exports&definitions['sqlite'];sql_imports=imports&definitions['sqlite']
        if (name=='Core' and (sql_exports!=required or sql_imports)) or (name=='JNI' and (sql_exports or sql_imports!=required)):raise ValueError('Core shared SQLite owner/JNI interface differs')
        if name=='JNI':
            body=run(['nm','--defined-only',path],'JNI-no-sqlite-body',30).decode()
            if any(line.split() and line.split()[-1].startswith(('sqlite3_','sqlcipher')) for line in body.splitlines()):raise ValueError('second SQLite implementation in JNI')
        dynamic=run(['readelf','-d',path],name+'-dynamic',30).decode();needed=set(re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic))
        if 'TEXTREL' in dynamic or not project_needed<=needed or any(n not in project_needed and not SYSTEM.fullmatch(n) for n in needed):raise ValueError('unreviewed project/system ELF dependency or TEXTREL')
        result[name]={'relative_path':'build/'+target,'sha256':p.digest(path),'bytes':path.stat().st_size,'exported_dynamic_symbols':len(exports),'sqlcipher_exports':sorted(sql_exports),'sqlcipher_imports':sorted(sql_imports),'needed':sorted(needed)}
    return {'archives':archive_records,'elfs':result,'hidden_crypto_ssl_expat':True,'shared_sqlcipher_owner':True,'second_jni_sqlite_body':False}

def add_elf(allowed,path,entry):
    path=Path(path).resolve();expected=entry['sha256'] if isinstance(entry,dict) else entry
    if p.digest(path)!=expected:raise ValueError('prevalidated ELF changed')
    with path.open('rb') as stream:
        if stream.read(4)==b'\x7fELF':allowed[str(path)]=expected

def runtime_allowlist(roots,jdk_runtime,new_elfs):
    allowed=dict(jdk_runtime['bound_files']);p.bound_files(allowed)
    for family,root in roots.items():
        if family=='kernel_java':continue
        record=p.load(root/'complete.json')
        if family=='gdal_jni':
            for name,entry in record['products'].items():add_elf(allowed,root/'lib'/name,entry)
        else:
            installed=record.get('installed',{})
            groups=[(root/'install',installed)]
            if family=='sqlcipher':groups=[(root/(n+'-install'),v) for n,v in installed.items()]
            elif family=='spatial':groups=[(root/(n+'-install'),v) for n,v in installed.items()]
            for prefix,entries in groups:
                items=((e['path'],e) for e in entries) if isinstance(entries,list) else entries.items()
                for name,entry in items:add_elf(allowed,prefix/name,entry)
        if family=='gles':
            for name,entry in record['runtime_providers'].items():add_elf(allowed,name,entry)
            for name,entry in record['host_inputs'].items():add_elf(allowed,name,entry)
    for path in new_elfs:add_elf(allowed,path,p.digest(path))
    return allowed

def check_mapped_provider(path,sha,allowed,gles_prefix):
    path=Path(path).resolve()
    if p.digest(path)!=sha or allowed.get(str(path))!=sha:raise ValueError('unmanifested/changed mapped provider: '+str(path))
    if path.name.startswith(('libcrypto.so','libssl.so','libsqlite3.so')):raise ValueError('shared crypto/SQLite backend mapped')
    if path.name in ('libGLdispatch.so.0.0.0','libGLESv2.so.2.1.0') and not path.is_relative_to(Path(gles_prefix).resolve()):raise ValueError('host graphics dispatch/GLES substitution')
    return path

def strict_jni_diagnostics(text):
    return [line for line in text.splitlines() if any(marker in line for marker in ('WARNING in native method','WARNING: JNI','FATAL ERROR'))]

def runtime(output,roots,java_home,run,env,jdk_runtime,actual_elfs=None):
    java_input=p.load(roots['kernel_java']/'inputs.json');classpath=[roots['kernel_java']/'classes']+[Path(e['path']) for e in java_input['classpath']]
    classes=output/'runtime-classes';classes.mkdir()
    files=[HERE/n for n in ['KernelRuntimeSmoke.java','NativeDatabaseCandidate.java','KernelThrowingLoggerCandidate.java']]
    run([java_home/'bin/javac','--release','17','-proc:none','-cp',__import__('os').pathsep.join(map(str,classpath)),'-d',classes,*files],'runtime-javac',120)
    current_elfs=actual_elfs or {'Core':output/'build/kernel-cpp/libtakengine.so','JNI':output/'build/kernel-jni/libtakenginejni.so'}
    allowed=runtime_allowlist(roots,jdk_runtime,list(current_elfs.values()))
    (output/'runtime-allowed-elfs.json').write_text(json.dumps(allowed,indent=2)+'\n')
    loads=[roots['gles']/'install/lib/libGLdispatch.so.0.0.0',roots['gles']/'install/lib/libGLESv2.so.2.1.0',roots['las']/'install/lib/liblas.so.2.4.0',roots['gdal_jni']/'lib/libgdalalljni.so',current_elfs['Core'],current_elfs['JNI']]
    manifest=output/'runtime-native.sha256';manifest.write_text(''.join(p.digest(p.regular(v))+' '+str(v.resolve())+'\n' for v in loads))
    bound={str(v.resolve()):p.digest(v) for v in loads};results={}
    for phase,tokens in [('basic',['PASS_KERNEL_JNI_MATRIX_POINT_WKB_NATIVE_PROJECTION']),('database',['PASS_PREPARED_NATIVE_DATABASE2_ENCRYPTED_OPEN_REOPEN_WRONG_KEY_CONTROL','PASS_REAL_GDAL_MEM_EXACT_WRITE_READ']),('logger',['PASS_REAL_THROWING_LOGGER_BASELINE_REJECTION_MATCH_AND_CORRECT_KEY_RECOVERY'])]:
        app=output/'runtime'/phase;app.mkdir(parents=True);(app/'home').mkdir();(app/'data').mkdir()
        command=[java_home/'bin/java','-Xcheck:jni','-Xmx256m','-XX:ActiveProcessorCount=2','-Djava.awt.headless=true','-Duser.home='+str(app/'home'),'-Djava.io.tmpdir='+str(app),'-DTAK_APP_DATA_PATH='+str(app/'data'),'-cp',__import__('os').pathsep.join(map(str,[classes,*classpath])),'KernelRuntimeSmoke',manifest,phase]
        text=run(command,'runtime-'+phase,120).decode()
        if any(t not in text for t in tokens) or strict_jni_diagnostics(text) or 'UnsatisfiedLinkError' in text:raise ValueError('strict actual JNI control failed: '+phase)
        if phase=='logger':
            match=re.search(r'LOGGER_CALLBACKS=(\d+) BASELINE_WRONG_KEY=(\S+) LISTENER_WRONG_KEY=(\S+)',text)
            if not match or int(match[1])<1 or match[2]!=match[3]:raise ValueError('actual throwing logger boundary/baseline classification not preserved')
        mapped={}
        for sha,name in re.findall(r'^ELF ([0-9a-f]{64}) (.+)$',text,re.M):
            path=check_mapped_provider(name,sha,allowed,roots['gles']/'install')
            mapped[str(path)]=sha
        if any(mapped.get(path)!=sha for path,sha in bound.items()):raise ValueError('requested real native provider not mapped')
        results[phase]={'required_controls':tokens,'strict_jni_warnings':0,'mapped_elfs':mapped}
    p.bound_files(allowed)
    return {'mode':'explicit-verified-native-loads','phases':results,'stock_engine_resource_loader_acceptance':False,'renderer_acceptance':False,'commoncommo_acceptance':False,'takx_acceptance':False}
