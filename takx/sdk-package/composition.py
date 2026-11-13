# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Explicit SDK composition; baseline native producer/provider APIs stay strict."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

PROFILE = 'public-cpu-gdal244-kml-v1'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise ValueError('composition input differs: ' + str(path))
    return path

def inspect(declaration, expected):
    """Replay public finalizer validation without writing or rerunning native code."""
    declaration = checked(declaration, expected)
    config = json.loads(declaration.read_text())
    if set(config) != {'schema', 'profile', 'finalization_plan', 'finalization_plan_sha256', 'finalization_receipt', 'finalization_receipt_sha256'} or config['schema'] != 1 or config['profile'] != PROFILE:
        raise ValueError('explicit supported composition declaration required')
    plan_path = checked(config['finalization_plan'], config['finalization_plan_sha256'])
    receipt_path = checked(config['finalization_receipt'], config['finalization_receipt_sha256'])
    plan = json.loads(plan_path.read_text()); receipt = json.loads(receipt_path.read_text())
    validator = Path(__file__).parent.parent/'native-gdal-jni/finalization_validation.py'
    # The original CLI validator source identity remains in the old receipt.
    # This owned read-only API independently revalidates its original execution.
    spec = importlib.util.spec_from_file_location('sdk_composition_finalizer', validator)
    finalizer = importlib.util.module_from_spec(spec); spec.loader.exec_module(finalizer)
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
    options = (root/'gdal-kml-build/GDALmake.opt').read_text()
    if not re.search(r'^HAVE_SQLITE\s*=\s*no\s*$', options, re.M):
        raise ValueError('reduced profile requires SQLite drivers compiled out')
    if observed['actualGdalArchiveObjects'] != 1073 or observed['strictJniDiagnosticCount'] != 0:
        raise ValueError('actual reduced native closure differs')
    inventory=json.loads(Path(plan['expectedInventoryFile']).read_text())
    objects=[name for name in inventory['gnuBuild']['regularFiles'] if name.endswith('.o')]
    if len(objects)!=1073 or any(re.search(r'(?:mbtiles|gpkg|sqlite)',name,re.I) for name in objects):
        raise ValueError('actual reduced object inventory contains SQLite driver bodies')
    if 'ifeq ($(HAVE_SQLITE),yes)\nGDAL_FORMATS := $(GDAL_FORMATS) rasterlite mbtiles\nendif' not in options:
        raise ValueError('actual raster SQLite gate differs')
    ogrmake=(root/'gdal-kml-build/ogr/ogrsf_frmts/GNUmakefile').read_text()
    if not re.search(r'^SUBDIRS-\$\(HAVE_SQLITE\)\s*\+=\s*gpkg\s*$',ogrmake,re.M):
        raise ValueError('actual GeoPackage SQLite gate differs')
    symbols = (root/'private-expat-symbols.log').read_text()
    if 'Symbol table' not in symbols or any(re.search(r'\b'+name+r'\b', symbols) for name in ('GDALRegister_MBTiles','RegisterOGRGeoPackage','RegisterOGRSQLite')):
        raise ValueError('SQLite driver registration symbols present')
    products = {name: checked(root/'lib'/name, sha) for name, sha in observed['products'].items()}
    if set(products) != {'libgdal.so', 'libgdalalljni.so'}:
        raise ValueError('exact two GDAL products required')
    metadata = {'profile': PROFILE, 'declaration_sha256': expected,
                'finalization_plan_sha256': config['finalization_plan_sha256'],
                'finalization_receipt_sha256': config['finalization_receipt_sha256'],
                'original_producer_success': False, 'original_failure_preserved': True,
                'fresh_native_build': False, 'products': observed['products'],
                'native_driver_absence_runtime_qualified': False,
                'dynamic_needed': observed['dynamicNeeded'], 'elf_inspection_hashes': observed['elfInspectionHashes']}
    inputs=[declaration,plan_path,receipt_path,root,Path(plan['repository']),Path(plan['expectedInventoryFile']),Path(plan['kmlBindings']),*[Path(x) for x in plan['validatorInputs']]]
    return products, metadata, observed['mappedProviders'], inputs
