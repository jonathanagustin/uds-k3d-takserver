#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Audit an exact local stopped producer stage; never adopt its JNI acceptance."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('commo_stage_build',HERE/'build.py')
B=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B)
PRODUCER=json.loads((HERE/'producer-c992.lock.json').read_text())
MAX_MANIFEST=16*1024**2

def load(path):
    if path.is_symlink():raise ValueError('manifest symlink refused')
    with path.open('rb') as f:data=f.read(MAX_MANIFEST+1)
    if len(data)>MAX_MANIFEST:raise ValueError('manifest exceeds bound')
    return json.loads(data)

def inventory(root):
    result=B.native.inventory(root)
    if sum(e.get('bytes',0) for e in result)>2*1024**3:raise ValueError('stage snapshot exceeds bound')
    return result

def audit(stage,source,spatial,zlib,quictls,tools,metadata,java,cache):
    stage=B.native.external(stage)
    if (stage/'complete.json').exists():raise ValueError('this observer is for the explicitly stopped c992 stage only')
    prepared=load(stage/'prepared.json')
    if prepared['recipe']!=PRODUCER['recipe'] or prepared['source']!=PRODUCER['revision'] or PRODUCER['version']!='1.17.2':
        raise ValueError('unreviewed stopped producer recipe/source')
    failure=load(stage/'failed.json')
    if failure.get('last_stage')!='CommonCommoTlsSmoke':raise ValueError('stage did not reach observed JNI checker boundary')
    for tool in prepared['host_tools'].values():
        if B.native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('producer host tool changed')
    if prepared['jdk_inventory']!=B.native.inventory(java):raise ValueError('producer JDK inventory changed')
    if prepared['tools']!=B.verify_tools(tools,metadata):raise ValueError('producer tool prefix changed')
    if prepared['debian_keyring_sha256']!=B.native.digest(Path('/usr/share/keyrings/debian-archive-keyring.gpg')):raise ValueError('producer trust keyring changed')
    if prepared['providers']!=B.verify_providers(spatial,zlib,quictls):raise ValueError('reused provider identity changed')
    for e in B.LOCK['archives']:B.native.verified(cache/e['sha256'],e)
    if B.native.git(source,'rev-parse','HEAD').decode().strip()!=PRODUCER['revision']:raise ValueError('official Git revision changed')
    common=load(stage/'commoncommo-sources.json')
    # Recompute all pinned official Git blobs, not just the self-recorded source hash.
    tree=B.native.git(source,'ls-tree','-r','-z',PRODUCER['revision'],'--','commoncommo').rstrip(b'\0').split(b'\0')
    git={}
    for row in tree:
        meta,name=row.split(b'\t');mode,kind,oid=meta.decode().split()
        if kind!='blob' or mode not in ('100644','100755'):raise ValueError('nonregular official source')
        data=B.native.git(source,'cat-file','blob',oid)
        git[name.decode()]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'git_blob':oid}
    if common['git']!=git:raise ValueError('official source/blob identity differs')
    B.check_record(stage/'commoncommo',common['patched'])
    deps=load(stage/'source-inputs.json')
    if set(deps)!={e['name'] for e in B.LOCK['archives']}:raise ValueError('dependency source families differ')
    for e in deps.values():
        path=Path(e['path'])
        if stage not in path.resolve().parents:raise ValueError('source inventory leaves original stage')
        B.check_record(path,e['postimages'])
    if prepared['commoncommo_source']!=B.native.digest(stage/'commoncommo-sources.json') or prepared['dependency_sources']!=B.native.digest(stage/'source-inputs.json'):
        raise ValueError('prepared source/config metadata changed')
    commands=load(stage/'commands.json');names=[c['stage'] for c in commands]
    required=['nghttp2-build','nghttp2-install','curl-build','curl-install','ngtcp2-build','ngtcp2-install','microhttpd-build','microhttpd-install','protoc-build','protobuf-lite-build','protobuf-headers','commoncommo-core','commoncommo-java','commoncommo-jni']
    if any(names.count(n)!=1 for n in required) or [names.index(n) for n in required]!=sorted(names.index(n) for n in required):raise ValueError('actual stage commands incomplete/ambiguous')
    # These logs are bounded private evidence. Return codes follow the reviewed
    # producer reaching its final fail-closed warnings gate, not simulated jobs.
    functional={}
    for name in B.SMOKES:
        text=(stage/(name+'.log')).read_text()
        if len(text.encode())>16*1024**2 or 'PASS' not in text or 'FATAL ERROR' in text:raise ValueError('observed functional stage incomplete')
        functional[name]={'sha256':B.native.digest(stage/(name+'.log')),'jni_warning_count':text.count('WARNING in native method:')}
    if not all(v['jni_warning_count']>0 for v in functional.values()):raise ValueError('expected stopped JNI warning evidence absent')
    prefix=stage/'install';archives={}
    for path in sorted((prefix/'lib').glob('*.a')):
        archives[path.name]={'sha256':B.native.digest(path),'bytes':path.stat().st_size,'elf_objects':B.db.archive_objects(path)}
    expected={'libcommoncommo.a','libcrypto.a','libssl.a','libcurl.a','libiconv.a','libxml2.a','libz.a','libnghttp2.a','libngtcp2.a','libngtcp2_crypto_quictls.a','libmicrohttpd.a','libprotobuf-lite.a'}
    if not expected.issubset(archives):raise ValueError('genuine static stage archive missing')
    headers=B.native.inventory(stage/'commoncommo/jni/native/headers')
    if not headers:raise ValueError('genuine JDK-generated JNI headers missing')
    observed=inventory(stage)
    result={'schema':1,'stage_class':'local-observed-dependencies-core-from-stopped-commoncommo','original_root':str(stage),
        'producer':PRODUCER,'prepared_sha256':B.native.digest(stage/'prepared.json'),'inventory':observed,'archives':archives,
        'jar_sha256':B.native.digest(prefix/'java/jcommoncommo.jar'),'native_headers':headers,'host_tools':prepared['host_tools'],
        'jdk_inventory':prepared['jdk_inventory'],'functional_observations':functional,'original_jni_accepted':False,
        'dependencies_and_core_reused':True,'source_revision':PRODUCER['revision'],
        'scope':'unsigned local observed-stage integrity, not publisher authentication or completed original JNI acceptance'}
    validate_record(result,stage)
    if inventory(stage)!=observed:raise ValueError('stage changed during snapshot audit')
    return result

