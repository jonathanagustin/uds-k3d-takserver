# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""OCI fixtures follow UDS 0.41 localbundle.go and Zarf layout/oci.go."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('artifact_inputs',
                                            ROOT / '.github/scripts/install-artifact-inputs.py')
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


class ArtifactInputsTests(unittest.TestCase):
    def setUp(self):
        self.objects = {}
        self.blob_layer = 'application/vnd.zarf.layer.v1.blob'
        core = self.package('core-base', [])
        image_descriptors = []
        image_layers = []
        self.expected_images = {}
        for i, name in enumerate(sorted(inputs.IMAGES)):
            config = self.add({'architecture': 'amd64', 'os': 'linux', 'unique': i},
                              'application/vnd.oci.image.config.v1+json')
            layer = {'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
                     'digest': 'sha256:' + str(i) * 64, 'size': 42}
            image = self.add({'schemaVersion': 2, 'mediaType': inputs.checkpoint.MANIFEST,
                              'config': config, 'layers': [layer]}, inputs.checkpoint.MANIFEST)
            image['annotations'] = {inputs.IMAGE_NAME: inputs.REGISTRY + name + ':input-key'}
            image_descriptors.append(image)
            image_layers.extend([{**item, 'mediaType': self.blob_layer} for item in (config, layer, image)])
            self.expected_images[name] = image['digest']
        index = self.add({'schemaVersion': 2, 'mediaType': inputs.checkpoint.INDEX,
                          'manifests': image_descriptors}, self.blob_layer)
        index['annotations'] = {inputs.TITLE: 'images/index.json'}
        app = self.package('takserver', [index, *image_layers])
        config = self.add({'architecture': 'amd64',
                           'annotations': {inputs.TITLE: 'takserver-dev'}}, self.blob_layer)
        # The actual bundle's YAML layer is deliberately not parsed or emitted.
        yaml = {'mediaType': self.blob_layer, 'digest': 'sha256:' + 'f' * 64, 'size': 9,
                'annotations': {inputs.TITLE: 'uds-bundle.yaml'}}
        self.root = self.add({'schemaVersion': 2, 'mediaType': inputs.checkpoint.MANIFEST,
                              'config': config, 'layers': [core, app, yaml]}, inputs.checkpoint.MANIFEST)
        self.objects['index.json'] = json.dumps({'schemaVersion': 2, 'mediaType': inputs.checkpoint.INDEX,
                                                'manifests': [self.root]}).encode()
        self.expected_core = core['digest']

    def add(self, value, media):
        data = json.dumps(value, separators=(',', ':')).encode()
        digest = inputs.checkpoint.sha(data)
        self.objects['blobs/sha256/' + digest.split(':')[1]] = data
        return {'mediaType': media, 'digest': digest, 'size': len(data)}

    def package(self, name, layers):
        if not layers:
            layers = [{'mediaType': self.blob_layer, 'digest': 'sha256:' + 'e' * 64, 'size': 42}]
        config = self.add({'kind': 'ZarfPackageConfig',
                           'metadata': {'name': name, 'architecture': 'amd64'}},
                          'application/vnd.zarf.config.v1+json')
        return {**self.add({'schemaVersion': 2, 'mediaType': inputs.checkpoint.MANIFEST,
                            'annotations': {inputs.TITLE: name}, 'config': config,
                            'layers': layers}, self.blob_layer)}

    def test_reads_actual_core_and_all_eight_packaged_images(self):
        value = inputs.identities(self.objects, 'amd64')
        self.assertEqual(value, {'core_oci_digest': self.expected_core,
                                 'image_digests': self.expected_images})
        self.assertEqual(set(value), {'core_oci_digest', 'image_digests'})

    def test_wrong_architecture_and_missing_or_corrupt_descriptor_omit(self):
        with self.assertRaises(ValueError):
            inputs.identities(self.objects, 'arm64')
        for name in ('index.json', 'blobs/sha256/' + self.expected_core.split(':')[1]):
            objects = copy.deepcopy(self.objects)
            del objects[name]
            with self.subTest(name=name), self.assertRaises((ValueError, KeyError)):
                inputs.identities(objects, 'amd64')
        objects = copy.deepcopy(self.objects)
        objects['blobs/sha256/' + self.expected_core.split(':')[1]] += b' '
        with self.assertRaises(ValueError):
            inputs.identities(objects, 'amd64')

    def test_forged_image_digest_does_not_match_actual_bytes(self):
        objects = copy.deepcopy(self.objects)
        digest = next(iter(self.expected_images.values()))
        objects['blobs/sha256/' + digest.split(':')[1]] = b'{"secret":"DO_NOT_EMIT"}'
        with self.assertRaises(ValueError):
            inputs.identities(objects, 'amd64')

    def archive(self, directory, members):
        raw = directory / 'bundle.tar'
        with tarfile.open(raw, 'w') as tar:
            for name, data in members:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        compressed = directory / 'bundle.tar.zst'
        subprocess.run(['zstd', '-q', str(raw), '-o', str(compressed)], check=True)
        return compressed

    def test_streaming_real_zstd_archive_never_extracts_config_or_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = self.archive(directory, [*self.objects.items(),
                                              ('../../outside', b'sensitive'),
                                              ('config.yaml', b'password: DO_NOT_EMIT')])
            objects = inputs.metadata(archive)
            self.assertEqual(inputs.identities(objects, 'amd64')['image_digests'], self.expected_images)
            self.assertEqual(set(directory.iterdir()), {archive, directory / 'bundle.tar'})
            self.assertNotIn('config.yaml', objects)

    def test_duplicate_and_corrupt_oci_entries_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            data = self.objects['index.json']
            archive = self.archive(directory, [('index.json', data), ('index.json', data)])
            with self.assertRaises(ValueError):
                inputs.metadata(archive)


if __name__ == '__main__':
    unittest.main()
