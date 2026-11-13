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
