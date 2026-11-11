#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline qualification of unchanged official TAKX reader/JAXB serialization."""
import argparse
import hashlib
import importlib.util
import json
import os
import resource
from pathlib import Path
import subprocess
import struct
import warnings
import zipfile

ROOT=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('fixture_builder',ROOT/'build_fixture.py')
BUILDER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(BUILDER)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixtures(directory):
    directory=Path(directory);BUILDER.build(directory/'canonical.zip')
    with zipfile.ZipFile(directory/'canonical.zip') as archive:
        inputs={item.filename:archive.read(item) for item in archive.infolist()}
    manifest=inputs['MANIFEST/manifest.xml']
    def write(name,entries):
        with warnings.catch_warnings(),zipfile.ZipFile(directory/(name+'.zip'),'w') as archive:
            warnings.simplefilter('ignore',UserWarning)
            for key,value in entries:archive.writestr(key,value)
    body=[(key,value) for key,value in inputs.items() if key!='MANIFEST/manifest.xml']
    write('legacy',[('manifest.xml',manifest),*body])
    write('nested',[('wrapper/'+key,value) for key,value in inputs.items()])
    write('missing',body)
    write('malformed',[('MANIFEST/manifest.xml',b'<MissionPackageManifest version="2"><invalid>')])
    write('traversal',[('MANIFEST/manifest.xml',manifest.replace(b'files/README.txt',b'../escape.txt')),
                       ('../escape.txt',b'SYNTHETIC TRAVERSAL')])
    write('duplicate',[(key,value) for key,value in inputs.items() if key!='files/README.txt']+
          [('files/README.txt',b'FIRST'),('files/README.txt',b'LAST')])
    write('missing-content',[(key,value) for key,value in inputs.items() if key!='files/README.txt'])
    write('size',[(key,value) for key,value in inputs.items() if key!='files/README.txt']+[('files/README.txt',b'x'*4097)])
    dtd=directory/'owned-external.dtd';dtd.write_text('<!ENTITY synthetic "SYNTHETIC-EXTERNAL-DTD">')
    xml=manifest.replace(b'<?xml version="1.0" encoding="UTF-8"?>',
        ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE MissionPackageManifest SYSTEM "'+dtd.as_uri()+'">').encode())
    xml=xml.replace(b'00000000-0000-4000-8000-000000000410',b'&synthetic;')
    write('external-dtd',[('MANIFEST/manifest.xml',xml)])



def admission_fixtures(directory):
    directory=Path(directory)
    with zipfile.ZipFile(directory/'canonical.zip') as archive:
        canonical=[(item.filename,archive.read(item)) for item in archive.infolist()]
    manifest=dict(canonical)['MANIFEST/manifest.xml']
    def write(name,entries):
        with zipfile.ZipFile(directory/(name+'.zip'),'w',compression=zipfile.ZIP_STORED) as archive:
            for key,value in entries:archive.writestr(key,value)
    write('directories',[(name,b'') for name in ('MANIFEST/','cot/','files/')]+canonical)
    write('manifest-traversal',[(key,value.replace(b'files/README.txt',b'../escape.txt') if key=='MANIFEST/manifest.xml' else value) for key,value in canonical])
    for name,path in [('backslash','files\\escape.txt'),('absolute','/escape.txt'),('drive','C:/escape.txt'),
                      ('dot-segment','files/./escape.txt'),('empty-segment','files//escape.txt')]:
        write(name,canonical+[(path,b'SYNTHETIC')])
    write('file-directory-conflict',canonical+[('collision',b'file'),('collision/child.txt',b'child')])
    duplicate=manifest.replace(b'</Contents>',b'<Content zipEntry="files/README.txt" ignore="false"/></Contents>')
    write('duplicate-reference',[(key,duplicate if key=='MANIFEST/manifest.xml' else value) for key,value in canonical])
    write('ambiguous',canonical+[('manifest.xml',manifest)])
    padding=b'<!--'+b'x'*(1024**2)+b'-->'
    write('manifest-limit',[(key,value+padding if key=='MANIFEST/manifest.xml' else value) for key,value in canonical])
    internal=manifest.replace(b'<?xml version="1.0" encoding="UTF-8"?>',
        b'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE MissionPackageManifest [<!ENTITY synthetic "SYNTHETIC-INTERNAL">]>')
    write('internal-dtd',[(key,internal if key=='MANIFEST/manifest.xml' else value) for key,value in canonical])
    write('count-limit',canonical+[(f'empty-{index}',b'') for index in range(2049)])
    # Forge only central-directory size metadata of these controlled tiny ZIPs.
    # No large payload is allocated/decompressed; actual constructor checks are exercised.
    def declared_sizes(name,entries,sizes):
        write(name,entries);path=directory/(name+'.zip');data=bytearray(path.read_bytes());offset=0
        while True:
            offset=data.find(b'PK\x01\x02',offset)
            if offset<0:break
            length,extra,comment=struct.unpack_from('<HHH',data,offset+28)
            entry=bytes(data[offset+46:offset+46+length]).decode()
            if entry in sizes:struct.pack_into('<I',data,offset+24,sizes[entry])
            offset+=46+length+extra+comment
        path.write_bytes(data)
    declared_sizes('entry-limit',canonical,{'files/README.txt':64*1024**2+1})
    extra=[(f'large-{index}',b'x') for index in range(5)]
    declared_sizes('aggregate-limit',canonical+extra,{name:64*1024**2 for name,_ in extra})
    write('same-basename',canonical+[('one/README.txt',b'FIRST'),('two/README.txt',b'SECOND')])
    write('changed-archive',[(key,value if key!='files/README.txt' else b'NEXT') for key,value in canonical])
    write('crc-extra',canonical+[('extra.p12',b'SYNTHETIC INVALID CERT BYTES')])
    extra_path=directory/'crc-extra.zip';extra_data=bytearray(extra_path.read_bytes())
    with zipfile.ZipFile(extra_path) as extra_zip:extra_offset=extra_zip.getinfo('extra.p12').header_offset
    extra_name,extra_field=struct.unpack_from('<HH',extra_data,extra_offset+26);extra_data[extra_offset+30+extra_name+extra_field]^=1;extra_path.write_bytes(extra_data)
    write('crc',canonical)
    path=directory/'crc.zip';data=bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:offset=archive.getinfo('files/README.txt').header_offset
    length,extra=struct.unpack_from('<HH',data,offset+26);data[offset+30+length+extra]^=1;path.write_bytes(data)


def qualify(source,maven,java_home,output,admission_projection=None):
    source,maven,java_home,output=map(Path,(source,maven,java_home,output))
    lock_hash=digest(ROOT/'inputs.lock.json')
    lock=json.loads((ROOT/'inputs.lock.json').read_text())
    paths=[]
    for path,expected in lock['takx']['sources'].items():
        actual=source/path
        if digest(actual)!=expected:raise ValueError('official source hash mismatch')
        paths.append(str(actual))
    jars=[]
    for name,item in lock['dependencies'].items():
        actual=maven/name
        if actual.stat().st_size!=item['bytes'] or digest(actual)!=item['sha256']:raise ValueError('dependency hash mismatch')
        jars.append(str(actual))
    for path,expected in lock['takx'].get('integrationSources',{}).items():
        if digest(source/path)!=expected:raise ValueError('receive/import wiring source mismatch')
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False)
    if revision.returncode or revision.stdout.decode().strip()!=lock['takx']['revision']:raise ValueError('official source revision mismatch')
    projection=None
    if admission_projection is not None:
        spec=importlib.util.spec_from_file_location('mission_projection',ROOT/'project_sources.py')
        projector=importlib.util.module_from_spec(spec);spec.loader.exec_module(projector)
        projection=projector.verify(admission_projection)
        paths=[str(Path(admission_projection)/'source'/path) if path in projection['sources'] else str(source/path)
               for path in lock['takx']['sources']]
    output.mkdir();output.chmod(0o700)
    classes=output/'classes';classes.mkdir()
    cases=output/'cases';cases.mkdir();fixtures(cases)
    harness='MissionPackageAdmission' if projection else 'MissionPackageConformance'
    if projection:admission_fixtures(cases)
    classpath=os.pathsep.join(jars)
    environment=dict(os.environ)
    for key in ('JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','JDK_JAVAC_OPTIONS','_JAVA_OPTIONS','CLASSPATH','LD_PRELOAD','LD_LIBRARY_PATH','JAVA_HOME','JDK_HOME'):
        environment.pop(key,None)
    commands=[('javac',[str(java_home/'bin/javac'),'-J-Xmx128m','--release','17','-encoding','UTF-8','-proc:none','-cp',classpath,'-d',str(classes),*paths,str(ROOT/(harness+'.java'))]),
              ('java',[str(java_home/'bin/java'),'-Xmx64m','-Djava.awt.headless=true','-cp',str(classes)+os.pathsep+classpath,harness,str(cases)])]
    for name,command in commands:
        with (output/(name+'.stdout')).open('xb') as stdout,(output/(name+'.stderr')).open('xb') as stderr:
            stdout_path=Path(stdout.name);stderr_path=Path(stderr.name);stdout_path.chmod(0o600);stderr_path.chmod(0o600)
            def bounded_files():resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
            result=subprocess.run(command,stdout=stdout,stderr=stderr,timeout=45,check=False,preexec_fn=bounded_files,env=environment)
        if result.returncode:raise ValueError('actual official Java qualification failed; retain bounded local evidence')
        if stdout_path.stat().st_size>65536 or stderr_path.stat().st_size>65536:raise ValueError('diagnostics exceeded bound')
    if digest(ROOT/'inputs.lock.json')!=lock_hash:raise ValueError('input lock changed during qualification')
    for path,expected in {**lock['takx']['sources'],**lock['takx'].get('integrationSources',{})}.items():
        if digest(source/path)!=expected:raise ValueError('official source changed during qualification')
    for name,item in lock['dependencies'].items():
        if digest(maven/name)!=item['sha256']:raise ValueError('dependency changed during qualification')
    if projection and projector.verify(admission_projection)!=projection:raise ValueError('source projection changed during qualification')
    observed=json.loads((output/'java.stdout').read_text())
    proof={'scope':'actual projected admission reader/shared remote guard only; not full Client or native transfer' if projection else 'actual official TAKX reader/model only; not Android import or CommonCommo transfer',
           'admissionProjection':projection,
           'actualClassInventory':{path.relative_to(classes).as_posix():digest(path) for path in classes.rglob('*.class')},
           'fixtureArchives':{path.name:{'sha256':digest(path),'bytes':path.stat().st_size} for path in cases.glob('*.zip')},
           'takxRevision':lock['takx']['revision'],'inputLockSha256':digest(ROOT/'inputs.lock.json'),
           'fixtureLockSha256':digest(ROOT/'fixtures.lock.json'),
           'codeSha256':{name:digest(ROOT/name) for name in ('qualify.py','build_fixture.py',harness+'.java')},
           'toolchainSha256':{name:digest(java_home/'bin'/name) for name in ('java','javac')},'canonicalPackageSha256':digest(cases/'canonical.zip'),
           'observed':observed,'evidenceSha256':{path.name:digest(path) for path in output.glob('*.*') if path.is_file()}}
    (output/'qualification.json').write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('takx-source','maven-root','java-home','output'):parser.add_argument('--'+arg,required=True)
    parser.add_argument('--admission-projection')
    args=parser.parse_args()
    try:
        proof=qualify(args.takx_source,args.maven_root,args.java_home,args.output,args.admission_projection)
        print('Actual official mission reader/serializer qualification completed; checks='+str(len(proof['observed']['checks'])))
    except (ValueError,OSError,subprocess.SubprocessError):parser.exit(1,'Qualification failed; retain output and use a new path for another attempt\n')


if __name__=='__main__':main()
