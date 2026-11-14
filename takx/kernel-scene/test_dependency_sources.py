# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
import importlib.util
from pathlib import Path
import tempfile
import unittest
S=importlib.util.spec_from_file_location('dependency_source_kernel',Path(__file__).with_name('kernel.py'))
K=importlib.util.module_from_spec(S);S.loader.exec_module(K)

class DependencySources(unittest.TestCase):
    def test_scene_sibling_is_not_a_dependency_but_dependency_drift_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for family in ('gdal','libkml'):
                (root/family).mkdir();(root/family/'source.c').write_text('pinned')
            expected=K.dependency_sources(root)
            (root/'kernel').mkdir();(root/'kernel/scene.cpp').write_text('separate scene producer')
            self.assertEqual(K.dependency_sources(root),expected)
            (root/'gdal/source.c').write_text('changed')
            self.assertNotEqual(K.dependency_sources(root),expected)
            (root/'libkml/link').symlink_to(root/'gdal/source.c')
            with self.assertRaises(ValueError):K.dependency_sources(root)

    def test_unknown_family_and_linked_kernel_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for family in ('gdal','libkml'):(root/family).mkdir()
            (root/'unknown').mkdir()
            with self.assertRaises(ValueError):K.dependency_sources(root)
            (root/'unknown').rmdir();(root/'kernel').symlink_to(root/'gdal',target_is_directory=True)
            with self.assertRaises(ValueError):K.dependency_sources(root)

if __name__=='__main__':unittest.main()
