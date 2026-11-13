# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit SDK composition; baseline native producer/provider APIs stay strict."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import ModuleType

HERE = Path(__file__).resolve().parent
_VALIDATOR = None

PROFILE = 'public-cpu-gdal244-kml-v1'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked(path, expected):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file() or path.resolve()!=path or digest(path) != expected:
        raise ValueError('composition input differs: ' + str(path))
    return path

def validator():
    global _VALIDATOR
    if _VALIDATOR is None:
        path=HERE.parent/'native-gdal-jni/finalization_validation.py'
        spec=importlib.util.spec_from_file_location('sdk_composition_finalizer',path)
        _VALIDATOR=importlib.util.module_from_spec(spec);spec.loader.exec_module(_VALIDATOR)
    return _VALIDATOR

def module_source_closure(modules, root):
    root=Path(root).resolve();seen=set();result={}
    def visit(module):
        if id(module) in seen:return
        seen.add(id(module));filename=getattr(module,'__file__',None)
        if not filename:return
        path=Path(filename).absolute()
        if not path.is_relative_to(root):return
        if path.suffix!='.py' or path.is_symlink() or not path.is_file() or path.resolve()!=path:
            raise ValueError('consumed validator source must be canonical regular Python')
        result[path.relative_to(root).as_posix()]=digest(path)
        for value in vars(module).values():
            if isinstance(value,ModuleType):visit(value)
    for module in modules:visit(module)
    return result

def source_closure():
    finalizer=validator();root=HERE.parent
    result=dict(finalizer.producer.recipe())
    result.update(module_source_closure([finalizer],root))
    result['sdk-package/composition.py']=digest(Path(__file__))
    return result

def declaration_kind(config):
    historical={'schema','profile','finalization_plan','finalization_plan_sha256','finalization_receipt','finalization_receipt_sha256'}
    fresh={'schema','profile','producer_kind','producer_receipt','producer_receipt_sha256','producer_recipe_sha256'}
    if not isinstance(config,dict) or type(config.get('schema')) is not int or config['schema']!=1 or config.get('profile')!=PROFILE:
        raise ValueError('explicit supported composition declaration required')
    if set(config)==historical:return 'historical-finalized'
    if set(config)==fresh and config['producer_kind']=='successful':return 'successful'
    raise ValueError('explicit supported composition declaration required')

def verify_reduced_closure(root, inventory, objects, warnings):
    options=(root/'gdal-kml-build/GDALmake.opt').read_text()
    if not re.search(r'^HAVE_SQLITE\s*=\s*no\s*$',options,re.M):
        raise ValueError('reduced profile requires SQLite drivers compiled out')
    files=[name for name in inventory['regularFiles'] if name.endswith('.o')]
    if objects!=1073 or warnings!=0 or len(files)!=1073 or any(re.search(r'(?:mbtiles|gpkg|sqlite)',name,re.I) for name in files):
        raise ValueError('actual reduced native closure differs')
    if 'ifeq ($(HAVE_SQLITE),yes)\nGDAL_FORMATS := $(GDAL_FORMATS) rasterlite mbtiles\nendif' not in options:
        raise ValueError('actual raster SQLite gate differs')
    ogrmake=(root/'gdal-kml-build/ogr/ogrsf_frmts/GNUmakefile').read_text()
    if not re.search(r'^SUBDIRS-\$\(HAVE_SQLITE\)\s*\+=\s*gpkg\s*$',ogrmake,re.M):
        raise ValueError('actual GeoPackage SQLite gate differs')
    symbols=(root/'private-expat-symbols.log').read_text()
    if 'Symbol table' not in symbols or any(re.search(r'\b'+name+r'\b',symbols) for name in ('GDALRegister_MBTiles','RegisterOGRGeoPackage','RegisterOGRSQLite')):
        raise ValueError('SQLite driver registration symbols present')

