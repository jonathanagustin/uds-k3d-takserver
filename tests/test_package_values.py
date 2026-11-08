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
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE = "c72fcf944a4f43bbb386d22371aa640f"
TAK_APPS = ("takserver-api", "takserver-messaging", "takserver-config", "takserver-plugins")
_cache = {}


_DOWNLOAD_URL = re.compile(r"(?:could not download|failed to fetch)\s+(https://[^\s]+)", re.IGNORECASE)
_STATUS_NEAR = re.compile(
    r"HTTP\s+(\d{3})\b|:\s*(\d{3})\s+Gateway\b|(\d{3})\s+Gateway\s+Time-?out\b",
    re.IGNORECASE,
)
_STATUS_ANY = re.compile(r"\bHTTP\s+(\d{3})\b|\b(\d{3})\s+Gateway\s+Time-?out\b", re.IGNORECASE)
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")
_BUILD_DEPS = "unable to build dependencies"


def _status_code(match):
    return next(group for group in match.groups() if group)


def _public_download_url(raw):
    """Host and path of one https download. Userinfo, query, and fragment stay out."""
    raw = raw.split("-----", 1)[0].rstrip(".,;:")
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments or len(segments) > 8:
        return None
    if any(_SAFE_SEGMENT.fullmatch(segment) is None for segment in segments):
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(("https", host, "/" + "/".join(segments), "", ""))


