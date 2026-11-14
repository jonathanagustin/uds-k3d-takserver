# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Pure integrity checks for real producer chains; never build or load libraries."""
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
TAKX=HERE.parent
FAMILIES={'sqlcipher':'native-sqlcipher','geos':'native-geos','proj':'native-proj','assimp':'native-assimp','las':'native-las','mdb':'native-mdbtools','draco':'native-deps','spatial':'kernel-spatial-db','cesium':'native-cesium','gdal_jni':'native-gdal-jni','gles':'native-gles','kml':'native-kml','curl':'native-curl','kernel_java':'kernel-java'}
MODULES={}
def digest(path):
    with Path(path).open('rb') as stream:
        h=hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def regular(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('regular bound file required: '+str(path))
    return path
def load(path):return json.loads(regular(path).read_text())
def module(family):
    if family not in MODULES:
        spec=importlib.util.spec_from_file_location('kernel_native_'+family,TAKX/FAMILIES[family]/'build.py')
        MODULES[family]=importlib.util.module_from_spec(spec);spec.loader.exec_module(MODULES[family])
    return MODULES[family]
def inventory(root):
    result={}
    for p in sorted(Path(root).rglob('*')):
        if '__pycache__' in p.parts:continue
        if p.is_symlink():raise ValueError('symlink in bound tree: '+str(p))
        if p.is_file():result[str(p.relative_to(root))]={'bytes':p.stat().st_size,'sha256':digest(p)}
        elif not p.is_dir():raise ValueError('nonregular bound tree member')
    return result
def check_files(root,expected):
    if isinstance(expected,list):
        if module('draco').inventory(Path(root))!=expected:raise ValueError('installed inventory differs: '+str(root))
        return
    actual=inventory(root)
    if all(isinstance(v,str) for v in expected.values()):actual={k:v['sha256'] for k,v in actual.items()}
    if actual!=expected:raise ValueError('bound tree inventory differs: '+str(root))
def bound_files(values,root=None):
    for name,entry in values.items():
        p=(Path(root)/name) if root else Path(name)
        if root and (Path(name).is_absolute() or '..' in Path(name).parts):raise ValueError('bound output escapes root')
        expected=entry['sha256'] if isinstance(entry,dict) else entry
        if digest(regular(p))!=expected:raise ValueError('bound file changed: '+str(p))
        if isinstance(entry,dict) and 'bytes' in entry and p.stat().st_size!=entry['bytes']:raise ValueError('bound size changed')
def recipe_check(family,record,history_key=None):
    producer=module(family)
    current=producer.recipe() if hasattr(producer,'recipe') else producer.a.inventory(producer.HERE) if family=='cesium' else {n:digest(producer.HERE/n) for n in ('build.py','inputs.lock.json','DracoSourceProbe.cpp')}
    historical = record['recipe']!=current
    if historical:
        allowed=load(HERE/'producer-history.lock.json').get(history_key or family)
        if not allowed or record['recipe']!=allowed['recipe']:raise ValueError('unreviewed consumed producer source variant: '+family)
        for name,value in record['recipe'].items():
            expected=value['sha256'] if isinstance(value,dict) else value
            recipe_root=TAKX if family=='gdal_jni' else producer.HERE
            candidate=HERE/allowed['variants'][name]['snapshot'] if name in allowed['variants'] else recipe_root/name
            if not candidate.resolve().is_relative_to(TAKX.resolve()) or digest(regular(candidate))!=expected:raise ValueError('historical consumed source body differs')
    for name,tool in record.get('tools',{}).items():
        path,expected=(tool['path'],tool['sha256']) if isinstance(tool,dict) else (name,tool)
        if digest(regular(path))!=expected:raise ValueError('producer tool changed')
    return historical
def verify_java(root):
    mod=module('kernel_java');record=load(root/'inputs.json');result=load(root/'result.json')
    if record['recipe_sha256']!=digest(mod.HERE/'build.py') or record['lock_sha256']!=digest(mod.HERE/'inputs.lock.json'):raise ValueError('Java normative recipe differs')
    if record['upstream_revision']!=mod.REVISION or record['classpath_profile']!='patched' or record['source_scope']!='engine-shared' or not record['generate_jni_headers']:raise ValueError('complete real Java/JNI profile required')
    if result['exit_code'] or result['errors'] or result['required_jni_headers']!=109 or result['generated_jni_headers']!=118 or result['compiled_class_files']!=2697 or result['adapter_sources']!=59 or result['upstream_sources']!=1176:raise ValueError('Java/JNI producer scope incomplete')
    for entry in record['sources']:bound_files({entry['path']:entry['sha256']})
    for entry in record['classpath']:bound_files({entry['path']:entry['sha256']})
    bound_files({record['toolchain']['javac']:record['toolchain']['sha256']})
    check_files(root/'classes',load(root/'class-hashes.json'));check_files(root/'jni-headers',load(root/'jni-header-hashes.json'))
    coverage=load(root/'jni-header-coverage.json')
    if coverage['missing_headers']:raise ValueError('required generated JNI header absent')
    return {'receipt':'inputs.json','sha256':digest(root/'inputs.json'),'fresh_native_build':False}
def verify(family,root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('regular producer root required')
    root=root.resolve()
    if family=='kernel_java':return verify_java(root)
    record=load(root/'complete.json');before=digest(root/'complete.json');historical=recipe_check(family,record);producer=module(family)
    if family in ('sqlcipher','geos','proj','assimp'):
        # Existing normative contract also checks sources, installed files, tools,
        # positive outputs and runtime for these source-built component families.
        module('spatial').dependency(root,{'assimp':'zlib'}.get(family,family)) if family=='assimp' else module('spatial').dependency(root,family)
    elif family=='las':
        producer.validate_lock(load(producer.HERE/'inputs.lock.json'))
        if record.get('revision')!='9f6893dd657feacc35ec5de03dad721c2e44170e' or not record.get('whole_archive_pic') or not record.get('las_laz_semantics'):raise ValueError('LAS source/control contract differs')
        check_files(root/'install',record['installed']);producer.check_sources(root/'source',load(root/'sources.json'),record['generated_source_files'])
        producer.verify_runtime(record['runtime_closure'])
    elif family=='mdb':
        if record.get('version')!='1.0.0' or not record.get('strict_pic') or not record.get('real_mdb_controls'):raise ValueError('MDBTools real source controls absent')
        producer.check_sources(root/'source',record['source_inventory']);check_files(root/'install',record['installed']);bound_files(record['outputs'],root);producer.las.verify_runtime(record['runtime_closure'])
    elif family=='draco':
        if record.get('draco_version')!='1.5.7' or not record.get('codec_fixture_probe_passed') or not record.get('pic_link_passed'):raise ValueError('Draco real codec/PIC proof absent')
        check_files(root/'install',record['installed']);sources=load(root/'sources.json')
        if digest(root/'sources.json')!=record['source_inventory_sha256']:raise ValueError('Draco source receipt changed')
        check_files(root/'source',{v['path']:{'bytes':v['bytes'],'sha256':v['sha256']} for v in sources});producer.verify_probe_outputs(root,record['probe_outputs'])
    elif family=='spatial':
        if not record.get('strict_pic') or not record.get('real_kernel_spatial_database_controls'):raise ValueError('actual spatial database controls absent')
        for name,files in record['source_inventories'].items():check_files(root/(name+'-source'),files)
        for name,files in record['installed'].items():check_files(root/(name+'-install'),files)
        bound_files(record['outputs'],root);producer.las.verify_runtime(record['runtime_closure'])
    elif family=='gdal_jni':
        # This pure verifier preserves its frozen stopped-producer ancestry.
        if historical:
            if any(record.get(key) not in (None,False) for key in ('kml_profile_enabled','strict_jni_diagnostics_free')) or record.get('kml_build') is not None:
                raise ValueError('historical GDAL baseline cannot claim strict JNI or KML acceptance')
            producer.replay_artifacts(root,record)
        else:
            producer.replay(root)
    elif family=='gles':
        if not record.get('genuine_surfaceless_es3_clear_readback'):raise ValueError('real GLES controls absent')
        check_files(root/'source',record['source_inventory']);check_files(root/'install',record['installed']);bound_files(record['headers'],root/'include');bound_files(record['host_inputs']);bound_files(record['runtime_providers'])
        required={'libGLdispatch.so.0.0.0','libGLESv2.so.2.1.0'}
        if not required<={Path(p).name for p in record['runtime_providers']}:raise ValueError('actual source dispatch/GLES missing')
    elif family=='kml':
        if not record.get('strict_whole_archive_pic') or not record.get('dom_kmz_uri_controls') or not record.get('private_static_expat_dynsym_verified'):raise ValueError('real KML controls absent')
        check_files(root/'install',record['installed']);check_files(root/'expat-install',record['expat_installed'])
        for name,files in record['source_postimages'].items():check_files(root/'source'/name,files)
    elif family=='curl':
        if record.get('version')!=load(producer.HERE/'inputs.lock.json')['version'] or not record.get('strict_whole_archive_pic') or not record.get('escape_free_backend_feature_controls'):raise ValueError('real curl profile absent')
        check_files(root/'install',record['installed']);check_files(root/'build',record['objects'])
        if digest(producer.HERE/'source.lock.json')!=record['source_inventory_sha256']:raise ValueError('curl source lock differs')
        check_files(root/'source',load(producer.HERE/'source.lock.json'))
    elif family=='cesium':
        if not record.get('full_cesium_build_acceptance') or record['actual_targets']!=producer.TARGETS:raise ValueError('full actual Cesium target graph required')
        if digest(root/'prepared.json')!=record['prepared_sha256']:raise ValueError('Cesium preparation receipt differs')
        check_files(root/'install',record['installed']);observed=load(root/'observed-products.json')
        if observed['complete_sha256']!=before:raise ValueError('Cesium observed completion differs')
        bound_files(observed['all_files'],root)
        # Never turn the recorded resumed dependency lineage into a fresh build.
        if bool(record['lineage'])==bool(record['fresh_dependency_build']):raise ValueError('Cesium lineage/fresh flags inconsistent')
    else:raise ValueError('unsupported provider family')
    if digest(root/'complete.json')!=before:raise ValueError('producer receipt changed during validation')
    return {'receipt':'complete.json','sha256':before,'fresh_dependency_build':record.get('fresh_dependency_build',False),'lineage':record.get('lineage'),'source_recipe':record['recipe']}
def root_of(paths,family):
    value=paths[family];return Path(value['root'] if isinstance(value,dict) else value).resolve()

def declared_paths(paths):
    result=[]
    def visit(value):
        if isinstance(value,dict):
            for item in value.values():visit(item)
        elif isinstance(value,str):result.append(Path(value))
        else:raise ValueError('declared provider paths must be strings')
    visit(paths);return result

def verify_cesium_ancestry(paths):
    selected=paths['cesium']
    if not isinstance(selected,dict):raise ValueError('Cesium requires declared producer and acquisition roots')
    root=root_of(paths,'cesium');complete=load(root/'complete.json');lineage=complete['lineage']
    if lineage is None:
        if set(selected)!={'root','acquisition_root'} or complete.get('fresh_dependency_build') is not True or complete.get('fresh_cesium_build') is not True:
            raise ValueError('fresh Cesium requires honest freshness and only its acquisition root')
        original=load(root/'producer.json');prepared=load(root/'prepared.json')
        if original.get('lineage') is not None or original.get('fresh_dependency_build') is not True:
            raise ValueError('fresh Cesium producer lineage differs')
        recipe_check('cesium',original)
        acquired=Path(selected['acquisition_root']).resolve()
        acquisition=load(acquired/'acquired.json');sha=digest(acquired/'acquired.json')
        if sha!=original['sources_receipt_sha256'] or sha!=prepared['sources_receipt_sha256']:
            raise ValueError('fresh Cesium acquisition receipt differs')
        for name,entry in acquisition['sources'].items():check_files(acquired/'source'/name,entry['files'])
        providers=module('cesium').a.verify_providers(root_of(paths,'sqlcipher'),root_of(paths,'draco'))
        if original['providers']!=providers or acquisition['providers']!=providers:
            raise ValueError('fresh Cesium selected provider chain differs')
        return {'fresh_dependency_build':True,'acquisition_sha256':sha,'original_recipe':original['recipe']}
    if set(selected)!={'root','dependency_root','stopped_inventory','acquisition_root'}:
        raise ValueError('continued Cesium requires complete declared retained ancestry')
    previous=Path(selected['dependency_root']).resolve();snapshot=Path(selected['stopped_inventory']);acquired=Path(selected['acquisition_root']).resolve()
    if previous!=Path(lineage['previous_output']).resolve():raise ValueError('Cesium ancestry relocation requires a separate accepted operation')
    if digest(snapshot)!=lineage['stopped_inventory_sha256']:raise ValueError('Cesium stopped source inventory differs')
    check_files(previous,load(snapshot));original=load(previous/'producer.json')
    if original!=lineage['original_producer']:raise ValueError('Cesium original producer differs')
    recipe_check('cesium',original,'cesium_ancestor')
    failed=load(previous/'failed.json')
    if failed['completed']!=lineage['completed_actions']:raise ValueError('Cesium resumed action prefix differs')
    historical=load(HERE/'producer-history.lock.json')['cesium_ancestor']
    plan_path=HERE/historical['variants']['build-plan.json']['snapshot'] if 'build-plan.json' in historical['variants'] else module('cesium').HERE/'build-plan.json'
    order=load(plan_path)['topological_order']
    if failed['completed']!=order[:len(failed['completed'])] or len(failed['completed'])!=len(set(failed['completed'])):raise ValueError('Cesium completed actions not the original producer prefix')
    if digest(acquired/'acquired.json')!=original['sources_receipt_sha256']:raise ValueError('Cesium acquired source receipt differs')
    acquisition=load(acquired/'acquired.json')
    for name,entry in acquisition['sources'].items():check_files(acquired/'source'/name,entry['files'])
    selected_providers=module('cesium').a.verify_providers(root_of(paths,'sqlcipher'),root_of(paths,'draco'))
    if original['providers']!=selected_providers or acquisition['providers']!=selected_providers:raise ValueError('Cesium source/provider chain differs from selected roots')
    return {'stopped_inventory_sha256':digest(snapshot),'original_recipe':original['recipe'],'completed_actions':failed['completed'],'fresh_dependency_build':False,'acquisition_sha256':digest(acquired/'acquired.json')}

def verify_cross_links(paths):
    kml=module('kml');kroot=root_of(paths,'kml');krecord=load(kroot/'complete.json')
    boost=kml.verify_las(root_of(paths,'las'))[1]
    snapshot=paths['cesium'].get('stopped_inventory')
    uri=kml.verify_cesium(root_of(paths,'cesium'),Path(snapshot) if snapshot is not None else None)[1]
    gdal=paths['gdal_jni'];proof=Path(gdal['dependency_proof']);dependency=Path(gdal['dependency_root'])
    reference=kroot/'source/libkml/third_party/zlib-1.2.3/contrib/minizip'
    minizip=kml.verify_minizip(dependency,proof,reference)[1]
    expected={'boost':boost,'uriparser':uri,'minizip':minizip,'assimp_zlib_receipt_sha256':digest(root_of(paths,'assimp')/'complete.json')}
    if krecord['providers']!=expected:raise ValueError('KML selected Boost/URI/minizip/zlib ABI providers differ')
    curl=module('curl');crecord=load(root_of(paths,'curl')/'complete.json')
    if curl.providers(root_of(paths,'sqlcipher'),root_of(paths,'assimp'))!=crecord['providers']:raise ValueError('curl selected crypto/zlib provider chain differs')
    spatial=load(root_of(paths,'spatial')/'complete.json')
    for family in ('proj','geos','sqlcipher','zlib'):
        selected=root_of(paths,'assimp' if family=='zlib' else family)
        if digest(selected/'complete.json')!=spatial['input_receipt_sha256'][family]:raise ValueError('spatial selected dependency differs')
    accepted=load(root_of(paths,'gdal_jni')/'accepted-inputs.json')
    if digest(proof/'dependencies-built.json')!=accepted['native']['receipt_sha256']:raise ValueError('GDAL stopped-dependency proof differs')
    return {'kml_selected_abi_providers':expected,'curl_selected_providers':crecord['providers'],'gdal_dependency_receipt_sha256':accepted['native']['receipt_sha256']}

def verify_all(paths):
    if set(paths)!=set(FAMILIES):raise ValueError('exact complete named provider inventory required')
    results={};errors={}
    for family,path in paths.items():
        try:
            if family=='gdal_jni':
                if not isinstance(path,dict) or set(path)!={'root','dependency_root','dependency_proof'}:raise ValueError('GDAL requires its accepted stopped-dependency root/proof')
                results[family]=verify(family,Path(path['root']))
                accepted=load(Path(path['root'])/'accepted-inputs.json')['native']
                check_files(Path(path['dependency_root'])/'gdal-install',accepted['installed'])
                bound_files(accepted['bindings']['files'],Path(path['dependency_root']))
                results[family]['lineage']={'fresh_build':accepted['fresh_build'],'ancestry':accepted['lineage']}
            else:results[family]=verify(family,root_of(paths,family))
        except (ValueError,KeyError,FileNotFoundError,TypeError) as error:errors[family]=str(error)
    if not errors:
        try:
            results['cesium']['verified_ancestry']=verify_cesium_ancestry(paths)
            results['kml']['verified_cross_links']=verify_cross_links(paths)
        except (ValueError,KeyError,FileNotFoundError,TypeError) as error:errors['cross_provider_chain']=str(error)
    return results,errors
