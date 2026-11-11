#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline source-exact project Java/JNI interop profile. No native build or execution."""
import argparse,hashlib,importlib.util,json,os,shlex,shutil,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('interop_runner',HERE.parent/'native-commoncommo/runner.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())
def inventory(root):return {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
def validate(lock):
 if (lock['actual_kernel_version'],lock['official_revision'],lock['profile'],lock['viewport_policy'])!=('8.30.5','9f6893dd657feacc35ec5de03dad721c2e44170e','public-kernel-client-interop-v1','public-viewport-fit-v1'):raise ValueError('unsupported real project source identity')
 if digest(HERE/'client-contracts.patch')!=lock['patch_sha256']:raise ValueError('source patch differs')
 for n,v in lock['owned_java'].items():
  if digest(HERE/n)!=v:raise ValueError('owned policy source differs')
def disjoint(output, inputs):
 output=output.resolve()
 if output.exists() or any(output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in inputs):
  raise ValueError('new disjoint output required')
def syntax_command(entry, source, headers):
 argv=entry.get('arguments') or shlex.split(entry['command'])
 if argv.count(entry['file']) != 1 or any(v.startswith('@') for v in argv):
  raise ValueError('exact direct compiler source required')
 clean=[];skip=False
 for token in argv:
  if skip:skip=False;continue
  if token in ['-o','-MF','-MT','-MQ']:skip=True;continue
  if token in ['-c','-MD','-MMD']:continue
  clean.append(str(source) if token==entry['file'] else token)
 if skip:raise ValueError('truncated compiler option')
 clean[1:1]=['-fsyntax-only','-I'+str(headers)]
 return clean
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for n in ['source','sdk-proof','output','java-home']:ap.add_argument('--'+n,type=Path,required=True)
 ap.add_argument('--phase',choices=['verify','java','controls','syntax'],default='verify');ap.add_argument('--native-proof',type=Path);ap.add_argument('--public-jars',type=Path)
 args=ap.parse_args();lock=load(HERE/'inputs.lock.json');validate(lock)
 output=args.output.absolute()
 disjoint(output,[HERE.parent.parent,args.source,args.sdk_proof,args.java_home,*([args.native_proof] if args.native_proof else []),*([args.public_jars] if args.public_jars else [])])
 initial={n:digest(HERE/n) for n in ['build.py','inputs.lock.json','client-contracts.patch','java/PublicViewportFit.java','HeadlessControls.java']};initial['../native-commoncommo/runner.py']=digest(HERE.parent/'native-commoncommo/runner.py')
 sdk=load(args.sdk_proof/'complete.json');package=args.sdk_proof/'package';manifest=sdk['manifest']
 if manifest['version']!='8.30.5' or manifest['class_count']!=2697 or not sdk['component_runtime_acceptance']:raise ValueError('actual qualified public Kernel package required')
 sdkjar=next(package.glob('kernel-8.30.5-*.jar'));cp=[sdkjar]+[package/v['path'] for v in manifest['dependencies']]
 sdkcp=list(cp)
 if args.phase=='controls':
  if not args.public_jars:raise ValueError('exact public runtime JAR directory required')
  for name,item in lock['public_runtime_jars'].items():
   path=args.public_jars/name
   if path.is_symlink() or path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise ValueError('actual public renderer runtime dependency differs')
   cp.append(path)
 deps={str(p):digest(p) for p in cp}
 for p in sdkcp:
  if digest(p)!=sdk['package_inventory'][str(p.relative_to(package))]['sha256']:raise ValueError('SDK input differs')
 tools={n:Path(shutil.which(n) or n).resolve() for n in ['git','patch']};java=args.java_home.resolve()
 for n in ['java','javac']:
  if digest(java/'bin'/n)!=sdk['jdk_tools'][n]['sha256']:raise ValueError('qualified JDK required')
 output.mkdir(mode=0o700,parents=True);started=time.monotonic();env=dict(os.environ)
 for n in ['JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','JDK_JAVAC_OPTIONS','_JAVA_OPTIONS','CLASSPATH','LD_PRELOAD','LD_LIBRARY_PATH']:env.pop(n,None)
 env.update(GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_TERMINAL_PROMPT='0',PYTHONNOUSERSITE='1')
 commands=[];original_size=runner.disk_bytes
 def size(root):
  if shutil.disk_usage(output).free<2*1024**3:raise ValueError('2GiB free disk floor')
  return original_size(root)
 runner.disk_bytes=size
 def run(command,name,timeout=120):
  remain=600-(time.monotonic()-started)
  if remain<=0:raise ValueError('aggregate command deadline')
  command=list(map(str,command));command[0]=str(tools.get(command[0],command[0]));commands.append({'name':name,'argv':command,'timeout':min(timeout,remain)});(output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
  return runner.execute(command,output,name,timeout=min(timeout,remain),env=env,capture=True,disk_limit=35*1024**2)
 record={'recipe':initial,'sdk_receipt_sha256':digest(args.sdk_proof/'complete.json'),'source_lock':lock,'tools':{n:{'path':str(p),'sha256':digest(p)} for n,p in tools.items()},'jdk':{n:{'path':str(java/'bin'/n),'sha256':digest(java/'bin'/n)} for n in ['java','javac']},'dependencies':deps,'native_object_or_link_performed':False,'new_JNI_executed':False,'native_feature_acceptance':False,'multipoint_detail_acceptance':False,'private_sdk_equivalence':False,'phase':args.phase}
 if args.phase=='verify':(output/'verified.json').write_text(json.dumps(record,indent=2)+'\n');return
 stage=output/'source';stage.mkdir()
 for i,(name,v) in enumerate(lock['files'].items()):
  data=run(['git','--no-lazy-fetch','-C',args.source,'show',lock['official_revision']+':'+name],'source-'+str(i),20)
  if hashlib.sha256(data).hexdigest()!=v['before']:raise ValueError('official source preimage differs')
  path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 run(['patch','--batch','--fuzz=0','-p1','-d',stage,'-i',HERE/'client-contracts.patch'],'apply-reviewed-source',20)
 for name,v in lock['files'].items():
  if digest(stage/name)!=v['after']:raise ValueError('source postimage differs')
 policy=stage/'takkernel/shared/src/main/java/gov/tak/platform/symbology/milstd2525/PublicViewportFit.java';shutil.copyfile(HERE/'java/PublicViewportFit.java',policy)
 classes=output/'classes';classes.mkdir();headers=output/'jni-headers';headers.mkdir();empty=output/'empty';empty.mkdir();sources=[stage/n for n in lock['files'] if n.endswith('.java')]+[policy]
 run([java/'bin/javac','-J-Xmx768m','-J-XX:ActiveProcessorCount=2','--release','17','-proc:none','-implicit:none','-sourcepath',empty,'-cp',os.pathsep.join(map(str,cp)),'-d',classes,'-h',headers,*sources],'compile-source-profile')
 record.update(sources=inventory(stage),classes=inventory(classes),jni_headers=inventory(headers))
 if args.phase=='controls':
  tests=output/'control-classes';tests.mkdir();fullcp=os.pathsep.join(map(str,[classes,*cp]))
  run([java/'bin/javac','--release','17','-proc:none','-cp',fullcp,'-d',tests,HERE/'HeadlessControls.java'],'compile-headless-controls')
  text=run([java/'bin/java','-Djava.awt.headless=true','-Xmx512m','-XX:ActiveProcessorCount=2','-cp',os.pathsep.join([str(tests),fullcp]),'gov.tak.platform.symbology.milstd2525.HeadlessControls',output/'control-data'],'real-headless-controls').decode()
  if 'PASS_REAL_HEADLESS_CONTROLS' not in text or 'EngineLibrary: Failed' in text:raise ValueError('real headless control incomplete')
  record['headless_controls_passed']=True;record['control_classes']=inventory(tests)
 if args.phase=='syntax':
  if not args.native_proof:raise ValueError('actual native producer graph required for syntax-only JNI checks')
  native=load(args.native_proof/'complete.json')
  if not native['fresh_native_build'] or native['native_translation_units']!={'core':483,'jni':159,'cesium':173}:raise ValueError('actual complete native source graph required')
  native_inputs={str(args.native_proof/'complete.json'):digest(args.native_proof/'complete.json'),str(args.native_proof/'build/compile_commands.json'):digest(args.native_proof/'build/compile_commands.json')}
  for name,item in native['staged_sources'].items():
   path=args.native_proof/'layout'/name
   if digest(path)!=item['sha256']:raise ValueError('native source graph input changed')
   native_inputs[str(path)]=item['sha256']
  for name,value in native['actual_toolchain']['bound_files'].items():
   if digest(name)!=value:raise ValueError('native producer toolchain changed')
   native_inputs[name]=value
  compdb=load(args.native_proof/'build/compile_commands.json');compiler_before={}
  for i,name in enumerate(n for n in lock['files'] if n.endswith('.cpp')):
   rows=[v for v in compdb if v['file'].endswith('/'+name.removeprefix('takkernel/engine/src/main/')) or v['file'].endswith('/'+name.split('/jni/',1)[1])]
   if len(rows)!=1:raise ValueError('unique actual JNI translation unit required')
   entry=rows[0];clean=syntax_command(entry,stage/name,headers);compiler_before[clean[0]]=digest(clean[0])
   run(clean,'JNI-syntax-'+str(i),180)
  for name,value in native_inputs.items():
   if digest(name)!=value:raise ValueError('native syntax input changed')
  record['JNI_syntax_only_passed']=True;record['syntax_compilers']=compiler_before;record['observed_native_inputs']=native_inputs
 for n,p in tools.items():
  if digest(p)!=record['tools'][n]['sha256']:raise ValueError('metadata tool changed')
 for n in ['java','javac']:
  if digest(java/'bin'/n)!=record['jdk'][n]['sha256']:raise ValueError('qualified JDK changed')
 for p,v in deps.items():
  if digest(p)!=v:raise ValueError('consumed SDK dependency changed')
 if initial!={n:digest(HERE/n) if not n.startswith('../') else digest(HERE/n) for n in initial}:raise ValueError('producer changed')
 record.update(elapsed_seconds=time.monotonic()-started,output_bytes=size(output));(output/'complete.json').write_text(json.dumps(record,indent=2)+'\n');print('Project source profile passed specified phase; native/multipoint/SDK acceptance remains false.')
if __name__=='__main__':main()
