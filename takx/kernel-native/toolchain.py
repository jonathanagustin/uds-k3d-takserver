# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bind actual compiler/linker and CMake implementation, beyond launcher files."""
import json
from pathlib import Path
import shutil
import providers as p

def elf(path):
    with p.regular(path).open('rb') as stream:
        if stream.read(4)!=b'\x7fELF':raise ValueError('actual native tool ELF required: '+str(path))

def capture(tools,output,run,env):
    files={};backends={};package={}
    def bind(path):
        path=Path(path).resolve();files[str(path)]=p.digest(p.regular(path));return path
    cmake=bind(tools['cmake'])
    with cmake.open('rb') as stream:first=stream.readline(4096)
    binary=cmake
    if first.startswith(b'#!'):
        words=first[2:].decode().strip().split()
        if len(words)!=1 or not Path(words[0]).is_absolute():raise ValueError('reviewed absolute Python CMake launcher required')
        interpreter=bind(words[0]);package['wrapper_interpreter']={'path':str(interpreter),'sha256':files[str(interpreter)]}
        info=json.loads(run([words[0],'-I','-c','import cmake,json;print(json.dumps({"module":cmake.__file__,"bin":cmake.CMAKE_BIN_DIR}))'],'cmake-package-location',20).decode())
        module=Path(info['module']).resolve();package_root=module.parent
        for path in package_root.rglob('*.py'):
            if '__pycache__' not in path.parts:bind(path)
        binary=bind(Path(info['bin'])/'cmake');package['python_module']=str(module)
    elf(binary);package['native_binary']={'path':str(binary),'sha256':files[str(binary)]}
    root_script=output/'capture-cmake-root.cmake';root_script.write_text('message("KERNEL_NATIVE_CMAKE_ROOT=${CMAKE_ROOT}")\n')
    result=run([binary,'-P',root_script],'cmake-native-root',20).decode()
    lines=[line.split('=',1)[1] for line in result.splitlines() if line.startswith('KERNEL_NATIVE_CMAKE_ROOT=')]
    if len(lines)!=1:raise ValueError('actual CMake module root unavailable')
    package['module_root']=str(Path(lines[0]).resolve())
    # The complete actual CMake module/data root is bound, not a wrapper hash.
    for path in Path(lines[0]).rglob('*'):
        if path.is_file():bind(path)
    for driver,name in [('cc','cc1'),('cxx','cc1plus'),('cxx','collect2'),('cc','as'),('cxx','ld')]:
        value=run([tools[driver],'-print-prog-name='+name],'compiler-path-'+name,20).decode().strip()
        path=Path(shutil.which(value,path=env.get('PATH')) or value).resolve();elf(path);bind(path);backends[name]=str(path)
    for name in ('ar','ranlib'):
        path=Path(shutil.which(name,path=env.get('PATH')) or name).resolve();elf(path);bind(path);backends[name]=str(path)
    for path in tools.values():bind(path)
    return {'bound_files':files,'cmake':package,'compiler_and_binutils':backends}

def verify(record):
    p.bound_files(record['bound_files'])

def jdk_runtime(java_home,run):
    """Prevalidate exact JDK ELF identities and their actual host dependency closure."""
    import re
    java_home=Path(java_home).resolve();owned={};sonames={};pending=[]
    for path in java_home.rglob('*'):
        if not path.is_file():continue
        path=path.resolve()
        with path.open('rb') as stream:
            if stream.read(4)!=b'\x7fELF':continue
        owned[str(path)]=p.digest(path);pending.append(path)
    if not owned:raise ValueError('JDK ELF inventory empty')
    readelf=Path(shutil.which('readelf')).resolve();ldconfig=Path(shutil.which('ldconfig') or '/sbin/ldconfig').resolve()
    tool_files={str(readelf):p.digest(p.regular(readelf)),str(ldconfig):p.digest(p.regular(ldconfig))}
    dynamic={}
    for index,path in enumerate(pending):
        text=run([readelf,'-d',path],'jdk-needed-'+str(index),20).decode();dynamic[str(path)]=text
        sonames[path.name]=path
        for name in re.findall(r'\(SONAME\).*?\[(.*?)\]',text):sonames[name]=path
    cache=run([ldconfig,'-p'],'jdk-system-loader-cache',20).decode();system={}
    for line in cache.splitlines():
        m=re.match(r'\s*(\S+) \([^)]*x86-64[^)]*\) => (\S+)',line)
        if m and m[1] not in system:system[m[1]]=Path(m[2]).resolve()
    bound=dict(owned);queue=list(dynamic);visited=set();index=0
    while queue:
        name=queue.pop()
        if name in visited:continue
        visited.add(name);path=Path(name)
        text=dynamic.get(name)
        if text is None:
            text=run([readelf,'-d',path],'jdk-host-needed-'+str(index),20).decode();index+=1
        for needed in re.findall(r'\(NEEDED\).*?\[(.*?)\]',text):
            dependency=sonames.get(needed) or system.get(needed)
            if dependency is None:raise ValueError('JDK native dependency unresolved before build: '+needed)
            dependency=dependency.resolve();elf(dependency);bound[str(dependency)]=p.digest(dependency)
            if str(dependency) not in visited:queue.append(str(dependency))
    return {'bound_files':bound,'jdk_elfs':owned,'metadata_tools':tool_files,'resolution':'actual JDK DT_NEEDED closure through owned SONAMEs and recorded x86-64 loader cache'}
