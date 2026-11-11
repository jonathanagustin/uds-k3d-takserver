# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline real helper/API and workflow contracts; never create a release."""
import copy
import importlib.util
import json
import os
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('readiness', Path(__file__).with_name('release-readiness.py'))
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
SOURCE, OTHER, ANNOTATED = 'a' * 40, 'b' * 40, 'c' * 40


class API:
    def __init__(self, public=False):
        self.release = {'id': 123, 'url': R.BASE + '/releases/123', 'tag_name': 'v0.12.3',
                        'target_commitish': SOURCE, 'draft': not public, 'prerelease': False}
        self.calls = []
        self.annotated = False
        self.mutate = None

    def __call__(self, path, payload=None):
        self.calls.append((path, payload))
        if self.mutate:
            self.mutate(self, path, payload)
        if path.startswith('/git/ref/'):
            return {'ref': 'refs/tags/v0.12.3', 'object': {
                'type': 'tag' if self.annotated else 'commit', 'sha': ANNOTATED if self.annotated else SOURCE}}
        if path.startswith('/git/tags/'):
            return {'sha': ANNOTATED, 'object': {'type': 'commit', 'sha': SOURCE}}
        if payload is not None:
            self.release['draft'] = False
        return copy.deepcopy(self.release)


class PublishedTagAPI(API):
    """Model GitHub: the published-tag endpoint cannot find this draft."""
    def __call__(self, path, payload=None):
        if path.startswith('/releases/tags/') and self.release['draft']:
            self.calls.append((path, payload))
            error = urllib.error.HTTPError('https://api.github.com/fixture', 404, 'Not Found', {}, None)
            error.close()
            raise error
        return super().__call__(path, payload)


