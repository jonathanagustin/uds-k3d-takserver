# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('worldwind_recipe', HERE / 'build.py')
recipe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recipe)


def jdk_resources(jar, expected):
    """Read bytes through the actual JVM resource loader without class init."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        harness = root / 'ResourceProbe.java'
        harness.write_text('''import java.net.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
public class ResourceProbe {
 public static void main(String[] args) throws Exception {
  try (URLClassLoader loader = new URLClassLoader(new URL[]{Path.of(args[0]).toUri().toURL()}, null)) {
   for (int i=1; i<args.length; i+=2) {
    try (var input = loader.getResourceAsStream(args[i])) {
     if (input == null || !HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
          .digest(input.readAllBytes())).equals(args[i+1])) throw new AssertionError(args[i]);
    }
   }
  }
 }
}''')
        subprocess.run(['javac', '--release', '17', '-d', str(root), str(harness)], check=True)
        pairs = [value for pair in sorted(expected.items()) for value in pair]
        subprocess.run(['java', '-cp', str(root), 'ResourceProbe', str(jar), *pairs], check=True)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((HERE / 'inputs.lock.json').read_text())

    def test_inventory_and_project_adaptations(self):
        recipe.validate(self.lock)
        bad = copy.deepcopy(self.lock)
        bad['project_inputs']['standard-gdal.patch'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'adaptation integrity'):
            recipe.validate(bad)
        bad = copy.deepcopy(self.lock)
        del bad['files'][next(p for p in bad['files'] if p.endswith('.java'))]
        with self.assertRaisesRegex(ValueError, 'complete examples'):
            recipe.validate(bad)

    def test_interop_is_explicit_and_bound_to_official_preimages(self):
        contract = recipe.interop_contract()
        self.assertEqual(contract['profile'], 'project-standard-gdal-rgb-interop')
        for name, record in contract['files'].items():
            self.assertEqual(record['before_sha256'], self.lock['files'][name])
            self.assertNotEqual(record['before_sha256'], record['after_sha256'])
        with patch.object(recipe, 'digest', return_value='0' * 64):
            with self.assertRaisesRegex(ValueError, 'interop profile integrity'):
                recipe.interop_contract()

    def test_timeout_retains_diagnostics_and_removes_partial_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'classes').mkdir()
            (root / 'classes/Partial.class').write_bytes(b'partial')
            (root / 'uds-takserver-worldwind-java.jar').write_bytes(b'partial')
            error = subprocess.TimeoutExpired(['javac'], 240, output=b'compiler output', stderr=b'compiler error')
            with patch.object(recipe.subprocess, 'run', side_effect=error):
                self.assertEqual(recipe.compile_checked(['javac'], root, {}, {}), 124)
            state = json.loads((root / 'build-state.json').read_text())
            self.assertIn('timed out', state['failure'])
            self.assertEqual((root / 'javac.stdout.log').read_bytes(), b'compiler output')
            self.assertEqual((root / 'javac.stderr.log').read_bytes(), b'compiler error')
            self.assertFalse((root / 'classes').exists())
            self.assertFalse((root / 'uds-takserver-worldwind-java.jar').exists())

    def test_dependency_mutation_rejected_after_successful_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'classes').mkdir()
            jar = root / 'dependency.jar'
            jar.write_bytes(b'original')
            expected = recipe.digest(jar)
            def compile_and_mutate(*args, **kwargs):
                (root / 'classes/Partial.class').write_bytes(b'class')
                jar.write_bytes(b'mutation')
                return subprocess.CompletedProcess(args[0], 0, b'', b'')
            with patch.object(recipe.subprocess, 'run', side_effect=compile_and_mutate):
                self.assertEqual(recipe.compile_checked(['javac'], root, {jar: expected}, {}), 1)
            state = json.loads((root / 'build-state.json').read_text())
            self.assertIn('dependency changed', state['failure'])
            self.assertFalse((root / 'classes').exists())
            self.assertFalse((root / 'uds-takserver-worldwind-java.jar').exists())

    def test_source_hash_mismatch_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'src').mkdir()
            (root / 'src/Test.java').write_bytes(b'wrong')
            lock = {'files': {'src/Test.java': recipe.hashlib.sha256(b'right').hexdigest()}}
            with patch.object(recipe.subprocess, 'check_output', side_effect=[
                    (recipe.REVISION + '\n').encode(), b'src/Test.java\n', b'']):
                with self.assertRaisesRegex(ValueError, 'source/resource integrity'):
                    recipe.snapshot(root, lock)
            self.assertEqual(list(root.rglob('*.class')), [])

    def test_deterministic_jar_and_resource_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = [Path(directory) / n for n in ('a.jar', 'b.jar')]
            recipe.write_jar(a, {'images/test': b'bytes', 'META-INF/upstream-notices/license': b'notice'})
            recipe.write_jar(b, {'META-INF/upstream-notices/license': b'notice', 'images/test': b'bytes'})
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as jar:
                self.assertEqual(jar.read('images/test'), b'bytes')
                self.assertEqual(jar.read('META-INF/upstream-notices/license'), b'notice')
            if shutil.which('javac') and shutil.which('java'):
                jdk_resources(a, {'images/test': recipe.hashlib.sha256(b'bytes').hexdigest()})

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_palette_argb_depth_and_invalid_inputs_without_gdal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / 'PaletteProbe.java'
            harness.write_text('''import gov.nasa.worldwind.util.gdal.ProjectPaletteColorModel;
import java.awt.image.*;
public class PaletteProbe {
 public static void main(String[] args) {
  for (int bits : new int[]{1, 8, 9, 16}) {
   int count = 1 << bits;
   IndexColorModel cm = ProjectPaletteColorModel.create(bits, count,
      i -> i == count - 1 ? 0x7f123456 : 0xffabcdef);
   if (cm.getPixelSize() != bits || cm.getRGB(count - 1) != 0x7f123456
       || cm.getRGB(0) != 0xffabcdef
       || cm.getTransferType() != (bits <= 8 ? DataBuffer.TYPE_BYTE : DataBuffer.TYPE_USHORT))
      throw new AssertionError("palette/depth loss");
   WritableRaster raster = cm.createCompatibleWritableRaster(1, 1);
   raster.setSample(0, 0, 0, count - 1);
   if (new BufferedImage(cm, raster, false, null).getRGB(0, 0) != 0x7f123456)
      throw new AssertionError("raster index truncation");
  }
  for (int[] invalid : new int[][]{{0,1},{17,1},{8,257},{8,0}}) {
   try { ProjectPaletteColorModel.create(invalid[0], invalid[1], i -> 0);
      throw new AssertionError("accepted invalid input");
   } catch (IllegalArgumentException expected) { }
  }
 }
}''')
            subprocess.run(['javac', '--release', '17', '-d', str(root),
                            str(HERE / 'ProjectPaletteColorModel.java'), str(harness)], check=True)
            subprocess.run(['java', '-Djava.awt.headless=true', '-cp', str(root), 'PaletteProbe'], check=True)

    @unittest.skipUnless(os.getenv('WORLDWIND_SOURCE') and os.getenv('WORLDWIND_GIS_BUILD')
                         and os.getenv('WORLDWIND_PUBLIC_JARS'), 'opt-in local complete source build')
    def test_real_complete_source_build(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'build'
            subprocess.run(['python3', str(HERE / 'build.py'), '--source', os.environ['WORLDWIND_SOURCE'],
                '--gis-build', os.environ['WORLDWIND_GIS_BUILD'], '--public-jars', os.environ['WORLDWIND_PUBLIC_JARS'],
                '--output', str(out)], check=True)
            state = json.loads((out / 'build-state.json').read_text())
            self.assertEqual(state['java_sources'], 1727)
            self.assertEqual(state['exit_code'], 0)
            self.assertFalse(state['native_built_or_loaded'])
            with zipfile.ZipFile(out / state['artifact']['name']) as jar:
                self.assertIn('gov/nasa/worldwindx/examples/ApplicationTemplate.class', jar.namelist())
                self.assertIn('gov/nasa/worldwind/util/gdal/GDALUtils.class', jar.namelist())
                self.assertEqual(jar.read('META-INF/project-LICENSE.txt'), (recipe.REPO / 'LICENSE').read_bytes())
                profile = json.loads(jar.read('META-INF/uds-takserver-worldwind-profile.json'))
                self.assertEqual(profile['combined_variant_spdx'], 'GPL-3.0-only')
                self.assertEqual(profile['profile'], 'project-standard-gdal-rgb')
                resources = {p[4:]: sha for p, sha in self.lock['files'].items()
                             if p.startswith('src/') and not p.endswith('.java')}
                self.assertEqual(len(resources), 189)
                self.assertTrue(set(resources).issubset(jar.namelist()))
                for name, sha in resources.items():
                    self.assertEqual(recipe.hashlib.sha256(jar.read(name)).hexdigest(), sha)
            jdk_resources(out / state['artifact']['name'], {
                'config/DataFileStore.xml': resources['config/DataFileStore.xml'],
                'images/16x16-icon-nasa.png': resources['images/16x16-icon-nasa.png'],
                'META-INF/project-LICENSE.txt': self.lock['project_license']['sha256'],
                **{'META-INF/upstream-notices/' + p: self.lock['files'][p] for p in self.lock['notices']}})


if __name__ == '__main__':
    unittest.main()
