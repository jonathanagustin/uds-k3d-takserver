# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Scene-only publication controls; no network, credentials, media copies or rendering."""
import base64
import copy
import io
import json
from pathlib import Path
import stat
import os
import subprocess
import tempfile
import warnings
import unittest
from unittest.mock import patch
import zipfile

import publish_scenes as p
from test_publish import FakeGitHub as ReelFake, REPO, SHA


class SceneFake(ReelFake):
    def __init__(self):
        super().__init__()
        self.recipe = b'recipe fixture'
        self.lock = Path(__file__).with_name('inputs.lock.json').read_bytes()
        lock = json.loads(self.lock)
        self.files = {'Inter-LICENSE.txt': b'license fixture', p.BUNDLE: b'bundle fixture'}
        for slug, (label, start, duration, frames) in p.SCENES.items():
            self.files[slug + '.mp4'] = (slug + ' video fixture').encode()
            self.files[slug + '.jpg'] = (slug + ' poster fixture').encode()
            manifest = {'purpose': lock['description'], 'source_input': lock['sources'][2],
                        'font_input': lock['font'], 'recipe_sha256': p.sha(self.recipe),
                        'lock_sha256': p.sha(self.lock), 'tool_versions': {'ffmpeg': 'ffmpeg fixture', 'ffprobe': 'ffprobe fixture'},
                        'scene': {'label': label, 'source': 'demo-clip-sync.mp4',
                                  'start_seconds': start, 'duration_seconds': duration},
                        'outputs': [{'file': slug + ext, 'sha256': p.sha(self.files[slug + ext]),
                                     'bytes': len(self.files[slug + ext])} for ext in ('.mp4', '.jpg')],
                        'probe': {'streams': [{'codec_name': 'h264', 'codec_type': 'video',
                                              'width': 1920, 'height': 1080}],
                                  'format': {'duration': str(duration)}},
                        'acceptance': 'Historical footage edit only; no new deployment, TAKX, or live interoperability acceptance'}
            self.files[slug + '.json'] = json.dumps(manifest).encode()
        self.statement['subject'] = [{'name': n, 'digest': {'sha256': p.sha(self.files[n])}}
                                     for n in sorted(p.SUBJECTS)]
        self.artifact['name'] = 'ui-scene-previews'
        self.pack()
        self.review = {'schema': 1, 'source_run_id': 42, 'source_attempt': 2, 'source_commit': SHA,
                       'reviewer': 'reviewer-fixture', 'reviewed_at': '2026-01-01T00:00:00Z',
                       'full_frame_privacy_review': True,
                       'frames': {s + '.mp4': v[3] for s, v in p.SCENES.items()},
                       'sha256': {n: p.sha(b) for n, b in self.files.items()}}
        self.target = None
        self.tag_exists = False
        self.mutations = []
        self.readbacks = []
        self.corrupt_readback = False

    def run(self, *args, binary=False):
        if args[:2] == ('attestation', 'verify'):
            self.calls.append(args)
            if self.fail_verification:
                raise ValueError('signature fixture failed')
            name = Path(args[2]).name
            assert name in p.SUBJECTS and Path(args[2]).read_bytes() == self.files[name]
            expected = ('--bundle', str(Path(args[2]).parent / p.BUNDLE), '--repo', REPO,
                        '--signer-workflow', f'{REPO}/{p.WORKFLOW}', '--signer-digest', SHA,
                        '--source-digest', SHA, '--source-ref', p.REF, '--cert-oidc-issuer',
                        'https://token.actions.githubusercontent.com', '--predicate-type',
                        'https://slsa.dev/provenance/v1', '--format', 'json')
            assert args[3:] == expected
            return [{'verificationResult': {'statement': copy.deepcopy(self.statement)}}]
        if args[:3] == ('api', '--paginate', '--slurp'):
            if args[3] == f'repos/{REPO}/releases?per_page=100':
                return [[copy.deepcopy(self.target)] if self.target else []]
            if args[3] == f'repos/{REPO}/releases/88/assets?per_page=100':
                return [copy.deepcopy(self.assets)]
        if args[:2] == ('release', 'upload'):
            assert args[2] == 'ui-scenes-run-42-attempt-2' and args[4:] == ('--repo', REPO)
            name = Path(args[3]).name
            assert not any(a['name'] == name for a in self.assets)
            assert Path(args[3]).read_bytes() == self.files[name]
            if self.fail_after is not None and len(self.uploads) >= self.fail_after:
                raise ValueError('interrupted upload')
            self.uploads.append(name)
            self.mutations.append(('upload', name))
            asset = self.asset(name)
            asset['id'] = 100 + len(self.assets)
            if self.bad_upload:
                asset['digest'] = 'sha256:' + '0' * 64
            self.assets.append(asset)
            return b''
        if args[:3] in (('api', '--method', 'POST'), ('api', '--method', 'PATCH')):
            self.mutations.append(args)
            if args[3].endswith('/git/refs'):
                self.tag_exists = True
                return {}
            if args[3].endswith('/releases'):
                values = dict(a.split('=', 1) for a in args[4:] if '=' in a)
                assert values['draft'] == 'true' and values['prerelease'] == 'true' and values['make_latest'] == 'false'
                self.target = {'id': 88, 'tag_name': values['tag_name'], 'target_commitish': SHA,
                               'draft': True, 'prerelease': True, 'body': values['body']}
                return copy.deepcopy(self.target)
            assert args[3] == f'repos/{REPO}/releases/88'
            assert args[4:] == ('-F', 'draft=false', '-f', 'make_latest=false')
            self.target['draft'] = False
            return copy.deepcopy(self.target)
        if args[0] == 'api':
            path = args[1]
            if '/contents/' in path:
                data = self.recipe if '/render.py?' in path else self.lock
                return {'type': 'file', 'encoding': 'base64', 'size': len(data),
                        'content': base64.b64encode(data).decode()}
            if '/git/matching-refs/' in path:
                return []
            if '/git/ref/tags/' in path:
                assert self.tag_exists
                return {'object': {'type': 'commit', 'sha': SHA,
                                   'url': f'https://api.github.com/repos/{REPO}/git/commits/{SHA}'}}
            if path == f'repos/{REPO}/releases/88':
                return copy.deepcopy(self.target)
            if '/releases/assets/' in path:
                assert binary and args[2:] == ('-H', 'Accept: application/octet-stream')
                asset = next(a for a in self.assets if a['id'] == int(path.rsplit('/', 1)[1]))
                self.readbacks.append(asset['name'])
                return b'corrupt' if self.corrupt_readback else self.files[asset['name']]
        return super().run(*args, binary=binary)


