# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Bound read-only Helm capabilities and materialize declared structural defaults."""
import copy
import hashlib
import json
import math
import re

MAX_BYTES = 256 * 1024
MAX_NODES = 8192
MAX_DEPTH = 32
SAFE_FIELDS = set(('spec monitor sso protocolMappers enabled alwaysDisplayInConsole '
                  'standardFlowEnabled serviceAccountsEnabled publicClient consentRequired '
                  'caBundle configMap name key labels annotations network serviceMesh mode '
                  'expose allow direction selector remoteSelector remoteNamespace remoteServiceAccount '
                  'serviceAccount remoteGenerated port ports protocol description kind portName '
                  'targetPort path clientId redirectUris webOrigins attributes secret').split())


def require(value, message):
    if not value:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def api_versions(text):
    require(isinstance(text, str) and len(text.encode()) <= MAX_BYTES, 'API discovery exceeds bound')
    versions = text.splitlines()
    require(0 < len(versions) <= 256 and len(set(versions)) == len(versions) and 'v1' in versions,
            'API discovery must be complete, nonempty and unique')
    require(all(re.fullmatch(r'(?:[a-z0-9][a-z0-9.-]*/)?v[0-9][a-zA-Z0-9]*', v) for v in versions),
            'unsupported API discovery version')
    return sorted(versions)


def _shape(value, depth=0, budget=None):
    budget = [0] if budget is None else budget
    budget[0] += 1
    require(depth <= MAX_DEPTH and budget[0] <= MAX_NODES, 'structural input exceeds bound')
    if isinstance(value, dict):
        require(all(isinstance(k, str) for k in value), 'structural keys must be strings')
        for item in value.values():
            _shape(item, depth + 1, budget)
    elif isinstance(value, list):
        for item in value:
            _shape(item, depth + 1, budget)
    else:
        require(value is None or type(value) in (str, int, bool, float), 'unsupported structural value')
        require(type(value) is not float or math.isfinite(value), 'nonfinite structural value')


def package_schema(crd):
    require(len(encoded(crd)) <= MAX_BYTES, 'Package CRD exceeds bound')
    require(crd.get('apiVersion') == 'apiextensions.k8s.io/v1' and crd.get('kind') == 'CustomResourceDefinition',
            'Package CRD identity differs')
    meta, spec = crd['metadata'], crd['spec']
    require(meta['name'] == 'packages.uds.dev' and isinstance(meta['uid'], str) and meta['uid'] and
            type(meta['generation']) is int and meta['generation'] > 0 and
            isinstance(meta['resourceVersion'], str) and meta['resourceVersion'], 'Package CRD metadata incomplete')
    require(spec.get('group') == 'uds.dev' and spec.get('scope') == 'Namespaced' and
            spec.get('names', {}).get('kind') == 'Package' and spec.get('names', {}).get('plural') == 'packages',
            'Package CRD resource contract differs')
    versions = [v for v in spec['versions'] if v.get('name') == 'v1alpha1']
    require(len(versions) == 1 and versions[0].get('served') is True, 'Package API version is not served')
    schema = versions[0]['schema']['openAPIV3Schema']
    _shape(schema)
    require(schema.get('type') == 'object' and schema['properties']['spec'].get('type') == 'object',
            'Package structural schema differs')
    def supported(node, conditional=False):
        if isinstance(node, dict):
            require('$ref' not in node, 'referenced defaults are unsupported')
            require(not conditional or 'default' not in node, 'conditional defaults are unsupported')
            for key, value in node.items():
                supported(value, conditional or key in ('allOf', 'anyOf', 'oneOf', 'not'))
        elif isinstance(node, list):
            for child in node:
                supported(child, conditional)
    supported(schema)
    record = {'name': meta['name'], 'uid': meta['uid'], 'generation': meta['generation'],
              'resourceVersion': meta['resourceVersion'], 'version': 'v1alpha1', 'schemaSHA256': digest(schema)}
    return record, copy.deepcopy(schema['properties']['spec'])


