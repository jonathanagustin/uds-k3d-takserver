#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Fresh project-variant JNI over an audited, unchanged local dependency/core stage."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import time
HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('commo_observed_stage',HERE/'stage.py')
S=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(S)
B=S.B

def separated(output,roots):
    output=B.native.external(output)
    if output.exists():raise ValueError('fresh JNI output required')
    for root in roots:
        root=root.resolve()
        if output==root or output in root.parents or root in output.parents:raise ValueError('JNI output overlaps input')
    return output

def hard_deadline(signum,frame):
    raise TimeoutError('10minute JNI deadline exceeded')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['stage','stage-audit','output','tools-root','tool-metadata','java-home','spatial-proof','zlib-proof','quictls-proof']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--stage-audit-sha256',required=True);a=p.parse_args()
    for value in vars(a).values():
        if isinstance(value,Path) and (not value.is_absolute() or any(c.isspace() for c in str(value))):raise ValueError('absolute paths without whitespace required')
    signal.signal(signal.SIGALRM,hard_deadline);signal.alarm(600)
    output=separated(a.output,[a.stage,a.stage_audit,a.tools_root,a.tool_metadata,a.java_home,a.spatial_proof,a.zlib_proof,a.quictls_proof]);output.mkdir(mode=0o700)
    initial=B.recipe();deadline=time.monotonic()+600;commands=[]
    try:
        stage=S.verify(a.stage,a.stage_audit,a.stage_audit_sha256)
        prefix=a.stage/'install';product=output/'install';(product/'lib').mkdir(parents=True);(product/'java').mkdir()
        env,tools,jdk,keyring=B.environment(a.tools_root,a.java_home,prefix,output)
        if tools!=stage['host_tools'] or jdk!=stage['jdk_inventory']:raise ValueError('JNI consumer tool/JDK identity differs from audited stage')
        original_prepared=S.load(a.stage/'prepared.json')
        if B.verify_tools(a.tools_root,a.tool_metadata)!=original_prepared['tools'] or B.verify_providers(a.spatial_proof,a.zlib_proof,a.quictls_proof)!=original_prepared['providers']:raise ValueError('accepted provider/tool stage differs')
        def run(argv,label,cwd=None,timeout=60,capture=False):
            left=deadline-time.monotonic()
            if left<=0:raise ValueError('10minute JNI command budget exceeded')
            argv=list(map(str,argv));commands.append({'stage':label,'argv':argv,'timeout':min(left,timeout)})
            (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
            if cwd:argv=[tools['python']['path'],str(HERE/'run-in.py'),str(cwd)]+argv
            return B.runner.execute(argv,output,label,min(left,timeout),env,capture)
        cc=output/'commoncommo';original=S.load(a.stage/'commoncommo-sources.json')['patched']
        # Real pinned source bytes only, not old objects/class files or a patched old prefix.
        for name,entry in original.items():
            src=a.stage/'commoncommo'/B.native.relative(name);dest=cc/B.native.relative(name);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
            if B.native.digest(dest)!=entry['sha256']:raise ValueError('copied CommonCommo source differs')
        shutil.copytree(a.stage/'commoncommo/jni/native/headers',cc/'jni/native/headers',copy_function=shutil.copy2)
        if B.native.inventory(cc/'jni/native/headers')!=stage['native_headers']:raise ValueError('original real JNI headers differ')
        B.apply_jni_patch(cc,run);sources=B.record(cc)
        jar=prefix/'java/jcommoncommo.jar';shutil.copy2(jar,product/'java/jcommoncommo.jar')
        if B.native.digest(product/'java/jcommoncommo.jar')!=stage['jar_sha256']:raise ValueError('original real JAR differs')
        freeze={'new_recipe':initial,'patch':B.LOCK['jni_patch'],'source_postimages':sources,'stage_manifest_sha256':a.stage_audit_sha256,
            'original_producer':stage['producer'],'original_prepared_sha256':stage['prepared_sha256'],'dependency_prefix':str(prefix),
            'original_inventory_sha256':hashlib.sha256(json.dumps(stage['inventory'],sort_keys=True).encode()).hexdigest(),
            'native_headers':stage['native_headers'],'jar_sha256':stage['jar_sha256'],'tools':tools,'jdk_inventory':jdk,'debian_keyring_sha256':keyring,
            'fresh_dependency_build':False,'fresh_core_build':False,'fresh_jni_build':True}
        (output/'prepared.json').write_text(json.dumps(freeze,indent=2)+'\n')
        exportmap=output/'jni-exports.map';exportmap.write_text('{ global: JNI_OnLoad; JNI_OnUnload; Java_com_atakmap_commoncommo_*; local: *; };\n')
        link='-shared -Wl,--hash-style=both -Wl,--no-undefined -Wl,--exclude-libs,ALL -Wl,--version-script='+str(exportmap)
        B.ant_config_guard()
        run(['make','-j1','TAKTHIRDPARTYDIR='+str(prefix),'COMMO_CXXFLAGS=-O2 -fPIC','CXX='+tools['g++']['path'],'TARGET=linux-amd64','LINK_FLAGS='+link],
            'fresh-commoncommo-jni',cc/'jni/native',180)
        library=product/'lib/libcommoncommojni.so';shutil.copy2(cc/'jni/native/libcommoncommojni.so',library)
        symbols=set()
        for n in ['libssl.a','libcrypto.a']:
            text=run([tools['nm']['path'],'-g','--defined-only',prefix/'lib'/n],'symbols-'+n,capture=True).decode()
            symbols|={line.split()[-1] for line in text.splitlines() if len(line.split())>=3 and line.split()[-2].upper()!='U'}
        public=B.exports(run([tools['readelf']['path'],'--dyn-syms','--wide',library],'new-jni-dynsym',capture=True).decode(),symbols)
        dynamic=run([tools['readelf']['path'],'-d',library],'new-jni-dynamic',capture=True).decode()
        if 'TEXTREL' in dynamic:raise ValueError('new JNI text relocations')
        runtime=B.runtime_closure(run([tools['ldd']['path'],library],'new-jni-runtime',capture=True).decode())
        classes=output/'smoke-classes';classes.mkdir()
        run([tools['javac']['path'],'--release','17','-cp',jar,'-d',classes,*[B.smoke_path(n) for n in (*B.SMOKES,'CommonCommoThrowingLogger')]],'compile-real-smokes',timeout=60)
        outcomes={}
        def smoke(name,extra=(),timeout=90):
            outcomes[name]=run([tools['java']['path'],'-Xcheck:jni','-Djava.library.path='+str(product/'lib'),'-cp',str(jar)+':'+str(classes),name,*extra],name,timeout=timeout,capture=True).decode()
        for n in B.SMOKES[:3]:smoke(n)
        credentials=output/'private-tls';credentials.mkdir(mode=0o700);env['TAKX_TLS_PASSWORD']=secrets.token_hex(24)
        old=B.tls.run;counter=[0]
        def credential_run(label,args,env=None,timeout=30):
            counter[0]+=1;return run(args,'tls-credential-'+str(counter[0]),timeout=timeout,capture=True).decode()
        B.tls.run=credential_run
        try:B.tls.credentials(credentials,env)
        finally:B.tls.run=old
        smoke('CommonCommoTlsSmoke',[credentials],120);shutil.rmtree(credentials)
        smoke('CommonCommoThrowingLogger')
        if any('WARNING in native method' in t or 'WARNING: JNI' in t or 'FATAL ERROR' in t for t in outcomes.values()):raise ValueError('strict JNI checker warnings/fatal retained; not accepted')
        B.check_record(cc,sources)
        if B.native.inventory(cc/'jni/native/headers')!=stage['native_headers'] or B.native.digest(jar)!=stage['jar_sha256']:raise ValueError('unchanged original JAR/headers changed')
        S.verify(a.stage,a.stage_audit,a.stage_audit_sha256)
        if initial!=B.recipe() or B.native.inventory(a.java_home)!=jdk or any(B.native.digest(Path(t['path']))!=t['sha256'] for t in tools.values()):raise ValueError('consumer recipe/tools changed')
        B.ant_config_guard();B.las.verify_runtime(runtime)
        receipt={'schema':1,'profile':'commoncommo-owned-jni-exception-variant','version':'1.17.2','project_variant':B.LOCK['jni_patch']['scope'],
            'recipe':initial,'jni_patch':B.LOCK['jni_patch'],'stage_manifest_sha256':a.stage_audit_sha256,'original_producer':stage['producer'],
            'original_prepared_sha256':stage['prepared_sha256'],'original_dependency_prefix':str(prefix),'original_stage_accepted_jni':False,
            'fresh_dependency_build':False,'fresh_core_build':False,'fresh_jni_build':True,'unchanged_jar_sha256':stage['jar_sha256'],
            'unchanged_native_headers':stage['native_headers'],'installed':B.native.inventory(product),'source_postimages':sources,
            'tools':tools,'runtime_closure':runtime,'hidden_crypto_symbol_count':len(symbols),'exports':public,'outcomes':outcomes,
            'strict_jni_checker_warnings':0,'throwing_logger_exception_control':True,'all_callback_exception_paths':False,
            'quic_compiled_in_original_core':True,'quic_peer_handshake':False,'takserver_interoperability':False,'full_sdk':False,'takx_client':False,
            'command_budget_s':600,'single_job':True,'disk_bytes':B.runner.disk_bytes(output)}
        signal.alarm(0);(output/'complete.json').write_text(json.dumps(receipt,indent=2)+'\n');print('Fresh real JNI variant and throwing-logger/transport controls passed; original dependencies/core reused')
    except Exception:
        (output/'failed.json').write_text(json.dumps({'status':'stopped; no JNI acceptance','last_stage':commands[-1]['stage'] if commands else 'stage-verification'})+'\n');raise
if __name__=='__main__':main()