def render_failure(result):
    """Exit status plus a dependency URL and HTTP status, when stderr has them.

    Rendered manifests and every other child byte stay out of the message.
    """
    stderr = result.stderr if isinstance(result.stderr, str) else ""
    code = result.returncode if isinstance(result.returncode, int) else "unknown"
    facts = []
    if _BUILD_DEPS in stderr:
        facts.append(_BUILD_DEPS)
    seen = {}
    order = []
    for match in _DOWNLOAD_URL.finditer(stderr):
        url = _public_download_url(match.group(1))
        if url is None:
            continue
        status_match = _STATUS_NEAR.search(stderr[match.end():match.end() + 160])
        status = _status_code(status_match) if status_match else None
        if url not in seen:
            order.append(url)
            seen[url] = status
        elif status and not seen[url]:
            seen[url] = status
    if order and any(seen[url] is None for url in order):
        statuses = {_status_code(item) for item in _STATUS_ANY.finditer(stderr)}
        if len(statuses) == 1:
            only = statuses.pop()
            for url in order:
                seen[url] = seen[url] or only
    for url in order:
        item = f"could not download {url}"
        if seen[url]:
            item += f": HTTP {seen[url]}"
        facts.append(item)
    if not order:
        status_match = _STATUS_ANY.search(stderr)
        if status_match:
            facts.append(f"HTTP {_status_code(status_match)}")
    detail = "; ".join(facts) if facts else "no allowlisted diagnostic"
    return f"package render failed ({code}): {detail}"


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
    result = subprocess.run(cmd, cwd=ROOT, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(render_failure(result))
    out = result.stdout
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


def admission_env(docs):
    deploy = find(docs, "Deployment", f"pepr-{MODULE}")
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
    def test_takclient_watcher_can_enroll_and_revoke_with_its_own_identity(self):
        _out, docs = render()
        account = f"pepr-{MODULE}-watcher"
        rules = [rule for rule in find(docs, "Package", "takserver")["spec"]["network"]["allow"]
                 if rule.get("remoteServiceAccount") == account]
        self.assertEqual(sorted(rule["port"] for rule in rules), [8443, 8446])
        for rule in rules:
            self.assertEqual(rule["direction"], "Ingress")
            self.assertEqual(rule["selector"], {"app": "takserver-api"})
            self.assertEqual(rule["remoteNamespace"], "pepr-system")
        self.assertIn('x509checkRevocation="true"', core_config(docs))

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

    def test_plugins_memory_reaches_admission_and_the_watcher(self):
        _out, docs = render()
        admission = admission_env(docs)
        for env in (watcher_env(docs), admission):
            self.assertEqual(env["PLUGINS_MEMORY_REQUEST"], "320Mi")
            self.assertEqual(env["PLUGINS_MEMORY_LIMIT"], "512Mi")
        _out, docs = render(variables=["PLUGINS_MEMORY_REQUEST=400Mi", "PLUGINS_MEMORY_LIMIT=1Gi"])
        for env in (watcher_env(docs), admission_env(docs)):
            self.assertEqual(env["PLUGINS_MEMORY_REQUEST"], "400Mi")
            self.assertEqual(env["PLUGINS_MEMORY_LIMIT"], "1Gi")
        _out, docs = render(
            variables=["PLUGINS_MEMORY_LIMIT=1Gi"],
            values=["tak.plugins.memoryRequest=640Mi", "tak.plugins.memoryLimit=2Gi"],
        )
        for env in (watcher_env(docs), admission_env(docs)):
            self.assertEqual(env["PLUGINS_MEMORY_REQUEST"], "640Mi")
            self.assertEqual(env["PLUGINS_MEMORY_LIMIT"], "2Gi")

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

    def test_health_checks_cover_the_client_ports(self):
        _out, docs = render()
        expose = {e["description"]: e for e in find(docs, "Package", "takserver")["spec"]["network"]["expose"]}
        health = expose["tak-health"]
        self.assertEqual(health["uptime"], {"checks": {"paths": ["/stream", "/api", "/enroll"]}})
        self.assertEqual(health["gateway"], "admin")
        self.assertEqual(health["annotations"], {"uds.dev/visible": "false"})
        pod = find(docs, "Deployment", "tak-health")["spec"]["template"]["spec"]
        secrets = [v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v]
        self.assertEqual(secrets, ["tak-health-client"])
        # Its own key is not encrypted, so the pod reads no other Secret.
        self.assertNotIn("secretKeyRef", str(pod))
        env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
        self.assertEqual(env["INTERVAL_SECONDS"], "30")
        self.assertEqual(env["STALE_SECONDS"], "90")
        job = find(docs, "Job", "takserver-cert-init")
        # The cert-init Job runs issue-health-cert.sh, which is inlined.
        self.assertIn("Issued client certificate CN=${cn}", str(job))

    def test_health_package_value_turns_it_off(self):
        _out, docs = render(values=["health.enabled=false"])
        expose = {e["description"] for e in find(docs, "Package", "takserver")["spec"]["network"]["expose"]}
        self.assertNotIn("tak-health", expose)
        names = {(d.get("kind"), (d.get("metadata") or {}).get("name")) for d in docs}
        self.assertNotIn(("Deployment", "tak-health"), names)
        self.assertNotIn(("Service", "tak-health"), names)
        self.assertNotIn("Issued client certificate", str(find(docs, "Job", "takserver-cert-init")))


_NATS_CHART = "https://github.com/nats-io/k8s/releases/download/nats-1.0.1/nats-1.0.1.tgz"
_DEPENDENCY_FAILURE = (
    "unable to build dependencies for the chart: "
    f"could not download {_NATS_CHART}: failed to fetch {_NATS_CHART} : 504 Gateway Time-out"
)
_DEPENDENCY_DIAGNOSTIC = (
    "package render failed (1): unable to build dependencies; "
    f"could not download {_NATS_CHART}: HTTP 504"
)


class RenderFailureTests(unittest.TestCase):
    def _message(self, stderr, stdout="", variable="DOMAIN=failure.example"):
        result = subprocess.CompletedProcess(
            args=["uds"], returncode=1, stdout=stdout, stderr=stderr,
        )
        with mock.patch.object(subprocess, "run", return_value=result):
            with self.assertRaises(AssertionError) as caught:
                render(variables=[variable])
        return str(caught.exception)

    def test_dependency_failure_reports_the_url_and_status(self):
        message = self._message(_DEPENDENCY_FAILURE, variable="DOMAIN=dependency.example")
        self.assertEqual(message, _DEPENDENCY_DIAGNOSTIC)

    def test_failed_render_omits_short_credentials(self):
        dirty = (
            "https://ci-user:hunter2@github.com/nats-io/k8s/releases/download/"
            "nats-1.0.1/nats-1.0.1.tgz?access_token=short-sensitive-token"
        )
        stderr = (
            "Authorization: Bearer short-sensitive-token\n"
            "unable to build dependencies for the chart: "
            f"could not download {dirty}: failed to fetch {dirty} : 504 Gateway Time-out"
        )
        message = self._message(stderr, variable="DOMAIN=credential.example")
        self.assertEqual(message, _DEPENDENCY_DIAGNOSTIC)
        self.assertNotIn("short-sensitive-token", message)
        self.assertNotIn("hunter2", message)
        self.assertNotIn("ci-user", message)
        self.assertNotIn("access_token", message)
        self.assertNotIn("Bearer", message)

    def test_failed_render_omits_secret_yaml(self):
        secret = "apiVersion: v1\nkind: Secret\ndata:\n  password: c2VjcmV0\n"
        message = self._message(secret + _DEPENDENCY_FAILURE, stdout=secret, variable="DOMAIN=secret.example")
        self.assertEqual(message, _DEPENDENCY_DIAGNOSTIC)
        self.assertNotIn("c2VjcmV0", message)
        self.assertNotIn("kind: Secret", message)
        self.assertNotIn("password", message)

    def test_failed_render_omits_incomplete_pem(self):
        pem = "-----BEGIN PRIVATE KEY-----\nSHORTKEYFRAGMENT"
        message = self._message(pem + "\n" + _DEPENDENCY_FAILURE, variable="DOMAIN=pem.example")
        self.assertEqual(message, _DEPENDENCY_DIAGNOSTIC)
        self.assertNotIn("SHORTKEYFRAGMENT", message)
        self.assertNotIn("BEGIN PRIVATE KEY", message)

    def test_failed_render_omits_stdout(self):
        stdout = "UNIQUE_STDOUT_MARKER\nkind: Secret\ndata:\n  token: stdout-only-secret\n"
        message = self._message(_DEPENDENCY_FAILURE, stdout=stdout, variable="DOMAIN=stdout.example")
        self.assertEqual(message, _DEPENDENCY_DIAGNOSTIC)
        self.assertNotIn("UNIQUE_STDOUT_MARKER", message)
        self.assertNotIn("stdout-only-secret", message)

    def test_http_status_survives_a_complete_pem_without_copying_it(self):
        stderr = (
            "helm pull failed: HTTP 504\n"
            "-----BEGIN PRIVATE KEY-----\nSECRETKEYDATA\n-----END PRIVATE KEY-----\n"
        )
        message = self._message(stderr, variable="DOMAIN=status.example")
        self.assertEqual(message, "package render failed (1): HTTP 504")
        self.assertNotIn("SECRETKEYDATA", message)
        self.assertNotIn("PRIVATE KEY", message)


if __name__ == "__main__":
    unittest.main()