def validate_record(record,stage):
    import re
    if record.get('producer')!=PRODUCER or record.get('stage_class')!='local-observed-dependencies-core-from-stopped-commoncommo' or record.get('original_jni_accepted') is not False or record.get('original_root')!=str(stage.resolve()):
        raise ValueError('stage provenance/scope/root differs')
    if set(record.get('host_tools',{}))!=set(PRODUCER['host_tool_names']) or sorted(e['path'] for e in record.get('native_headers',[]))!=PRODUCER['native_header_names'] or set(record.get('archives',{}))!=set(PRODUCER['static_archive_names']):
        raise ValueError('stage tool/header/archive closure incomplete')
    for name in ('jar_sha256','prepared_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',record.get(name,'')):raise ValueError('stage artifact identity missing')
    entries=record.get('inventory',[]);names=set()
    for entry in entries:
        name=str(B.native.relative(entry['path']))
        if name in names or not re.fullmatch('[0-9a-f]{64}',entry.get('sha256','')):raise ValueError('stage snapshot entries invalid/duplicate')
        names.add(name)
    required={'prepared.json','commands.json','source-inputs.json','commoncommo-sources.json','failed.json',
        'install/java/jcommoncommo.jar','install/lib/libcommoncommo.a','install/lib/libcommoncommojni.so'}
    required|={n+'.log' for n in B.SMOKES}
    if not required.issubset(names) or len(entries)<7000:raise ValueError('full observed source/config/artifact snapshot missing')

def verify(stage,manifest,expected_sha):
    if not __import__('re').fullmatch('[0-9a-f]{64}',expected_sha) or B.native.digest(manifest)!=expected_sha:raise ValueError('reviewed stage manifest digest differs')
    record=load(manifest)
    validate_record(record,stage)
    if record['inventory']!=inventory(stage):raise ValueError('frozen source/config/header/artifact snapshot changed')
    for tool in record['host_tools'].values():
        if B.native.digest(Path(tool['path']))!=tool['sha256']:raise ValueError('stage compiler/JDK/tool changed')
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['stage','source','spatial-proof','zlib-proof','quictls-proof','tools-root','tool-metadata','java-home','cache','report']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    if a.report.exists() or a.report.is_symlink() or a.stage.resolve() in a.report.resolve().parents:raise ValueError('new external report required')
    result=audit(a.stage,a.source,a.spatial_proof,a.zlib_proof,a.quictls_proof,a.tools_root,a.tool_metadata,a.java_home,a.cache)
    a.report.write_text(json.dumps(result,indent=2)+'\n');print('Exact stopped dependency/core stage audited; original JNI remains unaccepted')
if __name__=='__main__':main()