class SceneTests(unittest.TestCase):
    def publish(self, gh):
        with patch.object(p, 'LICENSE_SHA', p.sha(b'license fixture')), patch.object(p, 'inspect_media'), patch('builtins.print'):
            p.publish(gh, REPO, '42', '2', p.REF, gh.review)

    def refused_without_write(self, gh):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.publish(gh)
        self.assertEqual(gh.mutations, [])

    def test_publish_exact_original_bytes_then_public_retry_does_not_write(self):
        gh = SceneFake()
        self.publish(gh)
        self.assertEqual(set(gh.uploads), p.FILES)
        self.assertEqual(set(gh.readbacks), p.FILES)
        self.assertFalse(gh.target['draft'])
        writes = len(gh.mutations)
        self.publish(gh)
        self.assertEqual(len(gh.mutations), writes)
        self.assertEqual(len([a for a in gh.calls if a[:2] == ('attestation', 'verify')]), 12)

    def test_interrupted_draft_retry_only_uploads_missing_names(self):
        gh = SceneFake(); gh.fail_after = 3
        with self.assertRaises(ValueError): self.publish(gh)
        first = gh.uploads.copy(); gh.fail_after = None
        self.publish(gh)
        self.assertEqual(len(gh.uploads), 11)
        self.assertEqual(len(set(gh.uploads)), 11)
        self.assertEqual(gh.uploads[:3], first)

    def test_missing_false_incomplete_or_wrong_hash_review_fails_before_any_write(self):
        for mutate in [lambda r: r.clear(), lambda r: r.update(full_frame_privacy_review=False),
                       lambda r: r['frames'].update({'share-feature.mp4': 194}),
                       lambda r: r['sha256'].update({'share-feature.mp4': '0' * 64}),
                       lambda r: r.update(source_attempt=1), lambda r: r.update(source_commit='b'*40)]:
            with self.subTest(mutate=mutate):
                gh = SceneFake(); mutate(gh.review); self.refused_without_write(gh)

    def test_run_fork_attempt_and_signature_policy_fail_before_write(self):
        for mutate in [lambda g: g.source.update(event='pull_request'),
                       lambda g: g.source.update(run_attempt=3),
                       lambda g: g.source['head_repository'].update(id=999),
                       lambda g: setattr(g, 'fail_verification', True),
                       lambda g: g.statement['predicate']['runDetails']['metadata'].update(invocationId='wrong'),
                       lambda g: g.statement['subject'].pop()]:
            gh = SceneFake(); mutate(gh); self.refused_without_write(gh)

    def test_archive_digest_extra_duplicate_and_symlink_are_rejected(self):
        gh = SceneFake(); gh.artifact['digest'] = 'sha256:' + '0'*64; self.refused_without_write(gh)
        gh = SceneFake(); gh.files['extra'] = b'x'; gh.pack(); self.refused_without_write(gh)
        gh = SceneFake(); gh.pack(symlink='share-feature.jpg'); self.refused_without_write(gh)
        gh = SceneFake(); output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            for name,data in gh.files.items(): archive.writestr(name,data)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr('share-feature.jpg', b'duplicate')
        gh.archive = output.getvalue(); gh.artifact.update(size_in_bytes=len(gh.archive),digest='sha256:'+p.sha(gh.archive))
        self.refused_without_write(gh)

    def test_manifest_timing_poster_source_recipe_and_license_binding(self):
        for key, value in [('scene', {}), ('source_input', {}), ('recipe_sha256', '0'*64), ('outputs', [])]:
            gh = SceneFake(); v=json.loads(gh.files['share-feature.json']); v[key]=value
            gh.files['share-feature.json']=json.dumps(v).encode();gh.pack();self.refused_without_write(gh)
        gh=SceneFake();gh.files['share-feature.jpg']=b'changed';gh.pack();self.refused_without_write(gh)
        gh=SceneFake();gh.files['Inter-LICENSE.txt']=b'changed';gh.pack();self.refused_without_write(gh)

    def test_collision_and_readback_corruption_never_promote(self):
        gh=SceneFake();gh.fail_after=1
        with self.assertRaises(ValueError):self.publish(gh)
        gh.fail_after=None;gh.assets[0]['digest']='sha256:'+'0'*64
        with self.assertRaises(ValueError):self.publish(gh)
        self.assertTrue(gh.target['draft'])
        gh=SceneFake();gh.corrupt_readback=True
        with self.assertRaises(ValueError):self.publish(gh)
        self.assertTrue(gh.target['draft'])

    def test_scene_mode_requires_exact_pair_main_and_no_other_operation(self):
        script = Path(p.__file__)
        for run, attempt, ref, tag, old_run, export, success in [
            ('42', '2', p.REF, '', '', 'false', True),
            ('42', '', p.REF, '', '', 'false', False),
            ('', '2', p.REF, '', '', 'false', False),
            ('42', '2', 'refs/heads/topic', '', '', 'false', False),
            ('42', '2', p.REF, 'v0.12.0', '', 'false', False),
            ('42', '2', p.REF, '', '42', 'false', False),
            ('42', '2', p.REF, '', '', 'true', False),
        ]:
            with tempfile.NamedTemporaryFile() as output:
                env={**os.environ,'SCENE_SOURCE_RUN_ID':run,'SCENE_SOURCE_ATTEMPT':attempt,
                     'GITHUB_REF':ref,'RELEASE_TAG':tag,'SOURCE_RUN_ID':old_run,
                     'EXPORT_SCENES':export,'GITHUB_OUTPUT':output.name}
                result=subprocess.run(['/usr/bin/python3',str(script),'--mode-only'],env=env,
                                      capture_output=True,timeout=5)
                self.assertEqual(result.returncode==0,success,(run,attempt,ref,tag,old_run,export))
                if success:self.assertEqual(Path(output.name).read_text(),'mode=scenes\n')

    def test_duplicate_json_and_uncommitted_review_refused(self):
        with self.assertRaises(ValueError):p.decode('{"schema":1,"schema":1}')
        result=subprocess.run(['/usr/bin/python3',str(Path(p.__file__)),
                               '--source-run-id','42940218710','--source-attempt','1'],
                              capture_output=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'complete committed privacy review',result.stderr)

    def test_actual_probe_rejects_audio_wrong_rate_or_missing_frames(self):
        from types import SimpleNamespace
        good={'codec_type':'video','codec_name':'h264','width':1920,'height':1080,
              'avg_frame_rate':'30/1','nb_read_frames':'180'}
        for stream, extra in [(dict(good,nb_read_frames='179'),[]),
                              (dict(good,avg_frame_rate='24/1'),[]),
                              (good,[{'codec_type':'audio'}])]:
            value={'streams':[stream]+extra,'format':{'duration':'6.0'}}
            with patch.object(p.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(value).encode())):
                with self.assertRaises(ValueError):p.inspect_media(Path('/fixture'))

    def test_workflow_routes_scenes_without_renderer_or_combined_schema_relaxation(self):
        import yaml
        flow=yaml.safe_load((Path(__file__).resolve().parents[2]/'.github/workflows/ui-reel.yaml').read_text())
        job=flow['jobs']['publish-scenes']
        self.assertEqual(job['permissions'],{'contents':'write','actions':'read'})
        self.assertEqual(job['concurrency'],{'group':'ui-scenes-publish','queue':'max','cancel-in-progress':False})
        self.assertIn("mode == 'scenes'",job['if'])
        self.assertFalse(any('render.py' in s.get('run','') for s in job['steps']))
        self.assertEqual(len(p.reel.FILES),6)
        self.assertEqual(len(p.FILES),11)
