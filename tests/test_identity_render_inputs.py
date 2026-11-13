# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline render/discovery/defaulting checks; none grant live acceptance."""
import copy
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('identity_render_driver', ROOT / 'tests/workload-identities/drive.py')
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)
inputs = driver.render_inputs


def crd_fixture():
    schema = {'type': 'object', 'properties': {'spec': {'type': 'object', 'properties': {
        'network': {'type': 'object', 'properties': {'serviceMesh': {'type': 'object', 'properties': {
            'mode': {'type': 'string', 'default': 'ambient'}}}}},
        'sso': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'enabled': {'type': 'boolean', 'default': True},
            'publicClient': {'type': 'boolean', 'default': False},
            'protocolMappers': {'type': 'array', 'default': [], 'items': {
                'type': 'object', 'properties': {'consentRequired': {'type': 'boolean', 'default': False}}}}}}},
        'caBundle': {'type': 'object', 'properties': {'configMap': {'type': 'object', 'properties': {
            'name': {'type': 'string', 'default': 'uds-trust-bundle'},
            'key': {'type': 'string', 'default': 'ca-bundle.pem'},
            'labels': {'type': 'object', 'default': {}},
            'annotations': {'type': 'object', 'default': {}}}}}}}}}}
    return {'apiVersion': 'apiextensions.k8s.io/v1', 'kind': 'CustomResourceDefinition',
            'metadata': {'name': 'packages.uds.dev', 'uid': 'fixture-crd', 'generation': 1, 'resourceVersion': '8'},
            'spec': {'group': 'uds.dev', 'scope': 'Namespaced', 'names': {'kind': 'Package', 'plural': 'packages'},
                     'versions': [{'name': 'v1alpha1', 'served': True, 'schema': {'openAPIV3Schema': schema}}]}}


