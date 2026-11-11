#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""One reviewed metadata/install continuation after an unavailable newline tool."""
import argparse
import importlib.util
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('scene_metadata_resume', HERE / 'resume.py')
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
build = resume.build
SNAPSHOT_SHA = 'b9b6025783b3592e951ea153839d19e792f736905116017d51cc449edd8648c7'


def check_snapshot(original, previous, snapshot, manifest):
    if manifest.is_symlink() or build.native.digest(manifest) != SNAPSHOT_SHA:
        raise ValueError('metadata snapshot manifest differs')
    if build.native.inventory(snapshot) != json.loads(manifest.read_text()):
        raise ValueError('metadata snapshot changed')
    if (build.native.inventory(original) != build.native.inventory(snapshot / 'working') or
            build.native.inventory(previous) != build.native.inventory(snapshot / 'producer-output')):
        raise ValueError('metadata producer input changed')
    links = [(str(p.relative_to(original)), str(p.readlink())) for p in original.rglob('*') if p.is_symlink()]
    if links != [('gdal-build/.libs/libgdal.la', '../libgdal.la')]:
        raise ValueError('unexpected producer symlink')
    failed = json.loads((previous / 'failed.json').read_text())
    if (failed['stage'], failed['last_command'], failed['kernel_scene_acceptance']) != ('resumed-gdal', 'gdal-resumed-build', False):
        raise ValueError('not the reviewed missing-tool producer')
    for name, sha in failed['resumed_recipe'].items():
        path = snapshot / 'producer-recipe' / name.replace('../', 'parent/')
        if path.is_symlink() or build.native.digest(path) != sha:
            raise ValueError('previous producer bytes changed')
    return failed['resumed_recipe']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original','previous','snapshot','manifest','output','source','proj_proof','assimp_proof'):
        parser.add_argument('--' + name.replace('_','-'), type=Path, required=True)
    args = parser.parse_args()
    output = build.validate_output(args.output, [args.original,args.previous,args.snapshot,args.manifest,
        args.source,args.proj_proof,args.assimp_proof,HERE])
    previous_recipe = check_snapshot(args.original,args.previous,args.snapshot,args.manifest)
    deps = {family:build.verify_dependency(proof,family) for family,proof in
        [('proj',args.proj_proof),('assimp',args.assimp_proof)]}
    old_lineage = json.loads((args.previous / 'lineage.json').read_text())
    tools = old_lineage['dependency_bindings_before']['tools']
    for path,sha in tools.items():
        if build.native.digest(Path(path)) != sha:
            raise ValueError('metadata tool changed')
    if resume.dependency_bindings(args.original,tools) != old_lineage['dependency_bindings_before']:
        raise ValueError('preexisting source/config/minizip bindings changed')
    configuration = json.loads((args.original / 'configuration.json').read_text())
    if configuration['args'][0] != str(args.original.resolve() / 'gdal-build/configure'):
        raise ValueError('absolute producer path differs')
    source = args.original / 'source'
    old_sources = json.loads((args.original / 'sources.json').read_text())
    if build.inventory(source) != old_sources:
        raise ValueError('source postimages changed')
    work = args.original / 'gdal-build'
    # Include all produced .o, without following the one known metadata symlink.
    object_inventory = {str(p.relative_to(work)):{'bytes':p.stat().st_size,'sha256':build.native.digest(p)}
                        for p in work.rglob('*.o') if not p.is_symlink()}
    if len(object_inventory) != 1056 or any(not resume.relocatable(work/name) for name in object_inventory):
        raise ValueError('completed object inventory differs')
    archive = work / '.libs/libgdal.a'
    archive_sha = build.native.digest(archive)
    lock = json.loads((HERE / 'inputs.lock.json').read_text())
    entry = lock['patches']['gdal-libtool-normalizer.patch']
    patch = HERE / 'patches/gdal-libtool-normalizer.patch'
    normalizer = HERE / 'normalize_la.py'
    for target in (work / 'GNUmakefile', source / 'gdal/gdal/GNUmakefile'):
        if build.native.digest(target) != entry['before_sha256']:
            raise ValueError('GNUmakefile preimage differs')
    if build.native.digest(patch) != entry['sha256'] or build.native.digest(normalizer) != lock['normalizer_sha256']:
        raise ValueError('normalizer recipe differs')
    output.mkdir()
    initial = build.recipe()
    cc,cxx = Path('/usr/bin/gcc').resolve(),Path('/usr/bin/g++').resolve()
    env = build.assimp.environment(str(cc),str(cxx))
    for key in list(env):
        if key.startswith(('PROJ_','GDAL_','PKG_CONFIG','BASH_FUNC_')) or key in (
            'MAKEFLAGS','MFLAGS','GNUMAKEFLAGS','MAKEFILES','CONFIG_SITE','CONFIG_SHELL',
            'CPATH','LIBRARY_PATH','LD_LIBRARY_PATH','LD_PRELOAD','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH'):
            env.pop(key)
    env.update(CFLAGS='-O2 -fPIC',CXXFLAGS='-O2 -fPIC',CONFIG_SITE='/dev/null',
        PKG_CONFIG_LIBDIR=str(output/'no-pkgconfig'),PKG_CONFIG_PATH='',CC=str(cc),CXX=str(cxx),
        KERNEL_SCENE_PYTHON='/usr/bin/python3',KERNEL_SCENE_NORMALIZER=str(normalizer))
    python = Path('/usr/bin/python3').resolve()
    tools = {**tools,str(python):build.native.digest(python)}
    stage,deadline,commands = 'metadata-install',time.monotonic()+300,[]

    def run(command,name,timeout=60,capture=False):
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise ValueError('metadata stage deadline exceeded')
        commands.append({'stage':stage,'name':name,'command':list(map(str,command))})
        (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        value=build.native.run(list(map(str,command)),output,name,min(timeout,remaining),env,capture)
        if sum(p.stat().st_size for root in (args.original,output) for p in root.rglob('*')
               if p.is_file() and not p.is_symlink())>4*1024**3:
            raise ValueError('metadata output bound exceeded')
        return value

    lineage={'fresh_build':False,'previous_producer_recipe':previous_recipe,'current_recipe':initial,
        'missing_tool_snapshot_manifest_sha256':SNAPSHOT_SHA,'previous_lineage':old_lineage,
        'objects_before':object_inventory,'archive_before_sha256':archive_sha,'metadata_seconds':300,
        'total_gdal_compile_bound_seconds':2400,'normalizer_sha256':lock['normalizer_sha256']}
    (output/'lineage.json').write_text(json.dumps(lineage,sort_keys=True)+'\n')
    try:
        # Only the two known Makefiles change; C/C++ and compiler flags remain identical.
        for name,root in [('build',work),('source',source/'gdal/gdal')]:
            run(['/usr/bin/patch','--batch','--fuzz=0','-p1','-d',root,'-i',patch],'patch-normalizer-'+name)
            if build.native.digest(root/'GNUmakefile')!=entry['after_sha256']:
                raise ValueError('GNUmakefile postimage differs')
        new_sources=build.inventory(source)
        expected=dict(old_sources)
        expected['gdal/gdal/GNUmakefile']={'bytes':(source/'gdal/gdal/GNUmakefile').stat().st_size,
                                         'sha256':entry['after_sha256']}
        if new_sources!=expected:
            raise ValueError('unexpected source modification')
        (output/'sources.json').write_text(json.dumps(new_sources,sort_keys=True)+'\n')
        # Failed make left a completed .la target. Remove only its exact owned
        # generated metadata and its known internal link so normalization reruns.
        metadata={}
        for relative in ('gdal-build/libgdal.la','gdal-build/.libs/libgdal.la'):
            path=args.original/relative
            metadata[relative]={'sha256':build.native.digest(path),'symlink':str(path.readlink()) if path.is_symlink() else None}
        (output/'removed-generated-metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (work/'.libs/libgdal.la').unlink()
        (work/'libgdal.la').unlink()
        run(['/usr/bin/make','-C',work,'-j1','libgdal.la'],'gdal-metadata-build',300)
        after_objects={str(p.relative_to(work)):{'bytes':p.stat().st_size,'sha256':build.native.digest(p)}
                       for p in work.rglob('*.o') if not p.is_symlink()}
        if after_objects!=object_inventory:
            raise ValueError('metadata continuation changed compiled objects')
        (args.original/'gdal-install/lib').mkdir(parents=True,exist_ok=True)
        run(['/usr/bin/make','-C',work,'-j1','install-static-lib'],'gdal-metadata-install',180)
        if {str(p.relative_to(work)):{'bytes':p.stat().st_size,'sha256':build.native.digest(p)}
                for p in work.rglob('*.o') if not p.is_symlink()} != object_inventory:
            raise ValueError('static installation changed compiled objects')
        if b'\r' in (work/'libgdal.la').read_bytes():
            raise ValueError('generated metadata is not LF normalized')
        if build.inventory(source)!=new_sources or build.recipe()!=initial:
            raise ValueError('metadata source/recipe changed')
        bound=resume.dependency_bindings(args.original,tools)
        bound['normalizer_sha256']=lock['normalizer_sha256']
        bound['gdal_makefile_sha256']=entry['after_sha256']
        receipt=build.producer.emit(args.original,output,initial,new_sources,tools,lineage,False)
        stage,deadline='kernel-scene',time.monotonic()+1200
        frozen=output/'source';frozen.mkdir()
        build.kernel_stage(args,output,run,lock,initial,deps,frozen,new_sources,
            source/'libkml/libkml-1.3/third_party/zlib-1.2.3/contrib/minizip',args.assimp_proof/'zlib-install',
            args.original/'minizip/libminizip.a',args.original/'gdal-install',cxx,env,receipt,source)
        if build.recipe()!=initial or build.inventory(source)!=new_sources:
            raise ValueError('source/recipe changed during Kernel execution')
        result=json.loads((output/'complete.json').read_text());result['fresh_build']=False
        result['producer_lineage_sha256']=build.native.digest(output/'lineage.json')
        (output/'complete.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception:
        if (output/'complete.json').exists(): (output/'complete.json').unlink()
        (output/'failed.json').write_text(json.dumps({'stage':stage,'kernel_scene_acceptance':False,
            'last_command':commands[-1]['name'] if commands else None,'recipe':initial},indent=2)+'\n')
        raise


if __name__=='__main__':
    main()