def apply_defaults(value, schema):
    """Never prune keys or create a missing parent without its own default."""
    _shape(value)
    _shape(schema)
    budget = [0]
    def visit(current, node, depth=0):
        budget[0] += 1
        require(depth <= MAX_DEPTH and budget[0] <= MAX_NODES, 'default materialization exceeds bound')
        if current is None:
            if node.get('nullable') is True:
                return None
            require('default' in node, 'nonnull null without a declared default is unsupported')
            current = copy.deepcopy(node['default'])
        kind = node.get('type')
        if kind == 'object':
            require(isinstance(current, dict), 'expected structural object')
            result = copy.deepcopy(current)
            properties = node.get('properties', {})
            for key, child in properties.items():
                if key in result:
                    result[key] = visit(result[key], child, depth + 1)
                elif 'default' in child:
                    result[key] = visit(copy.deepcopy(child['default']), child, depth + 1)
            additional = node.get('additionalProperties')
            if isinstance(additional, dict):
                for key in set(result) - set(properties):
                    result[key] = visit(result[key], additional, depth + 1)
            return result
        if kind == 'array':
            require(isinstance(current, list), 'expected structural array')
            child = node.get('items', {})
            require(isinstance(child, dict), 'tuple defaults are unsupported')
            return [visit(item, child, depth + 1) for item in current]
        if kind:
            allowed = {'string': (str,), 'boolean': (bool,), 'integer': (int,), 'number': (int, float)}
            require(kind in allowed and type(current) in allowed[kind], 'structural scalar type differs')
        return copy.deepcopy(current)
    result = visit(value, schema)
    require(len(encoded(result)) <= MAX_BYTES, 'defaulted specification exceeds bound')
    return result


def safe_difference(expected, actual):
    """Field paths and whole-object hashes only; unknown map keys stay opaque."""
    _shape(expected); _shape(actual)
    paths = []
    truncated = False
    def segment(key):
        return key if key in SAFE_FIELDS else '<field-' + digest(key)[:12] + '>'
    def add(path):
        nonlocal truncated
        if len(paths) < 64:
            paths.append(path)
        else:
            truncated = True
    def visit(left, right, path):
        if type(left) is not type(right):
            add(path)
        elif isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                child = path + '/' + segment(key)
                if key not in left or key not in right:
                    add(child)
                else:
                    visit(left[key], right[key], child)
        elif isinstance(left, list):
            if len(left) != len(right):
                add(path + '/length')
            for index, (first, last) in enumerate(zip(left, right)):
                visit(first, last, path + '/' + str(index))
        elif left != right:
            add(path)
    visit(expected, actual, '/spec')
    return {'expectedSHA256': digest(expected), 'actualSHA256': digest(actual),
            'differingPaths': paths, 'pathsTruncated': truncated}


def bind_domain_plan(plan_path, source_sha):
    """Read the reviewed staged plan/config; never infer a value from live URLs."""
    from pathlib import Path, PurePosixPath
    import yaml
    require(isinstance(source_sha,str) and re.fullmatch(r'[a-f0-9]{40}',source_sha),'deployment source identity invalid')
    def read(path):
        path=Path(path).absolute()
        require(path.resolve()==path and path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)) and path.stat().st_size<=MAX_BYTES,'deployment binding is not a bounded canonical file')
        data=path.read_bytes();require(len(data)<=MAX_BYTES,'deployment binding exceeds bound')
        return path,data
    plan_path,raw_plan=read(plan_path);plan=json.loads(raw_plan)
    require(plan.get('schema')==1 and plan.get('sourceSHA')==source_sha,'deployment plan source differs')
    item=plan['files']['config'];relative=PurePosixPath(item['path'])
    require(not relative.is_absolute() and '..' not in relative.parts and relative.parts,'unsafe deployment config reference')
    config_path,raw_config=read(plan_path.parent/relative)
    require(hashlib.sha256(raw_config).hexdigest()==item['sha256'],'deployment config hash differs')
    config=yaml.safe_load(raw_config)
    require(isinstance(config,dict) and set(config)=={'variables'} and isinstance(config['variables'],dict) and set(config['variables'])=={'takserver'} and isinstance(config['variables']['takserver'],dict),'deployment variables contract differs')
    domain=config['variables']['takserver']['DOMAIN']
    require(isinstance(domain,str) and 0<len(domain)<=253 and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in domain.split('.')),'bound deployment DOMAIN is not a DNS name')
    return {'plan':str(plan_path),'planSHA256':hashlib.sha256(raw_plan).hexdigest(),'config':str(config_path),'configSHA256':hashlib.sha256(raw_config).hexdigest(),'DOMAIN':domain}