class RenderInputTests(unittest.TestCase):
    def test_manual_source_guard_refuses_changed_render_or_evidence_helper(self):
        for filename in ('render_inputs.py', 'phase_evidence.py'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                instance = driver.Driver(Path(directory) / 'journal.json')
                observed = []
                def command(args):
                    self.assertEqual(args[:2], ['git', 'show'])
                    relative = args[2].removeprefix('HEAD:')
                    observed.append(relative)
                    data = (ROOT / relative).read_text()
                    return data + '\n# changed helper\n' if relative.endswith('/' + filename) else data
                instance.command = command
                with patch.object(driver.importlib.util, 'spec_from_file_location',
                                  side_effect=AssertionError('must refuse before cluster module loading')):
                    with self.assertRaisesRegex(ValueError, 'consumed trial code differs'):
                        instance.guard()
                self.assertIn('tests/workload-identities/' + filename, observed)

    def test_api_discovery_requires_a_complete_bounded_unique_version_list(self):
        self.assertEqual(inputs.api_versions('monitoring.coreos.com/v1\nv1\n'), ['monitoring.coreos.com/v1', 'v1'])
        for text in ('', 'apps/v1\n', 'v1\nv1\n', 'v1\nwarning: unavailable\n', 'v1\nhttps://example/v1\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                inputs.api_versions(text)

    def test_declared_defaults_match_nested_ssos_and_preserve_explicit_values(self):
        _, schema = inputs.package_schema(crd_fixture())
        original = {'network': {'serviceMesh': {}}, 'sso': [{'clientId': 'example'},
                    {'enabled': False, 'publicClient': True, 'protocolMappers': [{}]}],
                    'caBundle': {'configMap': {'name': 'custom', 'labels': {'keep': 'value'}}},
                    'unknown': {'must-remain': 'unchanged'}}
        before = copy.deepcopy(original)
        result = inputs.apply_defaults(original, schema)
        self.assertEqual(original, before)
        self.assertEqual(result['network']['serviceMesh'], {'mode': 'ambient'})
        self.assertEqual(result['sso'][0], {'clientId': 'example', 'enabled': True, 'publicClient': False, 'protocolMappers': []})
        self.assertFalse(result['sso'][1]['enabled'])
        self.assertTrue(result['sso'][1]['publicClient'])
        self.assertEqual(result['sso'][1]['protocolMappers'], [{'consentRequired': False}])
        self.assertEqual(result['caBundle']['configMap'], {'name': 'custom', 'key': 'ca-bundle.pem',
                                                        'labels': {'keep': 'value'}, 'annotations': {}})
        self.assertEqual(result['unknown'], before['unknown'])

    def test_missing_parent_is_not_invented_and_nullable_null_is_retained(self):
        _, schema = inputs.package_schema(crd_fixture())
        self.assertEqual(inputs.apply_defaults({}, schema), {})
        schema['properties']['network']['default'] = {}
        result = inputs.apply_defaults({}, schema)
        self.assertEqual(result, {'network': {}})  # serviceMesh itself has no default
        schema['properties']['network']['properties']['serviceMesh']['default'] = {}
        self.assertEqual(inputs.apply_defaults({}, schema), {'network': {'serviceMesh': {'mode': 'ambient'}}})
        self.assertIsNone(inputs.apply_defaults(None, {'type': 'array', 'nullable': True, 'default': []}))
        self.assertEqual(inputs.apply_defaults(None, {'type': 'array', 'default': []}), [])
        with self.assertRaises(ValueError):
            inputs.apply_defaults({'nullable': None}, {'type': 'object', 'properties': {'nullable': {'type': 'object'}}})

    def test_map_defaults_are_independent_and_no_unknown_keys_are_pruned(self):
        schema = {'type': 'object', 'additionalProperties': {'type': 'object', 'properties': {
            'enabled': {'type': 'boolean', 'default': True}, 'items': {'type': 'array', 'default': []}}}}
        original = {'first': {'unknown': 'retain'}, 'second': {}}
        result = inputs.apply_defaults(original, schema)
        result['first']['items'].append('local')
        self.assertEqual(result['second']['items'], [])
        self.assertEqual(original, {'first': {'unknown': 'retain'}, 'second': {}})
        self.assertEqual(result['first']['unknown'], 'retain')
        with self.assertRaises(ValueError):
            inputs.apply_defaults(True, {'type': 'integer'})
        with self.assertRaises(ValueError):
            inputs.apply_defaults(list(range(inputs.MAX_NODES + 1)), {'type': 'array'})

    def test_schema_references_and_conditional_defaults_are_not_guessed(self):
        for change in ({'$ref': '#/unsupported'}, {'oneOf': [{'default': {}}]}):
            with self.subTest(change=change):
                crd = crd_fixture()
                crd['spec']['versions'][0]['schema']['openAPIV3Schema']['properties']['spec'].update(change)
                with self.assertRaises(ValueError):
                    inputs.package_schema(crd)
        crd = crd_fixture()
        crd['spec']['versions'][0]['served'] = False
        with self.assertRaises(ValueError):
            inputs.package_schema(crd)

    def test_bound_discovery_refuses_semantic_drift_but_allows_status_only_resource_version(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = driver.Driver(Path(directory) / 'journal.json')
            crd = crd_fixture()
            versions = ['v1', 'monitoring.coreos.com/v1']
            events = []
            instance.guard = lambda: events.append('owned-guard')
            def kube(*args):
                events.append(args[0])
                return '\n'.join(versions) if args[0] == 'api-versions' else json.dumps(crd)
            instance.kube = kube
            bound = copy.deepcopy(instance.bind_render_inputs())
            self.assertEqual(events[0], 'owned-guard')
            crd['metadata']['resourceVersion'] = '9'
            self.assertEqual(instance.observe_render_inputs()['packageCRD']['resourceVersion'], '9')
            self.assertEqual(instance.state['renderInputs'], bound)
            for key, value in [('uid', 'replacement'), ('generation', 2)]:
                saved = crd['metadata'][key]
                crd['metadata'][key] = value
                with self.assertRaisesRegex(ValueError, 'identity/schema changed'):
                    instance.observe_render_inputs()
                crd['metadata'][key] = saved
            versions.append('new.example/v1')
            with self.assertRaisesRegex(ValueError, 'capabilities'):
                instance.observe_render_inputs()
            versions.pop()
            crd['spec']['versions'][0]['schema']['openAPIV3Schema']['properties']['spec']['properties']['sso']['items']['properties']['enabled']['default'] = False
            with self.assertRaisesRegex(ValueError, 'schema changed'):
                instance.observe_render_inputs()

    @unittest.skipUnless(shutil.which('helm'), 'Helm required for real capability-dependent rendering')
    def test_real_helm_render_receives_discovered_monitoring_capability(self):
        for versions in (['v1'], ['monitoring.coreos.com/v1', 'v1']):
            with self.subTest(versions=versions), tempfile.TemporaryDirectory() as directory:
                instance = driver.Driver(Path(directory) / 'journal.json')
                instance.values = {'domain':'capability-fixture.example'}
                instance._package_schema = {'type': 'object'}
                instance.observe_render_inputs = lambda: {'apiVersions': versions}
                commands = []
                def command(args, payload=None):
                    commands.append(args)
                    return subprocess.run(args, input=payload, text=True, capture_output=True, check=True).stdout
                instance.command = command
                package, _ = instance.render('shared')
                self.assertEqual('monitor' in package['spec'], 'monitoring.coreos.com/v1' in versions)
                if 'monitor' in package['spec']:
                    self.assertEqual(len(package['spec']['monitor']), 3)
                self.assertEqual([commands[0][i + 1] for i, v in enumerate(commands[0]) if v == '--api-versions'], versions)

    def test_preflight_mismatch_keeps_only_safe_paths_and_hashes_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = driver.Driver(Path(directory) / 'journal.json')
            instance._last_render_inputs = {'apiVersions': ['v1']}
            expected = {'sso': [{'enabled': False, 'attributes': {}}]}
            actual = {'sso': [{'enabled': True, 'attributes': {'PRIVATE_KEY_CANARY': 'SECRET_VALUE_CANARY'}}]}
            receipt = {'sourceSHA': 'a' * 40, 'runID': '1', 'runAttempt': '1', 'clusterUID': 'cluster'}
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                instance.preflight_mismatch(expected, actual, receipt)
            breadcrumb = json.loads(stdout.getvalue())
            self.assertEqual(set(breadcrumb), {'stage', 'expectedSHA256', 'actualSHA256', 'differingPaths', 'pathsTruncated'})
            self.assertEqual(breadcrumb['stage'], 'preflight-package-mismatch')
            self.assertIn('/spec/sso/0/enabled', breadcrumb['differingPaths'])
            self.assertNotIn('PRIVATE_KEY_CANARY', stdout.getvalue())
            self.assertNotIn('SECRET_VALUE_CANARY', stdout.getvalue())
            self.assertNotIn('renderInputs', stdout.getvalue())
            path = Path(directory) / 'journal.preflight.json'
            data = path.read_bytes()
            self.assertNotIn(b'PRIVATE_KEY_CANARY', data)
            self.assertNotIn(b'SECRET_VALUE_CANARY', data)
            parsed = json.loads(data)
            self.assertIn('/spec/sso/0/enabled', parsed['differingPaths'])
            self.assertNotEqual(parsed['expectedSHA256'], parsed['actualSHA256'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                instance.preflight_mismatch(expected, actual, receipt)
            self.assertEqual(path.read_bytes(), data)


if __name__ == '__main__':
    unittest.main()


class DomainPostrenderTests(unittest.TestCase):
    def plan(self,directory,domain='bound.example'):
        import yaml
        root=Path(directory);config=root/'uds-config.yaml';config.write_text(yaml.safe_dump({'variables':{'takserver':{'DOMAIN':domain,'TAK_IMAGE_TAG':'unchanged'}}}))
        plan=root/'plan.json';plan.write_text(json.dumps({'schema':1,'sourceSHA':'a'*40,'files':{'config':{'path':config.name,'sha256':driver.hashlib.sha256(config.read_bytes()).hexdigest()}}}))
        return plan,config

    def test_only_known_domain_token_changes_and_unbound_token_refuses(self):
        original={'sso':[{'attributes':{'post.logout.redirect.uris':'https://takserver.###ZARF_VAR_DOMAIN###/login/redirect','other':'###ZARF_VAR_OTHER###'},'redirectUris':['https://takserver.###ZARF_VAR_DOMAIN###/login/redirect'],'publicClient':False}]}
        before=copy.deepcopy(original)
        with self.assertRaisesRegex(ValueError,'hash-bound'):inputs.postrender_domain(original)
        result=inputs.postrender_domain(original,'bound.example')
        self.assertEqual(original,before)
        self.assertEqual(result['sso'][0]['redirectUris'],['https://takserver.bound.example/login/redirect'])
        self.assertEqual(result['sso'][0]['attributes']['post.logout.redirect.uris'],result['sso'][0]['redirectUris'][0])
        self.assertEqual(result['sso'][0]['attributes']['other'],'###ZARF_VAR_OTHER###');self.assertFalse(result['sso'][0]['publicClient'])
        self.assertEqual(inputs.postrender_domain({'url':'explicit.example'}),{'url':'explicit.example'})

    def test_plan_source_config_hash_domain_and_paths_are_not_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            plan,config=self.plan(directory)
            binding=inputs.bind_domain_plan(plan,'a'*40);self.assertEqual(binding['DOMAIN'],'bound.example')
            with self.assertRaisesRegex(ValueError,'source differs'):inputs.bind_domain_plan(plan,'b'*40)
            config.write_text('changed')
            with self.assertRaisesRegex(ValueError,'hash differs'):inputs.bind_domain_plan(plan,'a'*40)
        for domain in ('bad/name','bad name','bad\nname','bad..name','-bad.example','bad.example:443'):
            with self.subTest(domain=domain),tempfile.TemporaryDirectory() as directory:
                plan,_=self.plan(directory,domain)
                with self.assertRaisesRegex(ValueError,'DNS name'):inputs.bind_domain_plan(plan,'a'*40)
        with tempfile.TemporaryDirectory() as directory:
            plan,_=self.plan(directory);value=json.loads(plan.read_text());value['files']['config']['path']='../outside';plan.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'unsafe'):inputs.bind_domain_plan(plan,'a'*40)

    @unittest.skipUnless(shutil.which('helm'),'Helm required for real DOMAIN postrender regression')
    def test_actual_helm_raw_values_postrender_both_uris_and_keep_other_sso_drift_visible(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(driver.os.environ,{'GITHUB_SHA':'a'*40}):
            plan,config=self.plan(directory)
            instance=driver.Driver(Path(directory)/'journal');instance.guard=lambda:None
            instance.bind_zarf_domain(plan);instance.values={'domain':'###ZARF_VAR_DOMAIN###'}
            instance._package_schema={'type':'object'};instance.observe_render_inputs=lambda:{'apiVersions':['v1']}
            payloads=[]
            def command(argv,payload=None):
                payloads.append(json.loads(payload));return subprocess.run(argv,input=payload,text=True,capture_output=True,check=True).stdout
            instance.command=command
            rendered,_=instance.render('shared')
            self.assertEqual(payloads[0]['domain'],'###ZARF_VAR_DOMAIN###')
            sso=rendered['spec']['sso'][0];self.assertEqual(sso['redirectUris'],['https://takserver.bound.example/login/redirect'])
            self.assertEqual(sso['attributes']['post.logout.redirect.uris'],sso['redirectUris'][0])
            literal=subprocess.run(['helm','template','uds-takserver-config',str(ROOT/'charts/takserver'),'--namespace','takserver','--set','domain=bound.example'],text=True,capture_output=True,check=True).stdout
            import yaml
            actual=next(x for x in yaml.safe_load_all(literal) if x and x.get('kind')=='Package')
            self.assertEqual(rendered['spec'],actual['spec'])
            altered=copy.deepcopy(actual['spec']);altered['sso'][0]['publicClient']=True
            self.assertNotEqual(rendered['spec'],altered)
            self.assertIn('/spec/sso/0/publicClient',inputs.safe_difference(rendered['spec'],altered)['differingPaths'])
            config.write_text('changed')
            with self.assertRaisesRegex(ValueError,'config hash differs'):instance.render('shared')
