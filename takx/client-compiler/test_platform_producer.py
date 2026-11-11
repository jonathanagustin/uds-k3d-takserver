# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Pure producer/consumer admission guards; no compiler or application is run."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('platform_producer_under_test', Path(__file__).with_name('platform_producer.py'))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class PlatformGuards(unittest.TestCase):
    def profile(self, root):
        patch = root / 'patches/mission.patch'
        patch.parent.mkdir()
        patch.write_bytes(b'guard metadata only; no source or compiler')
        lock = p.load(p.LOCK)
        sources = {name: {'preSha256': lock['sources']['takx-client-readiness:5.7/' + name],
                          'postSha256': '1' * 64, 'scope': 'Platform'} for name in p.PLATFORM_FILES}
        sources[p.CLIENT_FILE] = {'preSha256': '2' * 64, 'postSha256': '3' * 64, 'scope': 'Client'}
        profile = {'schema': 1, 'profileId': p.PROFILE, 'sourceRevision': p.REVISION,
                   'sources': sources, 'patch': {'file': 'patches/mission.patch', 'sha256': p.sha(patch)},
                   'platformReceipt': {'requiredProducer': 'genuine-full-platform', 'oldPlatformArtifactAllowed': False,
                                       'newClassNames': [p.EXTRA_CLASS]}}
        path = root / 'profile.json'
        path.write_text(json.dumps(profile))
        return path, profile

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            path.write_text('{"producer":true,"producer":false}')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
                p.load(path)

    def test_path_escapes_rejected(self):
        for value in ['.', '../a', '/a', 'a/../../b', 'a//b', 'a\\b', 'a\nnext', None]:
            with self.assertRaises(ValueError):
                p.relative(value)

    def test_exact_profile_sha_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _ = self.profile(Path(directory))
            with self.assertRaisesRegex(ValueError, 'profile SHA'):
                p.read_profile(path, '0' * 64)

    def test_patch_bytes_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.profile(root)
            (root / 'patches/mission.patch').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'patch identity'):
                p.read_profile(path, p.sha(path))

    def test_old_platform_fallback_is_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.profile(Path(directory))
            data['platformReceipt']['oldPlatformArtifactAllowed'] = True
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'artifact policy'):
                p.read_profile(path, p.sha(path))

    def test_extra_source_families_are_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.profile(Path(directory))
            data['sources']['Platform/src/main/java/FakeSDK.java'] = data['sources'][next(iter(p.PLATFORM_FILES))]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'exact four'):
                p.read_profile(path, p.sha(path))

    def test_source_postimages_replace_only_three_platform_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            _, profile = self.profile(Path(directory))
            lock = p.load(p.LOCK)
            changed = p.expected_sources(lock, profile)
            self.assertEqual(len(changed), 1815)
            self.assertEqual({name for name in changed if changed[name] != lock['sources'][name]},
                             {'takx-client-readiness:5.7/' + name for name in p.PLATFORM_FILES})
            self.assertTrue(all(value != '1' * 64 for value in lock['sources'].values()))

    def test_missing_producer_cannot_be_satisfied_by_old_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.profile(root)
            old = root / 'old'
            old.mkdir()
            (old / 'complete.json').write_text(json.dumps({'compiler_success': True, 'classes': {}}))
            with self.assertRaisesRegex(ValueError, 'full genuine Platform'):
                p.verify_platform_proof(path, p.sha(path), old, p.sha(old / 'complete.json'))

    def test_different_producer_recipe_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.profile(root)
            proof = root / 'producer'
            proof.mkdir()
            (proof / 'complete.json').write_text(json.dumps({'producer': 'genuine-full-platform',
                'compilerSuccess': True, 'returncode': 0, 'sourceCount': 1815,
                'producerRecipeSha256': '0' * 64, 'producerInputsSha256': p.sha(p.LOCK)}))
            with self.assertRaisesRegex(ValueError, 'recipe/lock'):
                p.verify_platform_proof(path, p.sha(path), proof, p.sha(proof / 'complete.json'))

    def test_two_source_overlay_is_not_a_full_platform_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _ = self.profile(root)
            proof = root / 'overlay'
            proof.mkdir()
            (proof / 'complete.json').write_text(json.dumps({'producer': 'genuine-full-platform',
                'compilerSuccess': True, 'returncode': 0, 'sourceCount': 2,
                'producerRecipeSha256': p.sha(Path(p.__file__)), 'producerInputsSha256': p.sha(p.LOCK)}))
            with self.assertRaisesRegex(ValueError, 'complete successful Platform compiler'):
                p.verify_platform_proof(path, p.sha(path), proof, p.sha(proof / 'complete.json'))

    def test_frozen_closure_has_no_precompiled_platform_on_classpath(self):
        lock = p.load(p.LOCK)
        self.assertEqual(len(lock['sources']), 1815)
        self.assertEqual(len(lock['classpath']), 135)
        self.assertEqual(len(lock['processorpath']), 129)
        self.assertEqual(len(lock['expected_baseline_class_names']), 2098)
        self.assertEqual(len(lock['expected_generated_source_names']), 17)
        self.assertFalse(any('platform-classes' in value for value in lock['classpath']))


if __name__ == '__main__':
    unittest.main()
