#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit stock SDK/CommonCommo co-load controls; no native build or download."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import selectors
import shutil
import signal
import subprocess
import sys
import time
import zipfile

HERE=Path(__file__).resolve().parent
CAP=512*1024**2
LOG_CAP=1024**2
FILE_CAP=128*1024**2
RESERVE=2*1024**2
FLOOR=2*1024**3


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def require(value,message):
    if not value:raise ValueError(message)


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):result.update(block)
    return result.hexdigest()


def environment():
    blocked=('LD_','DYLD_','JAVA_','_JAVA_','JDK_','GDAL_','PROJ_','OPENSSL_')
    env={key:value for key,value in os.environ.items() if not key.startswith(blocked)
         and key not in ('CLASSPATH','BASH_ENV','ENV','PYTHONPATH')}
    env.update(OPENSSL_CONF='/dev/null',OPENSSL_MODULES='/nonexistent-owned-openssl-providers',LC_ALL='C')
    return env


def disjoint(output,roots):
    output=Path(output).absolute()
    require(not output.exists() and not any(p.is_symlink() for p in (output,*output.parents)), 'fresh canonical output required')
    require(output.resolve()==output,'canonical output required')
    for root in roots:
        root=Path(root).resolve()
        require(output!=root and root not in output.parents and output not in root.parents,'output overlaps input')
    return output


def allocated(root):
    result=0
    for path in [root,*root.rglob('*')]:
        try:result+=path.lstat().st_blocks*512
        except FileNotFoundError:pass
    return result


def mapped(text,expected):
    actual={}
    for line in text.splitlines():
        if not line.startswith('JOINED_ELF '):continue
        fields=line.split(' ',2)
        require(len(fields)==3,'invalid ELF map record')
        sha,name=fields[1:];path=Path(name)
        require(path.is_absolute() and path.resolve()==path and not path.is_symlink() and path.is_file(), 'noncanonical mapped ELF')
        with path.open('rb') as stream:
            require(stream.read(4)==b'\x7fELF','mapped file is not ELF')
        require(name not in actual and expected.get(name)==sha and digest(path)==sha, 'unexpected/changed/duplicate ELF provider')
        require(not path.name.startswith(('libcrypto.so','libssl.so','libsqlite3.so')),'shared crypto/SQLite fallback')
        actual[name]=sha
    require(actual,'missing actual ELF maps')
    return actual


def native_capacity(jar,names):
    total=0
    with zipfile.ZipFile(jar) as archive:
        for name in names:
            files=[item for item in archive.infolist() if Path(item.filename).name==name]
            require(len(files)==1 and 0<files[0].file_size<=FILE_CAP,'native resource exceeds data-file limit')
            total+=((files[0].file_size+4095)//4096)*4096
    required=2*total+RESERVE+8*1024**2+3*LOG_CAP
    require(required<=CAP,'two native caches exceed output budget')
    return required


def child_limits(seconds):
    resource.setrlimit(resource.RLIMIT_FSIZE,(FILE_CAP,FILE_CAP))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))