def successful_receipt(config):
    receipt_path=checked(config['producer_receipt'],config['producer_receipt_sha256'])
    root=receipt_path.parent
    if receipt_path.name!='complete.json' or root.resolve()!=root.absolute() or (root/'failed.json').exists():
        raise ValueError('successful producer requires its genuine completed execution')
    producer=validator().producer
    data=producer.replay(root)  # Existing strict public replay: recipe, products, inputs, maps, GNU tree.
    recipe_sha=hashlib.sha256(json.dumps(data['recipe'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if recipe_sha!=config['producer_recipe_sha256'] or not all(data.get(key) is True for key in
            ('genuine_gdal_jni','kml_profile_enabled','strict_jni_diagnostics_free')) or data.get('gdal_version')!='2.4.4' or (type(data.get('checked_jni_warning_count')) is not int or data['checked_jni_warning_count']!=0):
        raise ValueError('successful reduced producer profile/source binding differs')
    expected_maps={str(root/'lib'/name):sha for name,sha in data['products'].items()}
    actual_maps={path:sha for path,sha in data['mapped_providers'].items() if 'gdal' in Path(path).name}
    if actual_maps!=expected_maps:raise ValueError('successful producer actual GDAL maps differ')
    log=(root/'probe.log').read_text()
    markers=('GDAL_JNI_VERSION_REGISTER_MEM_EXACT_WGS84_INTERRUPT_MISSING_FILE=true',
             'PASS_REAL_GDAL_ENUMERATION_PROGRESS_ORIGINAL_THROWABLE_CONTROLS',
             'PASS_GDAL_KML_DRIVERS_COORDINATES_ORIGINAL_THROWABLES')
    if producer.diagnostics.strict_jni_failures(log) or any(log.splitlines().count(marker)!=1 for marker in markers):
        raise ValueError('successful producer actual checked JNI controls differ')
    verify_reduced_closure(root,data['kml_build']['buildInventory'],data['gdal_archive_objects'],data['checked_jni_warning_count'])
    dynamic={};elf_hashes={}
    for name in data['products']:
        path=root/('dynamic-'+name+'.log')
        dynamic[name]=producer.audit_dynamic(root/'lib'/name,path.read_text());elf_hashes[path.name]=digest(path)
    if dynamic!=data['dynamic_needed']:raise ValueError('successful producer ELF audit differs')
    metadata={'profile':PROFILE,'producer_kind':'successful','producer_receipt_sha256':config['producer_receipt_sha256'],
              'producer_recipe_sha256':recipe_sha,'original_producer_success':True,'original_failure_preserved':False,
              'fresh_native_build':True,'products':data['products'],'native_driver_absence_runtime_qualified':False,
              'dynamic_needed':dynamic,'elf_inspection_hashes':elf_hashes}
    return root,data['products'],data['mapped_providers'],metadata,[receipt_path,root,*[Path(path) for path in data['bound_files']],
        *[Path(path) for path in data['mapped_providers']]]

def inspect(declaration, expected):
    declaration=checked(declaration,expected);config=json.loads(declaration.read_text())
    kind=declaration_kind(config)
    if kind=='successful':
        root,hashes,mapped,metadata,inputs=successful_receipt(config)
        products={name:checked(root/'lib'/name,sha) for name,sha in hashes.items()}
        if set(products)!={'libgdal.so','libgdalalljni.so'}:raise ValueError('exact two GDAL products required')
        metadata['declaration_sha256']=expected;metadata['validator_source_closure']=source_closure()
        return products,metadata,mapped,[declaration,*inputs]
    return historical_receipt(declaration,expected,config)

def historical_receipt(declaration, expected, config):
    plan_path = checked(config['finalization_plan'], config['finalization_plan_sha256'])
    receipt_path = checked(config['finalization_receipt'], config['finalization_receipt_sha256'])
    plan = json.loads(plan_path.read_text()); receipt = json.loads(receipt_path.read_text())
    finalizer = validator()
    for path, sha in plan['validatorInputs'].items():
        checked(path, sha)
    if receipt['planSha256'] != config['finalization_plan_sha256'] or receipt['originalEvidenceInventorySha256'] != plan['expectedInventorySha256']:
        raise ValueError('finalization plan/inventory identity differs')
    if receipt['originalExecutionRoot'] != plan['originalRoot'] or receipt['originalFailedReceiptSha256'] != plan['originalFailedSha256'] or receipt['originalSourceCommit'] != plan['originalSourceCommit']:
        raise ValueError('finalization execution lineage differs')
    observed = finalizer.validate(plan)
    if receipt['validationStatus'] != 'PASS' or receipt['originalProducerSuccess'] is not False or receipt['checks'] != observed:
        raise ValueError('actual finalization receipt/checks differ')
    root = Path(plan['originalRoot'])
    inventory=json.loads(Path(plan['expectedInventoryFile']).read_text())
    verify_reduced_closure(root,inventory['gnuBuild'],observed['actualGdalArchiveObjects'],observed['strictJniDiagnosticCount'])
    products = {name: checked(root/'lib'/name, sha) for name, sha in observed['products'].items()}
    if set(products) != {'libgdal.so', 'libgdalalljni.so'}:
        raise ValueError('exact two GDAL products required')
    metadata = {'profile': PROFILE, 'producer_kind':'historical-finalized', 'validator_source_closure':source_closure(), 'declaration_sha256': expected,
                'finalization_plan_sha256': config['finalization_plan_sha256'],
                'finalization_receipt_sha256': config['finalization_receipt_sha256'],
                'original_producer_success': False, 'original_failure_preserved': True,
                'fresh_native_build': False, 'products': observed['products'],
                'native_driver_absence_runtime_qualified': False,
                'dynamic_needed': observed['dynamicNeeded'], 'elf_inspection_hashes': observed['elfInspectionHashes']}
    inputs=[declaration,plan_path,receipt_path,root,Path(plan['repository']),Path(plan['expectedInventoryFile']),Path(plan['kmlBindings']),*[Path(x) for x in plan['validatorInputs']]]
    return products, metadata, observed['mappedProviders'], inputs