APPLICATION_CHARTS = {'takserver': ('uds-takserver-config', 'takserver-oidc', 'takserver'),
                      'cloudtak': ('uds-cloudtak',)}


def baseline_chart_values(overrides, read_values):
    """Replay only four application charts, using UDS file-then-value order."""
    require(isinstance(overrides, dict) and set(overrides) <= set(APPLICATION_CHARTS), 'unsupported baseline component')
    _shape(overrides)
    require(len(encoded(overrides)) <= MAX_BYTES, 'baseline overrides exceed bound')
    result = {component: {chart: {} for chart in charts} for component, charts in APPLICATION_CHARTS.items()}
    def merge(left, right):
        require(isinstance(right, dict), 'baseline chart values must be objects')
        for key, value in right.items():
            if isinstance(value, dict) and isinstance(left.get(key), dict):
                merge(left[key], value)
            else:
                left[key] = copy.deepcopy(value)
    for component, charts in overrides.items():
        require(isinstance(charts, dict) and set(charts) <= set(APPLICATION_CHARTS[component]), 'unsupported baseline chart')
        for chart, override in charts.items():
            require(isinstance(override, dict) and set(override) <= {'valuesFiles', 'values', 'variables'}, 'unsupported baseline chart override')
            require(all(isinstance(override.get(key, []), list) and len(override.get(key, [])) <= 64
                        for key in ('valuesFiles', 'values', 'variables')), 'baseline override inventory exceeds bound')
            # Variable declarations do not supply Helm values; retain their exact
            # reviewed identity in the source binding, never invent their values.
            for declaration in override.get('variables', []):
                require(isinstance(declaration, dict) and set(declaration) == {'name', 'description', 'path'}
                        and component == 'cloudtak' and chart == 'uds-cloudtak'
                        and declaration['name'] == 'CLOUDTAK_SSO_GROUPS' and declaration['path'] == 'sso.groups',
                        'unsupported baseline chart variable')
            for path in override.get('valuesFiles', []):
                require(isinstance(path, str), 'invalid baseline values reference')
                value = read_values(path)
                _shape(value)
                require(len(encoded(value)) <= MAX_BYTES, 'baseline chart file exceeds bound')
                merge(result[component][chart], value)
            for entry in override.get('values', []):
                require(isinstance(entry, dict) and set(entry) == {'path', 'value'}, 'unsupported baseline value')
                require(isinstance(entry['path'], str), 'unsupported baseline value path')
                require(not isinstance(entry['value'], dict), 'object-valued baseline entries require an explicit merge contract')
                parts = entry['path'].split('.')
                require(parts and all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts), 'unsupported baseline value path')
                current = result[component][chart]
                for part in parts[:-1]:
                    require(part not in current or isinstance(current[part], dict), 'baseline value path conflict')
                    current = current.setdefault(part, {})
                current[parts[-1]] = copy.deepcopy(entry['value'])
    for chart in result['takserver'].values():
        require('workloadIdentityPhase' not in chart and 'TAK_WORKLOAD_IDENTITY_PHASE' not in encoded(chart).decode(),
                'baseline cannot override identity phase')
    _shape(result)
    require(len(encoded(result)) <= MAX_BYTES, 'baseline chart values exceed bound')
    return result


