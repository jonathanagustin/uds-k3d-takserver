#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Build the real KernelScene subset from a validated local GIS producer contract."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scene_kernel_build', HERE / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
REQUIRED_BINDINGS = {'configuration.json','gdal-build/GDALmake.opt','gdal-build/port/cpl_config.h',
    'sources.json','minizip/libminizip.a','minizip/libminizip-pic.so','minizip/minizip-probe',
    'minizip-positive-controls.log','minizip-strict-link.log'}


def archive_members(path):
    """Hash real GNU ar object bodies, not a filename/opaque archive assertion."""
    values = []
    with path.open('rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError('not a regular GNU ar archive')
        while True:
            header = stream.read(60)
            if not header:
                break
            if len(header) != 60 or header[-2:] != b'`\n':
                raise ValueError('truncated archive header')
            size = int(header[48:58].strip())
            if not 0 <= size <= 16*1024**2:
                raise ValueError('archive member exceeds bound')
            data = stream.read(size)
            if len(data) != size:
                raise ValueError('truncated archive member')
            name = header[:16].strip()
            if name not in (b'/', b'//'):
                if data[:6] != b'\x7fELF\x02\x01':
                    raise ValueError('non-object archive member')
                values.append(hashlib.sha256(data).hexdigest())
            if size % 2 and len(stream.read(1)) != 1:
                raise ValueError('truncated archive padding')
    return Counter(values)


def reference_sources(args, output, lock, run):
    reference = output / 'source-reference'
    reference.mkdir()
    build.unpack(args.gdal_archive, reference/'gdal', lock['gdal'])
    build.unpack(args.libkml_archive, reference/'libkml', lock['libkml'])
    roots = {'gdal-disable-pdf.patch':('gdal/gdal',1),
        'gdal-libtool-normalizer.patch':('gdal/gdal',1),
        'libkml-pgsc.patch':('libkml/libkml-1.3',0),
        'minizip-zlib-crc-type.patch':('libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip',1)}
    for name,(root,level) in roots.items():
        patch=HERE/'patches'/name
        if build.native.digest(patch)!=lock['patches'][name]['sha256']:
            raise ValueError('reference patch differs')
        run(['/usr/bin/patch','--batch','--fuzz=0','-p'+str(level),'-d',reference/root,'-i',patch],
            'reference-'+name)
    if (build.native.digest(reference/'gdal/gdal/LICENSE.TXT')!=lock['licenses']['gdal'] or
            build.native.digest(reference/'libkml/libkml-1.3/COPYING')!=lock['licenses']['libkml']):
        raise ValueError('reference license differs')
    return build.inventory(reference)


def verify_producer(args, reference, deps):
    root=args.dependency_root.resolve()
    receipt_path=args.dependency_proof/'dependencies-built.json'
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size>8*1024**2:
        raise ValueError('bounded regular dependency receipt required')
    data=build.producer.normalize(json.loads(receipt_path.read_text()))
    if data.get('schema_exercise_only'):
        raise ValueError('schema exercise is not a completed producer')
    if build.native.digest(args.dependency_proof/'sources.json')!=data['source_postimages_sha256']:
        raise ValueError('source postimage manifest changed')
    if type(data.get('fresh_build')) is not bool or data.get('kernel_scene_acceptance') is not False:
        raise ValueError('completed dependency producer contract required')
    recipe=data['producer_recipe']
    if not isinstance(recipe,dict) or not recipe:
        raise ValueError('dependency producer identity missing')
    for name,sha in recipe.items():
        # Historical helper-relative paths have one reviewed parent component.
        if name.startswith('../'):
            relative='parent/'+str(build.native.relative(name[3:]))
        else:
            relative=str(build.native.relative(name))
        path=args.dependency_producer/relative
        if path.is_symlink() or not path.is_file() or build.native.digest(path)!=sha:
            raise ValueError('dependency producer recipe bytes differ')
    source=build.inventory(root/'source')
    if source!=reference or data['source_postimages']!=reference:
        raise ValueError('dependency sources differ from pinned archives and project patches')
    if build.native.inventory(root/'gdal-install')!=data['gdal_installed']:
        raise ValueError('installed GDAL inventory differs')
    bindings=data['bindings']
    if set(bindings['files'])!=REQUIRED_BINDINGS:
        raise ValueError('missing or unknown dependency binding')
    for name,sha in bindings['files'].items():
        path=root/name
        if path.is_symlink() or not path.is_file() or build.native.digest(path)!=sha:
            raise ValueError('configuration/minizip binding differs')
    if bindings['normalizer_sha256']!=build.native.digest(HERE/'normalize_la.py'):
        raise ValueError('normalizer identity differs')
    lock=json.loads((HERE/'inputs.lock.json').read_text())
    if bindings['gdal_makefile_sha256']!=lock['patches']['gdal-libtool-normalizer.patch']['after_sha256']:
        raise ValueError('normalizer rule identity differs')
    for path,sha in bindings['tools'].items():
        if build.native.digest(Path(path))!=sha:
            raise ValueError('dependency producer tool changed')
    configuration=json.loads((root/'configuration.json').read_text())
    expected=[str(root/'gdal-build/configure'),'--prefix='+str(root/'gdal-install'),
        '--with-proj='+str(args.proj_proof.resolve()/'install'),
        '--with-libz='+str(args.assimp_proof.resolve()/'zlib-install'),*build.CONFIGURE]
    if configuration['args']!=expected or configuration['dependencies']!=deps:
        raise ValueError('dependency configure contract differs')
    opts=(root/'gdal-build/GDALmake.opt').read_text()
    if not re.search(r'^PROJ_STATIC\s*=\s*yes$',opts,re.M) or '-DPROJ_VERSION=4' not in opts:
        raise ValueError('legacy static PROJ contract missing')
    if (root/'minizip-positive-controls.log').read_bytes()!=b'real_minizip_binary_crc_correct_and_wrong_password_controls=true\n':
        raise ValueError('actual minizip controls missing')
    if build.native.digest(root/'gdal-install/include/cpl_vsi.h')!=reference['gdal/gdal/port/cpl_vsi.h']['sha256']:
        raise ValueError('installed VSI header differs')
    version=(root/'gdal-install/include/gdal_version.h').read_text()
    for name,value in [('MAJOR',2),('MINOR',4),('REV',4)]:
        if not re.search(r'#\s*define GDAL_VERSION_'+name+r'\s+'+str(value)+r'\s*$',version,re.M):
            raise ValueError('installed GDAL API version differs')
    objects=data['objects_after']
    actual={str(p.relative_to(root/'gdal-build')):{'bytes':p.stat().st_size,'sha256':build.native.digest(p)}
            for p in (root/'gdal-build').rglob('*.o') if not p.is_symlink()}
    if actual!=objects:
        raise ValueError('compiled dependency objects differ')
    if archive_members(root/'gdal-install/lib/libgdal.a')!=Counter(v['sha256'] for v in objects.values()):
        raise ValueError('installed archive is not the actual produced object closure')
    return {'receipt_sha256':build.native.digest(receipt_path),'producer_recipe':recipe,
        'fresh_build':data['fresh_build'],'lineage':data.get('producer_lineage'),
        'installed':data['gdal_installed'],'bindings':bindings}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','source','dependency_root','dependency_proof','dependency_producer',
                 'gdal_archive','libkml_archive','proj_proof','assimp_proof'):
        parser.add_argument('--'+name.replace('_','-'),type=Path,required=True)
    args=parser.parse_args()
    output=build.validate_output(args.output,[args.source,args.dependency_root,args.dependency_proof,
        args.dependency_producer,args.gdal_archive,args.libkml_archive,args.proj_proof,args.assimp_proof,HERE])
    output.mkdir()
    initial=build.recipe()
    lock=json.loads((HERE/'inputs.lock.json').read_text())
    if lock['kernel_tus']!=build.KERNEL_TUS or len(build.KERNEL_TUS)!=35:
        raise ValueError('unreviewed Kernel source closure')
    deps={family:build.verify_dependency(proof,family) for family,proof in
          [('proj',args.proj_proof),('assimp',args.assimp_proof)]}
    cc,cxx=Path('/usr/bin/gcc').resolve(),Path('/usr/bin/g++').resolve()
    env=build.assimp.environment(str(cc),str(cxx))
    for key in list(env):
        if key.startswith(('PROJ_','GDAL_','PKG_CONFIG','BASH_FUNC_')) or key in (
            'MAKEFLAGS','MFLAGS','GNUMAKEFLAGS','MAKEFILES','CONFIG_SITE','CONFIG_SHELL',
            'CPATH','LIBRARY_PATH','LD_LIBRARY_PATH','LD_PRELOAD','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH'):
            env.pop(key)
    env.update(CC=str(cc),CXX=str(cxx),PKG_CONFIG_PATH='',PKG_CONFIG_LIBDIR=str(output/'no-pkgconfig'))
    deadline=time.monotonic()+1200
    commands=[]
    def run(command,name,timeout=60,capture=False):
        remaining=deadline-time.monotonic()
        if remaining<=0: raise ValueError('Kernel-only deadline exhausted')
        commands.append({'name':name,'command':list(map(str,command))})
        (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        value=build.native.run(list(map(str,command)),output,name,min(timeout,remaining),env,capture)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and not p.is_symlink())>4*1024**3:
            raise ValueError('Kernel-only output bound exceeded')
        return value
    try:
        reference=reference_sources(args,output,lock,run)
        accepted=verify_producer(args,reference,deps)
        (output/'accepted-dependency.json').write_text(json.dumps(accepted,sort_keys=True)+'\n')
        frozen=output/'source';frozen.mkdir()
        root=args.dependency_root.resolve()
        build.kernel_stage(args,output,run,lock,initial,deps,frozen,reference,
            root/'source/libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip',args.assimp_proof/'zlib-install',
            root/'minizip/libminizip.a',root/'gdal-install',cxx,env,args.dependency_proof/'dependencies-built.json',root/'source')
        if verify_producer(args,reference,deps)!=accepted:
            raise ValueError('dependency producer changed during Kernel integration')
        result=json.loads((output/'complete.json').read_text())
        result['dependency_producer']=accepted
        result['kernel_recipe']=initial
        result['fresh_kernel_build']=True
        (output/'complete.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception:
        if (output/'complete.json').exists(): (output/'complete.json').unlink()
        (output/'failed.json').write_text(json.dumps({'kernel_scene_acceptance':False,
            'last_command':commands[-1]['name'] if commands else None,'kernel_recipe':initial},indent=2)+'\n')
        raise


if __name__=='__main__':
    main()
