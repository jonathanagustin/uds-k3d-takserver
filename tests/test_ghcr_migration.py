# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Migration conflicts, OCI graph closure, namespace limits and credential handling."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/migrate-ghcr.py'
SPEC = importlib.util.spec_from_file_location('migration', SCRIPT)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
A, B, C = ['sha256:' + char * 64 for char in 'abc']


class FakeRegistry:
    host = 'ghcr.io'
    def __init__(self, values): self.values = values
    def tags(self, repository):
        return sorted(tag for repo, tag in self.values if repo == repository)
    def manifest(self, repository, reference, missing=False):
        return self.values.get((repository, reference))


class MigrationTests(unittest.TestCase):
    def test_existing_current_alias_is_preserved_by_full_digest_alias(self):
        source, target = M.OLD + 'takserver', M.NEW + 'takserver'
        registry = FakeRegistry({(source, 'stable'): A, (target, 'stable'): B,
                                 (source, 'same'): C, (target, 'same'): C})
        family = M.plan_family(registry, 'takserver')
        M.validate_plan({'schema': 1, 'families': [family]})
        stable = next(item for item in family['entries'] if item['source_tag'] == 'stable')
        self.assertEqual(stable['destination_tag'], 'legacy-' + 'a' * 64)
        self.assertEqual(stable['preserved_destination_digest'], B)
        self.assertTrue(next(item for item in family['entries'] if item['source_tag'] == 'same')['already_present'])

    def test_referrer_and_signature_collisions_fail_before_copy(self):
        for tag in ['sha256-' + 'a' * 64, 'sha256-' + 'a' * 64 + '.sig']:
            registry = FakeRegistry({(M.OLD + 'takserver', tag): A, (M.NEW + 'takserver', tag): B})
            with self.assertRaisesRegex(M.MigrationError, 'signature/referrer'):
                M.plan_family(registry, 'takserver')

    def test_empty_inventory_and_digest_alias_conflicts_fail(self):
        with self.assertRaises(M.MigrationError):
            M.plan_family(FakeRegistry({}), 'takserver')
        values = {(M.OLD + 'takserver', 'stable'): A, (M.NEW + 'takserver', 'stable'): B,
                  (M.NEW + 'takserver', 'legacy-' + 'a' * 64): C}
        with self.assertRaisesRegex(M.MigrationError, 'alias collision'):
            M.plan_family(FakeRegistry(values), 'takserver')

    def test_external_namespace_invalid_tags_and_duplicate_family_are_rejected(self):
        family = M.plan_family(FakeRegistry({(M.OLD + 'takserver', '0.10.0-upstream'): A}), 'takserver')
        for field, value in [('source', 'attacker/project'), ('destination', 'attacker/project'), ('family', '../escape')]:
            broken = copy.deepcopy(family); broken[field] = value
            with self.assertRaises(M.MigrationError): M.validate_plan({'schema': 1, 'families': [broken]})
        for field, value in [('source_tag', '../escape'), ('destination_tag', 'different'), ('digest', 'sha256:short')]:
            broken = copy.deepcopy(family); broken['entries'][0][field] = value
            with self.assertRaises(M.MigrationError): M.validate_plan({'schema': 1, 'families': [broken]})
        with self.assertRaises(M.MigrationError): M.validate_plan({'schema': 1, 'families': [family, family]})

    def test_actual_manifest_byte_hash_and_descriptor_closure(self):
        blob = b'{"actual":"configuration"}'
        blob_digest = 'sha256:' + hashlib.sha256(blob).hexdigest()
        image = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                            'config': {'digest': blob_digest, 'size': len(blob), 'mediaType': 'application/vnd.oci.image.config.v1+json'},
                            'layers': []}).encode()
        digest = 'sha256:' + hashlib.sha256(image).hexdigest()
        registry = M.Registry('http://127.0.0.1:5000')
        calls = []
        def response(repository, path, head=False, missing=False):
            calls.append(path)
            if path.startswith('manifests/'):
                return {'Docker-Content-Digest': digest}, image
            self.assertEqual(path, 'blobs/' + blob_digest)
            return {'Content-Length': str(len(blob)), 'Docker-Content-Digest': blob_digest}, b''
        registry.request = response
        self.assertEqual(registry.manifest('fixture', digest), digest)
        self.assertEqual(registry.closure('fixture', digest), {'manifests': [digest], 'blobs': {blob_digest: len(blob)}})
        registry.closure('fixture', digest)
        self.assertEqual(calls.count('blobs/' + blob_digest), 1)
        registry.request = lambda *a, **kw: ({'Docker-Content-Digest': A}, image)
        with self.assertRaisesRegex(M.MigrationError, 'byte digest'):
            registry.manifest('fixture', digest)

    def test_blob_size_and_invalid_descriptors_fail(self):
        registry = M.Registry('http://127.0.0.1:5000')
        registry.manifests['fixture', A] = {'layers': [{'digest': B, 'size': 4}]}
        registry.request = lambda *a, **kw: ({'Content-Length': '3'}, b'')
        with self.assertRaisesRegex(M.MigrationError, 'Blob size'):
            registry.closure('fixture', A)
        registry.manifests['fixture', A] = {'layers': [{'digest': '../outside', 'size': 4}]}
        with self.assertRaisesRegex(M.MigrationError, 'descriptor'):
            registry.closure('fixture', A)

    def test_copy_family_selector_never_touches_other_repositories(self):
        families = [M.plan_family(FakeRegistry({(M.OLD + name, 'stable'): A}), name)
                    for name in ('takserver', 'postgis')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = root / 'plan.json'
            plan.write_text(json.dumps({'schema': 1, 'families': families}))
            args = ['migrate-ghcr.py', 'copy', '--plan', str(plan), '--receipts',
                    str(root / 'receipts'), '--family', 'postgis']
            with patch('sys.argv', args), patch.object(M, 'copy_family',
                       side_effect=lambda family, receipts: {'family': family['family']}) as copy_family:
                M.main()
            self.assertEqual(copy_family.call_count, 1)
            self.assertEqual(copy_family.call_args.args[0]['family'], 'postgis')
            complete = json.loads((root / 'receipts' / 'complete.json').read_text())
            self.assertEqual(complete['families'], [{'family': 'postgis'}])

    def test_copy_failure_receipt_contains_codes_without_storage_credentials(self):
        family = M.plan_family(FakeRegistry({(M.OLD + 'takserver', 'stable'): A}), 'takserver')
        registry = FakeRegistry({(M.OLD + 'takserver', 'stable'): A})
        failure = M.subprocess.CompletedProcess([], 1, '', 'HTTP 403 https://storage.invalid/?sig=private-test')
        with tempfile.TemporaryDirectory() as directory, patch.object(M, 'Registry', return_value=registry), \
                patch.object(M.subprocess, 'run', return_value=failure):
            with self.assertRaisesRegex(M.MigrationError, 'Registry copy failed'):
                M.copy_family(family, Path(directory))
            receipt = (Path(directory) / 'takserver-error.json').read_text()
            self.assertEqual(json.loads(receipt)['registry_errors'], ['HTTP 403'])
            self.assertNotIn('storage.invalid', receipt)
            self.assertNotIn('private-test', receipt)

    def test_signed_storage_redirect_drops_registry_authorization(self):
        request = urllib.request.Request('https://ghcr.io/v2/fixture/blobs/' + A,
                                         headers={'Authorization': 'Bearer private-test-token'}, method='HEAD')
        redirected = M.SafeRedirect().redirect_request(request, None, 302, 'redirect', {},
                                                        'https://storage.blob.core.windows.net/public')
        self.assertIsNone(redirected.get_header('Authorization'))
        self.assertEqual(redirected.get_method(), 'HEAD')

    def test_copy_refuses_changed_destination_and_never_runs_a_command(self):
        family = M.plan_family(FakeRegistry({(M.OLD + 'takserver', 'version'): A}), 'takserver')
        registry = FakeRegistry({(M.OLD + 'takserver', 'version'): A, (M.NEW + 'takserver', 'version'): B})
        with tempfile.TemporaryDirectory() as directory, patch.object(M, 'Registry', return_value=registry), patch.object(M.subprocess, 'run') as run:
            with self.assertRaisesRegex(M.MigrationError, 'Destination tag changed'):
                M.copy_family(family, Path(directory))
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