def execute(vector,label,seconds,out,deadline,budget,commands):
    budget();log=out/(label+'.log');timeout=min(seconds,deadline-time.monotonic())
    require(timeout>0,'300-second total deadline')
    item={'label':label,'argv':list(map(str,vector)),'status':'running'};commands.append(item)
    (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    child=None;selector=selectors.DefaultSelector();size=0
    try:
        with log.open('xb') as stream:
            child=subprocess.Popen(item['argv'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                env=environment(),cwd=out,start_new_session=True,preexec_fn=lambda:child_limits(seconds))
            os.set_blocking(child.stdout.fileno(),False);selector.register(child.stdout,selectors.EVENT_READ)
            end=time.monotonic()+timeout
            while child.poll() is None or selector.get_map():
                require(time.monotonic()<end,'owned command deadline');budget()
                for key,_events in selector.select(.05):
                    try:block=os.read(key.fileobj.fileno(),65536)
                    except BlockingIOError:continue
                    if not block:selector.unregister(key.fileobj);continue
                    require(size+len(block)<=LOG_CAP,'complete log cap')
                    stream.write(block);stream.flush();size+=len(block)
            require(child.returncode==0,'control failed: '+label)
            item['status']='success'
    finally:
        if child is not None:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait();child.stdout.close();item['exit']=child.returncode
        selector.close()
        if log.exists():item['log_sha256']=digest(log)
        if item['status']=='running':item['status']='failed'
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
    budget();return log.read_text()


def run(args):
    fresh=module('joined_fresh_producer',HERE.parent/'cot-conformance/fresh_producer.py')
    formats=module('joined_sdk_inspector',HERE.parent/'kernel-regressions/build.py')
    sdk_builder=module('joined_sdk_builder',HERE.parent/'sdk-package/build.py')
    diagnostics=module('joined_jni_diagnostics',HERE.parent/'jni_diagnostics.py')
    sdk=fresh.canonical(args.sdk_proof,True);commo=fresh.canonical(args.commoncommo_proof,True)
    java=fresh.canonical(args.java_home,True);bindings=fresh.canonical(args.commoncommo_bindings)
    roots=[sdk,commo,java,bindings,HERE.parent,*fresh.bindings(bindings).values()]
    out=disjoint(args.output,roots)
    require(shutil.disk_usage(out.parent).free>=FLOOR+CAP,'full512MiB reservation above2GiBfloor required')
    out.mkdir(mode=0o700);deadline=time.monotonic()+300;commands=[]
    def budget():
        require(allocated(out)+RESERVE<=CAP,'inclusive512MiB output cap')
        require(shutil.disk_usage(out).free>=FLOOR,'2GiB physical free floor')
    def command(vector,label,seconds):
        return execute(vector,label,seconds,out,deadline,budget,commands)
    record=None
    try:
        receipt,jar,dependencies,hosts=formats.inspect(sdk,args.sdk_sha256)
        require(receipt['recipe']==sdk_builder.recipe(),'current stock SDK producer recipe required')
        require(receipt['manifest']['runtime_resources']['source_inventory']==json.loads((HERE.parent/'sdk-package/runtime-resources.lock.json').read_text())['files'],'complete resource source identity required')
        common,binding=fresh.verify(bindings,commo/'install',commo/'complete.json',java,args.commoncommo_sha256,out)
        for name in ('java','javac'):
            require(Path(receipt['jdk_tools'][name]['path']).resolve()==(java/'bin'/name).resolve(),'SDK/Common selected JDK differs')
        source_paths=sdk_builder.runtime_control_sources(False)+[HERE.parent/(name+'.java') for name in
            ('CommonCommoSmoke','CommonCommoSignalSmoke','CommonCommoRoutingSmoke')]+[
            HERE.parent/'native-commoncommo/CommonCommoThrowingLogger.java',HERE/'JoinedSdkCommo.java']
        own=[Path(__file__),HERE.parent/'cot-conformance/fresh_producer.py',HERE.parent/'kernel-regressions/build.py',HERE.parent/'jni_diagnostics.py']
        inputs={str(path):digest(path) for path in [*source_paths,*own,bindings,sdk/'complete.json',commo/'complete.json']}
        record={'schema':1,'scope':'stock public Kernel8.30.5/CommonCommo1.17.2 co-load only','inputs':inputs,
                'sdk_receipt_sha256':args.sdk_sha256,'commoncommo_binding':binding,'commands':commands,
                'native_compilation':False,'full_sdk':False,'renderer':False,'takx_client':False,
                'takserver_interoperability':False,'tls_peer_under_co_load':False,'quic_peer':False}
        if args.phase=='inspect':
            (out/'verified-inputs.json').write_text(json.dumps(record,indent=2)+'\n');print('Verified inputs; no compiler/JVM/native loading.');return
        classes=out/'classes';classes.mkdir();common_jar=commo/'install/java/jcommoncommo.jar'
        cp=[jar,*dependencies,common_jar]
        command([java/'bin/javac','-J-Xmx256m','-J-XX:ActiveProcessorCount=2','--release','17','-proc:none','-implicit:none','-sourcepath','',
                 '-cp',os.pathsep.join(map(str,cp)),'-d',classes,*source_paths],'compile',60)
        for name,item in receipt['owned_runtime_classes'].items():
            require(digest(classes/name)==item['sha256'],'stock control class bytes differ')
        native=receipt['manifest']['native_resources'];require(len(native)==9,'exact stock native group required')
        record['native_capacity_reservation']=native_capacity(jar,native)
        manifest=out/'native-resources.sha256';manifest.write_text(''.join(sha+' '+name+'\n' for name,sha in native.items()))
        resource_file=out/'runtime-resources.sha256';resource_file.write_text(''.join(
            item.get('lfs_payload',item)['sha256']+' '+item['kind']+' '+item['destination']+'\n'
            for item in receipt['manifest']['runtime_resources']['source_inventory']))
        for name,sha in common['runtime_closure'].items():
            require(name not in hosts or hosts[name]==sha,'conflicting host provider');hosts[name]=sha
        for path in (java/'lib').rglob('*.so'):
            canonical=path.resolve();sha=digest(canonical)
            require(str(canonical) not in hosts or hosts[str(canonical)]==sha,'conflicting qualified JDK provider')
            hosts[str(canonical)]=sha
        record['trusted_host_runtime_inputs']=dict(hosts)
        common_jni=(commo/'install/lib/libcommoncommojni.so').resolve();common_hash=digest(common_jni)
        outcomes={}
        for order in ('sdk-first','common-first'):
            app=out/order;app.mkdir(mode=0o700)
            for name in ('tmp','home','data'):(app/name).mkdir(mode=0o700)
            library=app/'tmp/takkernel/engine'/hashlib.md5(jar.read_bytes()).hexdigest()/'lib/linux64'
            argv=[java/'bin/java','-Xcheck:jni','-Xmx256m','-XX:MaxMetaspaceSize=128m','-XX:ActiveProcessorCount=2',
                  '-Djava.awt.headless=true','-XX:ErrorFile='+str(app/'hs_err_%p.log'),'-Djava.io.tmpdir='+str(app/'tmp'),'-Duser.home='+str(app/'home'),
                  '-DTAK_APP_DATA_PATH='+str(app/'data'),'-Djava.library.path='+str(library)+os.pathsep+str(commo/'install/lib'),
                  '-cp',os.pathsep.join(map(str,[classes,*cp])),'JoinedSdkCommo',order,jar,common_jar,manifest,resource_file]
            text=command(argv,order,90)
            require(not diagnostics.strict_jni_failures(text),'strict JNI/startup diagnostics rejected')
            required=['PASS_JOINED_FIRST_GROUP_'+('SDK' if order=='sdk-first' else 'COMMONCOMMO'),
                      'PASS_JOINED_COMMON_CONSTRUCTOR_PKCS12_SIGNAL_ROUTING_LOGGER',
                      'PASS_JOINED_KERNEL_CONTROLS_AFTER_COMMON','PASS_JOINED_STOCK_SDK_COMMONCOMMO '+order,
                      'PASS_STOCK_ENGINE_RESOURCE_LOADER_SCOPED_COMPONENT']
            require(all(marker in text for marker in required),'actual joined control marker missing')
            expected={**hosts,str(common_jni):common_hash,**{str(library/name):sha for name,sha in native.items()}}
            actual=mapped(text,expected)
            require(all(actual.get(str(library/name))==sha for name,sha in native.items()) and
                    actual.get(str(common_jni))==common_hash,'complete co-loaded production groups required')
            outcomes[order]={'mapped_elfs':actual,'strict_jni_warnings':0,'required_controls':required}
        _common,again=fresh.verify(bindings,commo/'install',commo/'complete.json',java,args.commoncommo_sha256,out)
        formats.inspect(sdk,args.sdk_sha256);require(all(digest(path)==sha for path,sha in hosts.items()),'qualified host provider changed');require(again==binding and receipt['recipe']==sdk_builder.recipe(),'producer binding changed')
        require(all(digest(path)==sha for path,sha in inputs.items()),'consumed source/input changed')
        record.update(stock_sdk_commoncommo_co_load_controls_passed=True,outcomes=outcomes,
                      classes={str(path.relative_to(classes)):digest(path) for path in classes.rglob('*.class')})
        budget();(out/'complete.json').write_text(json.dumps(record,indent=2)+'\n');budget()
        print('Both stock SDK/CommonCommo load orders and scoped controls passed; no client/server/renderer claim.')
    except BaseException as error:
        (out/'failed.json').write_text(json.dumps({'status':'failed; no acceptance','type':type(error).__name__,'commands':commands,'inputs':record['inputs'] if record else {}})+'\n')
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('sdk-proof','commoncommo-proof','commoncommo-bindings','java-home','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('sdk-sha256','commoncommo-sha256'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--phase',choices=('inspect','qualify'),default='inspect');args=parser.parse_args()
    def expired(_signum,_frame):raise TimeoutError('300-second total joined deadline')
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(300)
    try:run(args)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)


if __name__=='__main__':main()