def bind_chart_overrides(plan_path, source_sha, repository_root):
    """Bind reviewed source closure to the same prepared baseline candidate."""
    import os
    from pathlib import Path
    import subprocess
    import yaml
    domain = bind_domain_plan(plan_path, source_sha)
    root = Path(repository_root).resolve()
    sources = {}
    def read(path):
        path = Path(path)
        require(not any(p.is_symlink() for p in (path, *path.parents)), 'baseline source has a symbolic link')
        path = path.resolve()
        require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'baseline source is not bounded')
        raw = path.read_bytes()
        require(len(raw) <= MAX_BYTES, 'baseline source exceeds bound')
        return path, raw
    def reviewed(path, parse=True):
        path, raw = read(path)
        require(root in path.parents, 'baseline source escapes repository')
        relative = path.relative_to(root).as_posix()
        result = subprocess.run(['git', 'show', source_sha + ':' + relative], cwd=root, capture_output=True, timeout=5,
            env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'})
        require(result.returncode == 0 and result.stdout == raw, 'baseline source differs from reviewed commit')
        sources[relative] = hashlib.sha256(raw).hexdigest()
        return yaml.safe_load(raw) if parse else None
    for relative in ('tests/velero-ownership/candidate.py', 'tests/velero-ownership/prepare.py'):
        reviewed(root / relative, parse=False)
    bundle_path = root / 'bundle/full/uds-bundle.yaml'
    bundle = reviewed(bundle_path)
    packages = [package for package in bundle['packages'] if package['name'] == 'takserver']
    require(len(packages) == 1, 'baseline application package differs')
    package = packages[0]
    plan_directory = Path(domain['plan']).parent
    _receipt_path, raw_receipt = read(plan_directory / 'candidate.json')
    receipt = json.loads(raw_receipt)
    _candidate_path, candidate_raw = read(plan_directory / 'core/uds-bundle.yaml')
    require(type(receipt.get('schema')) is int and receipt['schema'] == 1 and receipt['sourceSHA'] == source_sha
            and receipt['files']['core/uds-bundle.yaml'] == hashlib.sha256(candidate_raw).hexdigest(),
            'prepared baseline candidate hash differs')
    candidate = yaml.safe_load(candidate_raw)
    prepared = [item for item in candidate['packages'] if item['name'] == 'takserver']
    require(len(prepared) == 1, 'prepared baseline application differs')
    expected = copy.deepcopy(package)
    if 'path' in expected:
        expected['path'] = os.path.relpath((bundle_path.parent / expected['path']).resolve(), plan_directory / 'core')
    for charts in expected.get('overrides', {}).values():
        for chart in charts.values():
            if 'valuesFiles' in chart:
                chart['valuesFiles'] = [os.path.relpath((bundle_path.parent / path).resolve(), plan_directory / 'core')
                                       for path in chart['valuesFiles']]
    require(prepared[0] == expected, 'prepared baseline application overrides differ')
    values = baseline_chart_values(package['overrides'], lambda path: reviewed(bundle_path.parent / path))
    return {'chartOverrides': values, 'chartOverridesSHA256': digest(values), 'chartOverrideSources': sources,
            'candidateSHA256': hashlib.sha256(raw_receipt).hexdigest(),
            'candidateManifestSHA256': hashlib.sha256(candidate_raw).hexdigest()}


def postrender_domain(value, domain=None):
    """Emulate only Zarf's known DOMAIN token, leaving other Helm data intact."""
    _shape(value)
    marker='###ZARF_VAR_DOMAIN###'
    def visit(node):
        if isinstance(node,str):
            if marker not in node:return node
            require(domain is not None,'Zarf DOMAIN token requires a hash-bound candidate plan')
            return node.replace(marker,domain)
        if isinstance(node,dict):
            require(all(marker not in key for key in node),'DOMAIN token in an unsupported structural key')
            return {key:visit(item) for key,item in node.items()}
        if isinstance(node,list):return [visit(item) for item in node]
        return copy.deepcopy(node)
    result=visit(value);require(len(encoded(result))<=MAX_BYTES,'postrendered specification exceeds bound')
    return result