class PromotionTests(unittest.TestCase):
    def http_error(self, *args):
        error = urllib.error.HTTPError(*args)
        # Keep unused injected errors alive until deterministic cleanup too.
        self.addCleanup(error.close)
        return error

    def test_draft_exact_identity_patches_only_draft_and_rechecks(self):
        api = API()
        self.assertEqual(R.promote(api, 'v0.12.3', '123', SOURCE), 'published')
        self.assertEqual([(p, v) for p, v in api.calls if v is not None],
                         [('/releases/123', {'draft': False})])
        self.assertEqual(api.calls[-1][0], '/git/ref/tags/v0.12.3')

    def test_bound_draft_check_and_promote_do_not_use_published_tag_endpoint(self):
        for operation in ('check', 'promote'):
            with self.subTest(operation=operation):
                api = PublishedTagAPI()
                with self.assertRaises(urllib.error.HTTPError):
                    api('/releases/tags/v0.12.3')
                api.calls.clear()
                if operation == 'check':
                    self.assertTrue(R.check_release(api, 'v0.12.3', '123', SOURCE,
                                                    checked_source=SOURCE)['draft'])
                    self.assertFalse(any(payload is not None for _, payload in api.calls))
                else:
                    self.assertEqual(R.promote(api, 'v0.12.3', '123', SOURCE), 'published')
                    self.assertEqual([c for c in api.calls if c[1] is not None],
                                     [('/releases/123', {'draft': False})])
                self.assertEqual(api.calls[0], ('/releases/123', None))
                self.assertFalse(any(path.startswith('/releases/tags/') for path, _ in api.calls))

    def test_published_tag_model_refuses_wrong_binding_and_preserves_public_backfill(self):
        for operation in ('check', 'promote'):
            for identity in [('', ''), ('123', ''), ('', SOURCE), ('124', SOURCE), ('123', OTHER)]:
                api = PublishedTagAPI()
                with self.subTest(operation=operation, identity=identity), self.assertRaises(
                        (ValueError, urllib.error.HTTPError)):
                    if operation == 'check':
                        R.check_release(api, 'v0.12.3', *identity, checked_source=SOURCE)
                    else:
                        R.promote(api, 'v0.12.3', *identity)
                self.assertFalse(any(payload is not None for _, payload in api.calls))
            api = PublishedTagAPI(public=True)
            if operation == 'check':
                self.assertFalse(R.check_release(api, 'v0.12.3', checked_source=SOURCE)['draft'])
            else:
                self.assertEqual(R.promote(api, 'v0.12.3'), 'already-public')
            self.assertEqual(api.calls[0], ('/releases/tags/v0.12.3', None))
            self.assertFalse(any(payload is not None for _, payload in api.calls))

    def test_existing_tag_branch_metadata_is_not_commit_authority(self):
        api = API(); api.release['target_commitish'] = 'main'
        self.assertEqual(R.promote(api, 'v0.12.3', '123', SOURCE), 'published')

    def test_annotated_tag_is_peeled_to_real_commit(self):
        api = API(); api.annotated = True
        self.assertEqual(R.promote(api, 'v0.12.3', '123', SOURCE), 'published')
        self.assertTrue(any(p.startswith('/git/tags/') for p, _ in api.calls))

    def test_wrong_release_or_source_never_patches(self):
        for field, value in [('id', 124), ('tag_name', 'v0.12.4'),
                             ('url', 'https://api.github.com/repos/foreign/repo/releases/123'),
                             ('draft', 'false'), ('prerelease', True)]:
            with self.subTest(field=field):
                api = API(); api.release[field] = value
                with self.assertRaises((ValueError, TypeError)):
                    R.promote(api, 'v0.12.3', '123', SOURCE)
                self.assertFalse(any(v is not None for _, v in api.calls))

    def test_wrong_peeled_commit_and_tag_cycles_never_patch(self):
        for cycle in (False, True):
            api = API(); original = api.__call__
            def call(path, payload=None):
                if path.startswith('/git/ref/'):
                    return {'ref': 'refs/tags/v0.12.3', 'object': {'type': 'tag' if cycle else 'commit', 'sha': OTHER}}
                if path.startswith('/git/tags/'):
                    return {'sha': OTHER, 'object': {'type': 'tag', 'sha': OTHER}}
                return original(path, payload)
            with self.assertRaises(ValueError):
                R.promote(call, 'v0.12.3', '123', SOURCE)
            self.assertFalse(any(v is not None for _, v in api.calls))

    def test_identity_change_on_final_read_prevents_patch(self):
        for field, value in [('id', 124), ('tag_name', 'v0.12.4'), ('draft', False)]:
            api = API()
            def change(current, path, payload):
                exact_reads = sum(p == '/releases/123' and v is None for p, v in current.calls)
                if path == '/releases/123' and payload is None and exact_reads == 2:
                    current.release[field] = value
            api.mutate = change
            with self.subTest(field=field), self.assertRaises(ValueError):
                R.promote(api, 'v0.12.3', '123', SOURCE)
            self.assertFalse(any(v is not None for _, v in api.calls))

    def test_api_failure_is_not_a_success_or_mutation(self):
        def failure(_path, _payload=None):
            raise urllib.error.URLError('private details')
        with self.assertRaises(urllib.error.URLError):
            R.promote(failure, 'v0.12.3', '123', SOURCE)

    def test_public_backfill_and_exact_replay_do_not_patch(self):
        for identity in [('', ''), ('123', SOURCE)]:
            api = API(public=True)
            self.assertEqual(R.promote(api, 'v0.12.3', *identity), 'already-public')
            self.assertFalse(any(v is not None for _, v in api.calls))

    def test_draft_manual_recovery_requires_both_trusted_inputs(self):
        for identity in [('', ''), ('123', ''), ('', SOURCE), ('123', OTHER)]:
            api = API()
            with self.assertRaises(ValueError):
                R.promote(api, 'v0.12.3', *identity)
            self.assertFalse(any(v is not None for _, v in api.calls))

    def test_read_only_preflight_binds_native_checkout_and_refuses_unbound_draft(self):
        for public, identity, checkout, success in [
                (False, ('123', SOURCE), SOURCE, True),
                (False, ('', ''), SOURCE, False),
                (False, ('123', SOURCE), OTHER, False),
                (True, ('', ''), SOURCE, True),
                (True, ('', ''), OTHER, False)]:
            api = API(public=public)
            if success:
                R.check_release(api, 'v0.12.3', *identity, checked_source=checkout)
            else:
                with self.assertRaises(ValueError):
                    R.check_release(api, 'v0.12.3', *identity, checked_source=checkout)
            self.assertFalse(any(payload is not None for _, payload in api.calls))

    def test_api_bounds_status_malformed_duplicate_and_nonobject_responses(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass
            def read(self, limit):
                self.limit = limit
                return self.data[:limit]
        api = R.API('fixture')
        for data in (b'x' * 262145, b'not json', b'[]', b'{"id":1,"id":2}'):
            response = Response(); response.data = data
            with patch.object(api.opener, 'open', return_value=response), self.assertRaises(ValueError):
                api('/releases/123')
            self.assertEqual(response.limit, 262145)
        response = Response(); response.status = 503; response.data = b'{}'
        with patch.object(api.opener, 'open', return_value=response), self.assertRaises(ValueError):
            api('/releases/123')

    def test_api_failure_metadata_is_fixed_for_each_valid_operation(self):
        for path, operation in [('/releases/123', 'release-id'),
                                ('/releases/tags/v0.12.3', 'release-tag'),
                                ('/git/ref/tags/v0.12.3', 'git-ref'),
                                ('/git/tags/' + SOURCE, 'git-tag')]:
            for status, expected in [(404, 404), (99, 'unknown'), (600, 'unknown'),
                                     ('private-status', 'unknown'), (True, 'unknown')]:
                api = R.API('private-token')
                error = self.http_error('https://example.invalid/private-url', status,
                                               'private-reason', {'private-header': 'private-value'},
                                               io.BytesIO(b'private-body'))
                with self.subTest(operation=operation, status=status), patch.object(
                        api.opener, 'open', side_effect=error), self.assertRaises(R.APIFailure) as caught:
                    api(path)
                self.assertEqual((caught.exception.operation, caught.exception.kind, caught.exception.status),
                                 (operation, 'HTTP', expected))
                self.assertEqual(str(caught.exception), 'release API failure')

    def test_main_api_errors_never_print_upstream_secrets_or_success(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        env = {'GITHUB_REPOSITORY': R.REPO, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': 'refs/heads/main', 'WORKFLOW_SHA': head, 'GH_TOKEN': 'private-token',
               'RELEASE_TAG': 'v0.12.3', 'RELEASE_ID': '123', 'RELEASE_SOURCE_SHA': SOURCE,
               'READINESS_MODE': 'check', 'CHECKED_SOURCE_SHA': SOURCE}
        failures = [(self.http_error('https://example.invalid/private-url', 404, 'private-reason',
                                            {'private-header': 'private-value'}, io.BytesIO(b'private-body')),
                     'HTTP', 404),
                    (urllib.error.URLError('private-transport'), 'transport', 'unknown'),
                    (urllib.error.URLError(TimeoutError('private-timeout')), 'timeout', 'unknown'),
                    (TimeoutError('private-timeout'), 'timeout', 'unknown'),
                    (OSError('private-os-error'), 'transport', 'unknown')]
        for error, kind, status in failures:
            api = R.API('private-token')
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(kind=kind, error=type(error).__name__), patch.dict(os.environ, env, clear=True), \
                    patch.object(R, 'API', return_value=api), \
                    patch.object(api.opener, 'open', side_effect=error) as request, \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(R.main(), 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(),
                             f'Release readiness API failure: operation=release-id status={status} kind={kind}'
                             ' reason=unknown remaining=unknown reset=unknown accepted_contents=unknown\n')
            request.assert_called_once()
            self.assertEqual(request.call_args.args[0].method, 'GET')

    def test_bounded_http_reason_and_header_classification_never_echoes_payload(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        env = {'GITHUB_REPOSITORY': R.REPO, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': 'refs/heads/main', 'WORKFLOW_SHA': head, 'GH_TOKEN': 'private-token',
               'RELEASE_TAG': 'v0.12.3', 'RELEASE_ID': '123', 'RELEASE_SOURCE_SHA': SOURCE,
               'READINESS_MODE': 'check', 'CHECKED_SOURCE_SHA': SOURCE}
        cases = [
            (json.dumps({'message': 'Resource not accessible by integration', 'private': 'private-body'}).encode(),
             'access-denied'),
            (json.dumps({'message': 'API rate limit exceeded for private-IP. (private-details)'}).encode(),
             'primary-rate-limit'),
            (json.dumps({'message': 'You have exceeded a secondary rate limit. private-details'}).encode(),
             'secondary-rate-limit'),
            (b'{"message":"Bad credentials"}', 'bad-credentials'),
            (b'{"message":"private-unknown"}', 'unknown'),
            (b'private-malformed', 'unknown'),
            (b'[' * 1100 + b'0' + b']' * 1100, 'unknown'),
            (b'{"message":"Bad credentials","message":"private-duplicate"}', 'unknown'),
            (b'{"message":"Resource not accessible by integration","private":"' + b'x' * 5000, 'unknown'),
        ]
        for body, reason in cases:
            for headers, expected in [
                    ({'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1800000000',
                      'X-Accepted-GitHub-Permissions': 'contents=read', 'private-header': 'private-value'},
                     'remaining=0 reset=1800000000 accepted_contents=read'),
                    ({'X-RateLimit-Remaining': '-1', 'X-RateLimit-Reset': 'private-header',
                      'X-Accepted-GitHub-Permissions': 'contents=private-secret'},
                     'remaining=unknown reset=unknown accepted_contents=unknown')]:
                stream = io.BytesIO(body)
                error = self.http_error('https://example.invalid/private-url', 403,
                                               'private-reason', headers, stream)
                api = R.API('private-token')
                stdout, stderr = io.StringIO(), io.StringIO()
                with self.subTest(reason=reason, headers=expected), patch.dict(os.environ, env, clear=True), \
                        patch.object(R, 'API', return_value=api), \
                        patch.object(api.opener, 'open', side_effect=error) as request, \
                        patch.object(error, 'read', wraps=error.read) as read, \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(R.main(), 1)
                    read.assert_called_once_with(4097)
                self.assertEqual(stdout.getvalue(), '')
                self.assertEqual(stderr.getvalue(), 'Release readiness API failure: operation=release-id'
                                 f' status=403 kind=HTTP reason={reason} {expected}\n')
                request.assert_called_once()
                self.assertEqual(request.call_args.args[0].method, 'GET')
                self.assertTrue(stream.closed)

    def test_http_error_response_closes_when_bounded_body_read_fails(self):
        class BrokenBody(io.BytesIO):
            def read(self, _limit):
                raise OSError('private-read-failure')
        body = BrokenBody(b'private-body')
        error = self.http_error('https://example.invalid/private-url', 403, 'private-reason', {}, body)
        api = R.API('private-token')
        with patch.object(api.opener, 'open', side_effect=error), self.assertRaises(R.APIFailure) as caught:
            api('/releases/123')
        self.assertTrue(body.closed)
        self.assertEqual(caught.exception.metadata['reason'], 'unknown')
        self.assertEqual(str(caught.exception), 'release API failure')

    def test_permission_and_numeric_headers_are_strict_and_bounded(self):
        for remaining, reset, permission, expected in [
                ('9999999999', '9999999999', 'metadata=read, contents=write',
                 (9999999999, 9999999999, 'write')),
                ('10000000000', '0', 'contents=admin', ('unknown', 0, 'unknown')),
                ('1e3', '1.5', 'contents=read, contents=write', ('unknown', 'unknown', 'unknown')),
                (' 0', '+1', 'contents=write; contents=read', ('unknown', 'unknown', 'unknown')),
                ('1', '2', 'contents=read,' + 'x' * 1024, (1, 2, 'unknown'))]:
            error = self.http_error('https://example.invalid/private', 403, 'private',
                    {'X-RateLimit-Remaining': remaining, 'X-RateLimit-Reset': reset,
                     'X-Accepted-GitHub-Permissions': permission}, io.BytesIO(b'{}'))
            with self.subTest(expected=expected):
                meta = R.http_metadata(error)
                self.assertEqual((meta['remaining'], meta['reset'], meta['accepted_contents']), expected)
                self.assertEqual(meta['reason'], 'unknown')

    def test_main_context_and_api_failures_are_fixed_diagnostics(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        env = {'GITHUB_REPOSITORY': R.REPO, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': 'refs/heads/main', 'WORKFLOW_SHA': head, 'GH_TOKEN': 'DO_NOT_ECHO',
               'RELEASE_TAG': 'v0.12.3', 'RELEASE_ID': '123', 'RELEASE_SOURCE_SHA': SOURCE}
        for key, value in [('WORKFLOW_SHA', OTHER), ('GITHUB_REPOSITORY', 'foreign/repo'),
                           ('GITHUB_REF', 'refs/heads/unreviewed'), ('GITHUB_EVENT_NAME', 'pull_request')]:
            output = io.StringIO()
            with patch.dict(os.environ, {**env, key: value}, clear=True), \
                    patch.object(R, 'API', side_effect=AssertionError('must not access API')), \
                    contextlib.redirect_stderr(output):
                self.assertEqual(R.main(), 1)
            self.assertNotIn('DO_NOT_ECHO', output.getvalue())
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), \
                patch.object(R, 'API', side_effect=urllib.error.URLError('DO_NOT_ECHO')), \
                contextlib.redirect_stderr(output):
            self.assertEqual(R.main(), 1)
        self.assertNotIn('DO_NOT_ECHO', output.getvalue())

    def test_bad_patch_response_never_reports_completed_promotion(self):
        api = API()
        def corrupt(current, _path, payload):
            if payload is not None:
                current.release['id'] = 124
        api.mutate = corrupt
        with self.assertRaises(ValueError):
            R.promote(api, 'v0.12.3', '123', SOURCE)

    def test_static_endpoint_and_payload_restrictions_precede_network(self):
        api = R.API('fixture-token')
        with patch.object(api.opener, 'open', side_effect=AssertionError('network')):
            for path, payload in [('https://foreign.example', None), ('/releases/123', {'draft': True}),
                                  ('/git/ref/tags/v0.12.3', {'draft': False}), ('/releases/0', None)]:
                with self.assertRaises(ValueError):
                    api(path, payload)
        with self.assertRaises(ValueError):
            R.NoRedirect().redirect_request(None)
        with self.assertRaises(ValueError):
            json.loads('{"draft":true,"draft":false}', object_pairs_hook=R.unique)

    def test_api_defaults_read_only_and_explicit_writer_keeps_payload_guards(self):
        for write in (False, True):
            api = R.API('fixture', allow_write=write)
            with patch.object(api.opener, 'open') as request:
                if not write:
                    with self.assertRaises(ValueError):
                        api('/releases/123', {'draft': False})
                    request.assert_not_called()
                else:
                    response = request.return_value.__enter__.return_value
                    response.status = 200
                    response.read.return_value = b'{}'
                    self.assertEqual(api('/releases/123', {'draft': False}), {})
                    self.assertEqual(request.call_args.args[0].method, 'PATCH')
                    request.reset_mock()
                    with self.assertRaises(ValueError):
                        api('/releases/123', {'draft': True})
                    request.assert_not_called()
        api = R.API('fixture')
        with patch.object(api.opener, 'open') as request, self.assertRaises(ValueError):
            api('/releases/123', {'draft': False})
        request.assert_not_called()

    def test_main_selects_api_capability_only_after_context_and_mode_validation(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        env = {'GITHUB_REPOSITORY': R.REPO, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_REF': 'refs/heads/main', 'WORKFLOW_SHA': head, 'GH_TOKEN': 'fixture',
               'RELEASE_TAG': 'v0.12.3', 'RELEASE_ID': '123', 'RELEASE_SOURCE_SHA': SOURCE,
               'CHECKED_SOURCE_SHA': SOURCE}
        for mode in ('check', 'promote', 'invalid'):
            api = API()
            with patch.dict(os.environ, {**env, 'READINESS_MODE': mode}, clear=True), \
                    patch.object(R, 'API', return_value=api) as constructor, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(R.main(), 1 if mode == 'invalid' else 0)
            if mode == 'invalid':
                constructor.assert_not_called()
                self.assertEqual(api.calls, [])
            else:
                constructor.assert_called_once_with('fixture', allow_write=mode == 'promote')
                self.assertEqual(any(payload is not None for _, payload in api.calls), mode == 'promote')


class ChartSourceTests(unittest.TestCase):
    def test_expected_source_checked_at_resolved_tag_before_other_work(self):
        spec = importlib.util.spec_from_file_location('chart_source', ROOT / '.github/scripts/publish-charts.py')
        charts = importlib.util.module_from_spec(spec); spec.loader.exec_module(charts)
        for expected in ('main', 'a' * 39, '--help'):
            with patch.object(charts, 'run', side_effect=AssertionError('git must not run')), self.assertRaises(ValueError):
                charts.release(ROOT, 'v0.12.3', 'origin/main', expected)
        with patch.object(charts, 'run', return_value=subprocess.CompletedProcess([], 0, OTHER, '')) as command:
            with self.assertRaises(ValueError):
                charts.release(ROOT, 'v0.12.3', 'origin/main', SOURCE)
            self.assertEqual(command.call_count, 1)
        outputs = [SOURCE, '', '{".":"0.12.3"}', '123']
        for expected in ('', SOURCE):
            def run(_args, _repo):
                return subprocess.CompletedProcess([], 0, outputs.pop(0), '')
            outputs = [SOURCE, '', '{".":"0.12.3"}', '123']
            with patch.object(charts, 'run', side_effect=run):
                self.assertEqual(charts.release(ROOT, 'v0.12.3', 'origin/main', expected), (SOURCE, 123))


class WiringTests(unittest.TestCase):
    def workflow(self, name):
        return yaml.safe_load((ROOT / '.github/workflows' / name).read_text())

    def test_official_pinned_contract_supports_drafts_with_immediate_tags(self):
        contract = json.loads(Path(__file__).with_name('release-please-contract.json').read_text())
        config = json.loads((ROOT / 'release-please-config.json').read_text())['packages']['.']
        self.assertEqual(contract['releasePleaseVersion'], '17.6.0')
        for name in ('draft', 'force-tag-creation'):
            self.assertEqual(contract['properties'][name]['type'], 'boolean')
            self.assertIs(config[name], True)
        self.assertIn('does not create a Git tag for draft releases',
                      contract['properties']['force-tag-creation']['description'])
        step = self.workflow('release-please.yaml')['jobs']['release-please']['steps'][0]
        self.assertEqual(step['uses'].split('@')[1].split()[0], contract['actionRef'])

    def test_charts_before_packages_and_docs_after_verified_promotion(self):
        jobs = self.workflow('release-please.yaml')['jobs']
        self.assertEqual(jobs['publish']['needs'], ['release-please', 'charts'])
        self.assertEqual(jobs['charts']['needs'], 'release-please')
        self.assertEqual(jobs['charts']['with']['source_sha'], '${{ needs.release-please.outputs.source-sha }}')
        chart_steps = self.workflow('charts.yaml')['jobs']['publish']['steps']
        chart = next(step for step in chart_steps if step['name'] == 'Publish and verify both immutable charts')
        self.assertEqual(chart['env']['RELEASE_SOURCE_SHA'], '${{ inputs.source_sha }}')
        self.assertIn('--source-sha \"${RELEASE_SOURCE_SHA}\"', chart['run'])
        self.assertEqual(jobs['docs']['needs'], ['release-please', 'publish'])
        self.assertIn("needs.publish.result == 'success'", jobs['docs']['if'])
        self.assertEqual(jobs['publish']['with']['release_id'], '${{ needs.release-please.outputs.release-id }}')
        self.assertEqual(jobs['release-please']['outputs']['source-sha'], '${{ steps.release.outputs.sha }}')
        release = self.workflow('release.yaml')['jobs']
        self.assertEqual(release['provenance']['needs'], 'publish')
        steps = release['provenance']['steps']
        self.assertEqual(steps[-2]['name'], 'Verify the provenance')
        self.assertEqual(steps[-1]['run'], 'python3 .github/test-infra/release-readiness.py')
        self.assertNotIn('if', steps[-1]); self.assertNotIn('continue-on-error', steps[-1])
        self.assertEqual(steps[0]['with']['ref'], '${{ github.workflow_sha }}')
        self.assertFalse(steps[0]['with']['persist-credentials'])
        native = release['publish']['steps']
        names = [step['name'] for step in native]
        self.assertNotIn('Checkout trusted readiness checker', names)
        self.assertFalse(any('release-readiness.py' in step.get('run', '') for step in native))
        self.assertEqual(release['publish']['needs'], 'metadata')
        metadata = release['metadata']
        self.assertEqual(metadata['permissions'], {'contents': 'write'})
        self.assertEqual(metadata['timeout-minutes'], 5)
        self.assertNotIn('needs', metadata)
        self.assertNotIn('always()', metadata['if'])
        self.assertEqual(metadata['if'], release['publish']['if'])
        self.assertEqual(len(metadata['steps']), 2)
        checker, check = metadata['steps']
        self.assertEqual(checker['with']['ref'], '${{ github.workflow_sha }}')
        self.assertEqual(checker['with']['fetch-depth'], 0)
        self.assertFalse(checker['with']['persist-credentials'])
        self.assertEqual(checker['with']['sparse-checkout'], '.github/test-infra/release-readiness.py')
        self.assertEqual(check['env']['READINESS_MODE'], 'check')
        self.assertIn('git rev-parse --verify "refs/tags/${RELEASE_TAG}^{commit}"', check['run'])
        self.assertLess(check['run'].index('python3 .github/test-infra/release-readiness.py'),
                        check['run'].index('echo "source-sha='))
        self.assertEqual(metadata['outputs']['source-sha'], '${{ steps.check.outputs.source-sha }}')
        for job in release.values():
            self.assertNotIn('continue-on-error', job)
            for step in job['steps']:
                self.assertNotIn('continue-on-error', step)
        self.assertEqual(release['publish']['strategy']['max-parallel'], 1)
        self.assertEqual([x['arch'] for x in release['publish']['strategy']['matrix']['include']], ['amd64', 'arm64'])
        self.assertEqual(release['provenance']['permissions'], {
            'contents': 'write', 'packages': 'write', 'id-token': 'write', 'attestations': 'write'})
        self.assertEqual(release['publish']['permissions'], {'contents': 'read', 'packages': 'write', 'id-token': 'write'})

    def test_actual_prebuild_script_refuses_wrong_or_partial_draft_source(self):
        step = self.workflow('release.yaml')['jobs']['publish']['steps'][1]
        script = step['run'].split("python3 - <<'PY_CHECK'\n", 1)[1].split('\nPY_CHECK', 1)[0]
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
        for identity, source, success in [('123', head, True), ('123', OTHER, False), ('123', '', False), ('', head, False), ('', '', True)]:
            with self.subTest(identity=identity, source=source):
                result = subprocess.run(['python3', '-c', script], cwd=ROOT,
                    env={**os.environ, 'RELEASE_ID': identity, 'RELEASE_SOURCE_SHA': source,
                         'VERIFIED_SOURCE_SHA': head}, capture_output=True)
                self.assertEqual(result.returncode == 0, success)
        self.assertEqual(step['env']['RELEASE_SOURCE_SHA'], '${{ inputs.source_sha }}')

    def test_native_local_guard_rejects_missing_or_changed_metadata_source(self):
        step = self.workflow('release.yaml')['jobs']['publish']['steps'][1]
        script = step['run'].split("python3 - <<'PY_CHECK'\n", 1)[1].split('\nPY_CHECK', 1)[0]
        self.assertEqual(step['env']['VERIFIED_SOURCE_SHA'], '${{ needs.metadata.outputs.source-sha }}')
        for verified in ('', OTHER, 'private-invalid'):
            result = subprocess.run(['python3', '-c', script], cwd=ROOT,
                env={**os.environ, 'RELEASE_ID': '', 'RELEASE_SOURCE_SHA': '',
                     'VERIFIED_SOURCE_SHA': verified}, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)

    def test_metadata_shell_emits_only_checked_source_after_success(self):
        step = self.workflow('release.yaml')['jobs']['metadata']['steps'][1]
        script = step['run']
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'],
                           check=True, capture_output=True)
            subprocess.run(['git', '-C', str(repo), 'tag', 'v0.12.3'], check=True, capture_output=True)
            head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip()
            helper = repo / '.github/test-infra/release-readiness.py'
            helper.parent.mkdir(parents=True)
            # Stub only the helper result to exercise the actual workflow shell.
            # Real helper API/source/context contracts are tested separately.
            helper.write_text("import os,sys\n"
                              "assert os.environ['CHECKED_SOURCE_SHA'] == os.environ['EXPECTED_SHA']\n"
                              "sys.exit(int(os.environ['HELPER_EXIT']))\n")
            for tag, helper_exit, success in [('v0.12.3', '0', True), ('v0.12.3', '1', False),
                                               ('v0.12.4', '0', False), ('v0.12.3;false', '0', False)]:
                output = repo / 'output'
                output.unlink(missing_ok=True)
                result = subprocess.run(['bash', '-c', script], cwd=repo, capture_output=True, timeout=10,
                    env={**os.environ, 'RELEASE_TAG': tag, 'GITHUB_OUTPUT': str(output),
                         'HELPER_EXIT': helper_exit, 'EXPECTED_SHA': head})
                self.assertEqual(result.returncode == 0, success)
                self.assertEqual(output.read_text() if output.exists() else '',
                                 f'source-sha={head}\n' if success else '')
