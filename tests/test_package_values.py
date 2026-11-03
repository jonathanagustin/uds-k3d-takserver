# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Package values default to the Zarf variables, and only override them.

Each case renders the package with `uds zarf dev inspect manifests`, which
runs Helm and then replaces `###ZARF_VAR_*###` the way a deploy does. Needs
`uds` on PATH, network for the upstream chart, and the Pepr chart in
pepr/dist (pepr/build.sh). No cluster.
"""

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE = "c72fcf944a4f43bbb386d22371aa640f"
TAK_APPS = ("takserver-api", "takserver-messaging", "takserver-config", "takserver-plugins")
_cache = {}


def render(variables=(), values=()):
    key = (tuple(variables), tuple(values))
    if key in _cache:
        return _cache[key]
    cmd = ["uds", "zarf", "dev", "inspect", "manifests", ".", "--flavor", "upstream",
           "--no-color", "--log-level", "warn"]
    for pair in variables:
        cmd += ["--deploy-set-variables", pair]
    for pair in values:
        cmd += ["--set-values", pair]
    out = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout
    docs = [doc for doc in yaml.safe_load_all(out) if isinstance(doc, dict)]
    _cache[key] = (out, docs)
    return out, docs


def find(docs, kind, name):
    for doc in docs:
        if doc.get("kind") == kind and (doc.get("metadata") or {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind}/{name} in the rendered package")


def gateway_hosts(docs):
    """Hosts per server on the standard-ports Gateway: cert enrollment and stream."""
    gateway = find(docs, "Gateway", "takserver-standard-ports")
    return {server["port"]["name"]: server["hosts"] for server in gateway["spec"]["servers"]}


def core_config(docs):
    for doc in docs:
        if doc.get("kind") == "ConfigMap":
            for body in (doc.get("data") or {}).values():
                if "openIdDiscoveryConfiguration" in str(body):
                    return body
    raise AssertionError("no CoreConfig with openIdDiscoveryConfiguration")


def watcher_env(docs):
    deploy = find(docs, "Deployment", f"pepr-{MODULE}-watcher")
    container = deploy["spec"]["template"]["spec"]["containers"][0]
    return {item["name"]: item.get("value") for item in container.get("env") or []}


def tak_tags(docs):
    tags = set()
    for app in TAK_APPS:
        deploy = find(docs, "Deployment", app)
        for container in deploy["spec"]["template"]["spec"]["containers"]:
            if "/uds-k3d-takserver/" in container["image"]:
                tags.add(container["image"].rsplit(":", 1)[1])
    return tags


def hostnames(text, domain):
    return set(re.findall(r"[a-z0-9-]+\." + re.escape(domain) + r"\b", text))


# CI installs uds. A local run without it skips instead of failing.
@unittest.skipUnless(shutil.which("uds") or os.environ.get("CI"), "uds CLI is not installed")
class PackageValuesTests(unittest.TestCase):
    def assert_domain(self, out, docs, domain, old="uds.dev"):
        hosts = gateway_hosts(docs)
        expected = [f"takserver.{domain}", f"takserver-stream.{domain}"]
        self.assertEqual(hosts["tls-tak-cert"], expected)
        self.assertEqual(hosts["tcp-tak-stream"], expected)
        virtual = find(docs, "VirtualService", "takserver-standard-ports")
        self.assertEqual(virtual["spec"]["hosts"], expected)
        config = core_config(docs)
        self.assertIn(f'redirectUri="https://takserver.{domain}/login/redirect"', config)
        self.assertIn(f'configurationUri="https://sso.{domain}/realms/uds/', config)
        self.assertEqual(watcher_env(docs)["DOMAIN"], domain)
        self.assertIn(f"https://map.{domain}", out)
        if domain != old:
            self.assertEqual(hostnames(out, old), set())
        self.assertNotIn("###ZARF_VAR_", out)

    def test_defaults_match_the_variables(self):
        out, docs = render()
        self.assert_domain(out, docs, "uds.dev")
        env = watcher_env(docs)
        self.assertEqual(env["IN_CLUSTER_DNS"], "true")
        self.assertEqual(env["PASSTHROUGH_HOSTS"], "takserver-api takserver-stream")
        self.assertEqual(tak_tags(docs), {"5.7-RELEASE-14"})

    def test_domain_variable_moves_the_cert_and_gateway_hosts(self):
        out, docs = render(variables=["DOMAIN=example.com"])
        self.assert_domain(out, docs, "example.com")

    def test_the_other_variables_still_apply(self):
        _out, docs = render(variables=[
            "TAK_IMAGE_TAG=9.9-RELEASE-9",
            "IN_CLUSTER_DNS=false",
            "PASSTHROUGH_HOSTS=takserver-api",
        ])
        env = watcher_env(docs)
        self.assertEqual(env["IN_CLUSTER_DNS"], "false")
        self.assertEqual(env["PASSTHROUGH_HOSTS"], "takserver-api")
        self.assertTrue(env["RENDER_IMAGE"].endswith(":9.9-RELEASE-9"))
        self.assertEqual(tak_tags(docs), {"9.9-RELEASE-9"})

    def test_storage_classes_are_unset_by_default(self):
        _out, docs = render()
        for name in ("takserver-postgresql", "cloudtak-postgis"):
            claim = find(docs, "StatefulSet", name)["spec"]["volumeClaimTemplates"][0]
            self.assertNotIn("storageClassName", claim["spec"], name)

    def test_storage_class_variables_set_each_volume(self):
        _out, docs = render(variables=[
            "POSTGRES_STORAGE_CLASS=tak-class",
            "CLOUDTAK_STORAGE_CLASS=cloudtak-class",
        ])
        tak = find(docs, "StatefulSet", "takserver-postgresql")["spec"]["volumeClaimTemplates"][0]
        cloud = find(docs, "StatefulSet", "cloudtak-postgis")["spec"]["volumeClaimTemplates"][0]
        self.assertEqual(tak["spec"]["storageClassName"], "tak-class")
        self.assertEqual(cloud["spec"]["storageClassName"], "cloudtak-class")

    def test_a_package_value_overrides_the_variable(self):
        out, docs = render(variables=["DOMAIN=example.com"], values=["global.domain=values.example"])
        self.assert_domain(out, docs, "values.example")
        self.assertEqual(hostnames(out, "example.com"), set())

    def test_uptime_checks_probe_pages_the_apps_serve_themselves(self):
        _out, docs = render()
        expected = {"checks": {"paths": ["/login"]}}
        uptime = {
            pkg: {e["description"]: e.get("uptime") for e in find(docs, "Package", pkg)["spec"]["network"]["expose"]}
            for pkg in ("takserver", "cloudtak")
        }
        self.assertEqual(uptime["takserver"]["tak-web-http"], expected)
        self.assertEqual(uptime["cloudtak"]["cloudtak-map"], expected)
        for passthrough in ("tak-api-https", "tak-api-cert", "tak-messaging-streaming"):
            self.assertIsNone(uptime["takserver"][passthrough])


if __name__ == "__main__":
    unittest.main()
