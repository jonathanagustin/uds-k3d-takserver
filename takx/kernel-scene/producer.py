#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Shared local GIS producer contract; integrity evidence, not authentication."""
import importlib.util
import json
from pathlib import Path
import re
import shutil

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('scene_producer_native',HERE.parent/'native-deps/build.py')
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
CONTRACT='kernel-scene-gis-v1'
FILES=('configuration.json','gdal-build/GDALmake.opt','gdal-build/port/cpl_config.h','sources.json',
    'minizip/libminizip.a','minizip/libminizip-pic.so','minizip/minizip-probe',
    'minizip-positive-controls.log','minizip-strict-link.log')
SHA=re.compile('[0-9a-f]{64}')


def normalize(data):
    """Accept the recorded pre-schema producer without inventing missing facts."""
    result=dict(data)
    if 'schema_version' not in result:
        result['schema_version']=1
        result['contract']=CONTRACT
        result['producer_recipe']=result.get('producer_recipe') or result.get('producer_lineage',{}).get('current_recipe')
        result['schema_exercise_only']=False
    if result.get('schema_version')!=1 or result.get('contract')!=CONTRACT:
        raise ValueError('unsupported producer contract')
    if type(result.get('fresh_build')) is not bool or result.get('kernel_scene_acceptance') is not False:
        raise ValueError('explicit dependency freshness/acceptance required')
    if type(result.get('schema_exercise_only',False)) is not bool:
        raise ValueError('invalid schema exercise marker')
    if not result['fresh_build'] and not isinstance(result.get('producer_lineage'),dict):
        raise ValueError('resumed producer lineage required')
    recipe=result.get('producer_recipe')
    if not isinstance(recipe,dict) or not recipe:
        raise ValueError('producer recipe missing')
    for name,sha in recipe.items():
        native.relative(name[3:] if name.startswith('../') else name)
        if not isinstance(sha,str) or not SHA.fullmatch(sha):
            raise ValueError('invalid producer recipe digest')
    bindings=result.get('bindings',{})
    if set(bindings.get('files',{}))!=set(FILES) or not bindings.get('tools'):
        raise ValueError('incomplete configuration/product/tool contract')
    hashes=[*bindings['files'].values(),*bindings['tools'].values(),bindings.get('normalizer_sha256'),
        bindings.get('gdal_makefile_sha256'),result.get('source_postimages_sha256')]
    if any(not isinstance(x,str) or not SHA.fullmatch(x) for x in hashes):
        raise ValueError('invalid producer fact digest')
    if not result.get('source_postimages') or not result.get('gdal_installed') or not result.get('objects_after'):
        raise ValueError('source/install/object contract missing')
    return result


def emit(root, output, recipe, source_postimages, tools, lineage, fresh_build,
         producer_root=HERE, preserved_producer=False, schema_exercise=False):
    """All entrypoints emit the same facts, retaining actual producer identity."""
    if type(fresh_build) is not bool or (not fresh_build and not isinstance(lineage,dict)):
        raise ValueError('accurate producer freshness and lineage required')
    root,output=Path(root),Path(output)
    files={name:native.digest(root/name) for name in FILES}
    if (root/'minizip-positive-controls.log').read_bytes()!=b'real_minizip_binary_crc_correct_and_wrong_password_controls=true\n':
        raise ValueError('actual minizip control missing')
    actual=native.inventory(root/'source')
    if any('symlink' in item for item in actual):
        raise ValueError('producer source symlink refused')
    if {x['path']:{'bytes':x['bytes'],'sha256':x['sha256']} for x in actual}!=source_postimages:
        raise ValueError('producer source inventory differs')
    for path,sha in tools.items():
        if native.digest(Path(path))!=sha:
            raise ValueError('producer tool changed')
    sources=output/'sources.json'
    sources.write_text(json.dumps(source_postimages,sort_keys=True)+'\n')
    producer=output/'producer'
    producer.mkdir()
    for name,sha in recipe.items():
        native.relative(name[3:] if name.startswith('../') else name)
        relative=name.replace('../','parent/')
        source=Path(producer_root)/(relative if preserved_producer else name)
        if source.is_symlink() or native.digest(source)!=sha:
            raise ValueError('producer recipe bytes changed')
        target=producer/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    objects={str(p.relative_to(root/'gdal-build')):{'bytes':p.stat().st_size,'sha256':native.digest(p)}
             for p in (root/'gdal-build').rglob('*.o') if not p.is_symlink()}
    if any(p.is_symlink() for p in (root/'gdal-build').rglob('*.o')):
        raise ValueError('producer object symlink refused')
    data={'schema_version':1,'contract':CONTRACT,'fresh_build':fresh_build,
        'schema_exercise_only':schema_exercise,'producer_recipe':recipe,'producer_lineage':lineage,
        'receipt_emitter_sha256':native.digest(HERE/'producer.py'),
        'source_postimages':source_postimages,'source_postimages_sha256':native.digest(sources),
        'gdal_installed':native.inventory(root/'gdal-install'),'objects_after':objects,
        'bindings':{'files':files,'tools':tools,'normalizer_sha256':native.digest(HERE/'normalize_la.py'),
                    'gdal_makefile_sha256':native.digest(root/'gdal-build/GNUmakefile')},
        'kernel_scene_acceptance':False}
    normalize(data)
    path=output/'dependencies-built.json'
    path.write_text(json.dumps(data,sort_keys=True)+'\n')
    return path
