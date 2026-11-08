# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""CA trial keeps existing trust settings and safely restores after failures."""

import base64
import copy
import importlib.util
import http.server
import json
import os
import shutil
import ssl
import tempfile
import threading
from types import SimpleNamespace
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("trust_live", Path(__file__).with_name("trust-bundle-live.py"))
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def pem(name):
    return "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(name.encode()).decode() + "\n-----END CERTIFICATE-----\n"


class FakeKubectl:
    def __init__(self, existing=True):
        self.saved = base64.b64encode(pem("original").encode()).decode() if existing else live.MISSING
        bundle = {"includePublicCerts": True, "includeDoDCerts": False}
        if existing:
            bundle["certs"] = self.saved
        self.current = {"metadata": {"resourceVersion": "1", "generation": 1}, "status": {"phase": "Ready", "observedGeneration": 1}, "spec": {"caBundle": bundle, "policy": {"unchanged": True}}}
        self.generation = 0
        self.operations = []
        self.fail_after_patch = False
        self.fail_discovery = False
        self.discovery_checks = []
        self.restart_calls = []
        self.prune_calls = []
        self.stale_bundles = {}

    def config(self):
        return copy.deepcopy(self.current)

    def patch(self, operations):
        self.operations.append(operations)
        for operation in operations:
            path = operation["path"]
            if operation["op"] == "test":
                assert operation["value"] == self.current["metadata"]["resourceVersion"]
            elif path == "/spec/caBundle/certs":
                if operation["op"] == "remove":
                    self.current["spec"]["caBundle"].pop("certs", None)
                else:
                    self.current["spec"]["caBundle"]["certs"] = operation["value"]
            elif path == "/spec/caBundle":
                if operation["op"] == "remove":
                    del self.current["spec"]["caBundle"]
                else:
                    self.current["spec"]["caBundle"] = operation["value"]
        self.generation += 1
        self.current["metadata"]["resourceVersion"] = str(self.generation + 1)
        self.current["metadata"]["generation"] = self.generation + 1
        self.current["status"] = {"phase": "Ready", "observedGeneration": self.generation + 1}
        if self.fail_after_patch:
            self.fail_after_patch = False
            raise TimeoutError("response timed out after API accepted patch")

    def bundle(self, _namespace):
        if _namespace in self.stale_bundles:
            return self.stale_bundles[_namespace]
        value = live.certs_value(self.current)
        content = "" if value is live.MISSING else base64.b64decode(value).decode()
        flags = self.current.get("spec", {}).get("caBundle", {})
        if flags.get("includePublicCerts"):
            content += pem("public-root")
        if flags.get("includeDoDCerts"):
            content += pem("dod-root")
        return content

    def configured_roots(self, _config):
        value = live.certs_value(self.current)
        content = "" if value is live.MISSING else base64.b64decode(value).decode()
        flags = self.current.get("spec", {}).get("caBundle", {})
        if flags.get("includePublicCerts"):
            content += pem("public-root")
        if flags.get("includeDoDCerts"):
            content += pem("dod-root")
        return live.fingerprints(content)

    def prune_trial_roots(self, namespace, roots):
        self.prune_calls.append((namespace, roots))
        if namespace in self.stale_bundles:
            self.stale_bundles[namespace] = live.without_trial_roots(self.stale_bundles[namespace], roots)

    def pods(self):
        return {f"{ns}/{name}": {f"{name}-{self.generation}"} for ns, name in live.WORKLOADS}

    def discovery(self, domain, fingerprint):
        self.discovery_checks.append((domain, fingerprint))
        if self.fail_discovery:
            raise RuntimeError("SSO failed")
        return "SSO discovery passed"

    def run(self, *args):
        self.restart_calls.append(args)
        self.generation += 1
        return ""


class TrustBundleLiveTests(unittest.TestCase):
    def test_negative_controls_reject_only_certificate_authority_errors(self):
        script = Path(__file__).with_name("sso-trust-class.test.mjs")
        result = subprocess.run(
            ["node", "--test", str(script)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        source = Path(__file__).with_name("trust-bundle-live.py").read_text()
        discovery = source.split("def discovery", 1)[1]
        self.assertIn("sso-trust-class.mjs", source)
        self.assertIn("negativeControl", discovery)
        self.assertNotIn("publiclyTrusted=false", discovery)
        self.assertNotIn("unrelatedRejected=true", discovery)
    def test_creating_a_missing_namespace_bundle_does_not_require_reload(self):
        kube = FakeKubectl(existing=False)

        def bundle(_namespace):
            value = live.certs_value(kube.current)
            return "" if value is live.MISSING else base64.b64decode(value).decode()

        kube.bundle = bundle
        kube.signing_status = lambda _domain: "NEED_CA " + base64.b64encode(pem("signer").encode()).decode()
        kube.pods = lambda: {f"{ns}/{name}": {"same-uid"} for ns, name in live.WORKLOADS}
        trial = live.Trial(kube, "uds.dev")
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            trial.ensure_signing_ca()
        self.assertTrue(live.fingerprints(pem("signer")) <= live.fingerprints(kube.bundle("cloudtak")))
        self.assertTrue(live.fingerprints(pem("signer")) <= live.fingerprints(kube.bundle("takserver")))

    def test_updating_an_existing_bundle_still_requires_reload(self):
        kube = FakeKubectl()
        kube.signing_status = lambda _domain: "NEED_CA " + base64.b64encode(pem("signer").encode()).decode()
        kube.pods = lambda: {f"{ns}/{name}": {"same-uid"} for ns, name in live.WORKLOADS}
        trial = live.Trial(kube, "uds.dev")
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            with self.assertRaisesRegex(ValueError, "takserver/takserver-api, takserver/takserver-messaging, cloudtak/cloudtak still has its pre-rotation pod UID"):
                trial.ensure_signing_ca()

    def test_signing_ca_bootstrap_tracks_existing_bundles_per_namespace(self):
        kube = FakeKubectl(existing=False)
        kube.current["spec"]["caBundle"]["includePublicCerts"] = False

        def bundle(namespace):
            value = live.certs_value(kube.current)
            content = "" if value is live.MISSING else base64.b64decode(value).decode()
            return content + (pem("public-root") if namespace == "takserver" else "")

        kube.bundle = bundle
        kube.signing_status = lambda _domain: "NEED_CA " + base64.b64encode(pem("signer").encode()).decode()
        kube.pods = lambda: {f"{ns}/{name}": {f"{name}-{kube.generation}" if ns == "takserver" else "unchanged-first-bundle"}
                            for ns, name in live.WORKLOADS}
        trial = live.Trial(kube, "uds.dev")
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            trial.ensure_signing_ca()
            # Bootstrap permits the first CloudTAK observation, but a later
            # actual rotation still requires its replacement rather than skip it.
            with self.assertRaisesRegex(ValueError, "cloudtak/cloudtak still has its pre-rotation pod UID"):
                trial.phase(pem("trial"))

    def test_restore_reports_absent_and_leftover_namespace_bundles(self):
        self.assertFalse(live.automatic_reload_expected(False))
        self.assertTrue(live.automatic_reload_expected(True))
        kube = FakeKubectl(existing=False)

        def bundle(_namespace):
            value = live.certs_value(kube.current)
            return "" if value is live.MISSING else base64.b64decode(value).decode()

        kube.bundle = bundle
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            trial.restore()
        self.assertIs(live.certs_value(kube.current), live.MISSING)
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        original = kube.bundle
        with patch.object(kube, "bundle", side_effect=lambda namespace: original(namespace) + pem("unexpected-root")), \
                patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            with self.assertRaisesRegex(ValueError, "original CA bundles have not returned: takserver is .* still present"):
                trial.restore()

    def test_stale_core_bundle_cleanup_removes_only_trial_roots(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        temporary = trial.phase(pem("temporary"))
        for namespace in ("takserver", "cloudtak"):
            kube.stale_bundles[namespace] = kube.bundle(namespace) + pem("unrelated-admin-root")
        kube.current["spec"]["caBundle"]["includeDoDCerts"] = True
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            trial.restore()
        self.assertEqual(len(kube.prune_calls), 2)
        for content in kube.stale_bundles.values():
            roots = live.fingerprints(content)
            self.assertNotIn(temporary, roots)
            self.assertTrue(live.fingerprints(pem("original") + pem("unrelated-admin-root")) <= roots)
        self.assertTrue(kube.current["spec"]["caBundle"]["includeDoDCerts"])
        self.assertEqual(len(kube.restart_calls), len(live.WORKLOADS))

    def test_cleanup_waits_for_core_reconciliation_before_pruning(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        kube.stale_bundles = {ns: kube.bundle(ns) for ns in ("takserver", "cloudtak")}
        apply = kube.patch

        def still_pending(operations):
            apply(operations)
            kube.current["status"] = {"phase": "Pending", "observedGeneration": 1}

        with patch.object(kube, "patch", side_effect=still_pending), \
                patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            with self.assertRaisesRegex(ValueError, "restored CA generation"):
                trial.restore()
        self.assertEqual(kube.prune_calls, [])
        self.assertEqual(kube.restart_calls, [])

    def test_cleanup_preserves_a_trial_signer_now_enabled_by_concurrent_flags(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("dod-root"))
        for namespace in ("takserver", "cloudtak"):
            kube.stale_bundles[namespace] = kube.bundle(namespace)
        kube.current["spec"]["caBundle"]["includeDoDCerts"] = True
        with patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            trial.restore()
        self.assertEqual(kube.prune_calls, [])
        self.assertTrue(live.fingerprints(pem("dod-root")) <= live.fingerprints(kube.bundle("cloudtak")))

    def test_cleanup_rejects_roots_reintroduced_after_the_consumer_restart(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        run = kube.run

        def reintroduce(*args):
            result = run(*args)
            kube.stale_bundles["takserver"] = kube.bundle("takserver") + pem("temporary")
            return result

        with patch.object(kube, "run", side_effect=reintroduce), \
                patch.object(live, "wait_for", side_effect=lambda check, *_args, **_kwargs: check()):
            with self.assertRaisesRegex(ValueError, "original CA bundles"):
                trial.restore()
        self.assertEqual(kube.prune_calls, [])

    def test_configmap_pruning_is_owner_scoped_and_compare_and_swap_guarded(self):
        content = pem("temporary") + pem("temporary-signer") + pem("concurrent-admin-root")
        resource = {"metadata": {"name": "uds-trust-bundle", "namespace": "cloudtak", "uid": "original-uid", "resourceVersion": "12",
                                 "labels": {"uds/ca-bundle": "true", "uds/package": "cloudtak"},
                                 "ownerReferences": [{"kind": "Package", "name": "cloudtak", "apiVersion": "uds.dev/v1alpha1"}]},
                    "data": {"ca-bundle.pem": content, "other-key": "unchanged"}}
        kube = live.Kubectl()
        with patch.object(kube, "run", side_effect=[json.dumps(resource), ""]) as run:
            kube.prune_trial_roots("cloudtak", live.fingerprints(pem("temporary") + pem("temporary-signer")))
        args = run.call_args.args
        self.assertEqual(args[:5], ("patch", "configmap", "uds-trust-bundle", "-n", "cloudtak"))
        operations = json.loads(args[-1])
        self.assertEqual(operations[:3], [
            {"op": "test", "path": "/metadata/uid", "value": "original-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "12"},
            {"op": "test", "path": "/data/ca-bundle.pem", "value": content},
        ])
        self.assertEqual(operations[-1]["path"], "/data/ca-bundle.pem")
        self.assertEqual(live.fingerprints(operations[-1]["value"]), live.fingerprints(pem("concurrent-admin-root")))
        resource["metadata"]["labels"]["uds/package"] = "somebody-else"
        with patch.object(kube, "run", return_value=json.dumps(resource)) as run:
            with self.assertRaisesRegex(ValueError, "not owned by Core"):
                kube.prune_trial_roots("cloudtak", live.fingerprints(pem("temporary") + pem("temporary-signer")))
        self.assertEqual(run.call_count, 1)

    def test_a_configmap_version_conflict_is_not_silently_overwritten(self):
        resource = {"metadata": {"name": "uds-trust-bundle", "namespace": "takserver", "uid": "uid", "resourceVersion": "12",
                                 "labels": {"uds/ca-bundle": "true", "uds/package": "takserver"},
                                 "ownerReferences": [{"kind": "Package", "name": "takserver", "apiVersion": "uds.dev/v1alpha1"}]},
                    "data": {"ca-bundle.pem": pem("temporary")}}
        kube = live.Kubectl()
        failure = subprocess.CalledProcessError(1, ["kubectl", "patch"], stderr="resourceVersion test failed")
        with patch.object(kube, "run", side_effect=[json.dumps(resource), failure]):
            with self.assertRaises(subprocess.CalledProcessError):
                kube.prune_trial_roots("takserver", live.fingerprints(pem("temporary")))

    def test_node_error_survives_kubectl_exit_trailer_without_printing_material(self):
        result = SimpleNamespace(returncode=1, stdout="", stderr='UDS_SSO_TRUST_ERROR '+json.dumps({"code": "UNABLE_TO_GET_ISSUER_CERT", "message": "issuer missing\n-----BEGIN CERTIFICATE-----secret material"})+'\ncommand terminated with exit code 1\n')
        with patch.object(live.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "UNABLE_TO_GET_ISSUER_CERT: issuer missing") as caught:
                live.Kubectl().exec_sso("unused")
        self.assertNotIn("command terminated", str(caught.exception))
        self.assertNotIn("secret material", str(caught.exception))

    def test_append_preserves_existing_custom_roots(self):
        original = base64.b64encode(pem("old").encode()).decode()
        combined = base64.b64decode(live.append_ca(original, pem("new"))).decode()
        self.assertEqual(live.fingerprints(combined), live.fingerprints(pem("old") + pem("new")))
        self.assertEqual(live.fingerprints(base64.b64decode(live.append_ca(live.MISSING, pem("new"))).decode()),
                         live.fingerprints(pem("new")))

    def test_rotation_and_restoration_preserve_flags_and_other_config(self):
        kube = FakeKubectl()
        before = copy.deepcopy(kube.current["spec"])
        trial = live.Trial(kube, "example.com")
        first = trial.phase(pem("first"))
        trial.phase(pem("second"), first)
        trial.restore()
        self.assertEqual(kube.current["spec"], before)
        self.assertEqual(len(trial.evidence), 2)
        self.assertEqual(len(kube.discovery_checks), 2)
        for operations in kube.operations:
            self.assertEqual(operations[0]["path"], "/metadata/resourceVersion")
            self.assertTrue(all(op["path"] in ("/metadata/resourceVersion", "/spec/caBundle/certs") for op in operations))

    def test_concurrent_flag_changes_preserve_new_roots_and_reach_cleanup_restarts(self):
        for flag, value in (("includeDoDCerts", True), ("includePublicCerts", False)):
            with self.subTest(flag=flag):
                kube = FakeKubectl()
                trial = live.Trial(kube, "uds.dev")
                temporary = trial.phase(pem("temporary"))
                kube.current["spec"]["caBundle"][flag] = value
                # This fake now includes/removes public/DoD roots according to
                # the flags, so the whole restored bundle differs from baseline.
                with patch.object(live, "wait_for", side_effect=lambda check, *_args: check()):
                    trial.restore()
                self.assertEqual(kube.current["spec"]["caBundle"][flag], value)
                self.assertEqual(live.certs_value(kube.current), kube.saved)
                restored = live.fingerprints(kube.bundle("cloudtak"))
                self.assertNotIn(temporary, restored)
                self.assertTrue(live.fingerprints(pem("original")) <= restored)
                if flag == "includeDoDCerts":
                    self.assertTrue(live.fingerprints(pem("dod-root")) <= restored)
                else:
                    self.assertFalse(live.fingerprints(pem("public-root")) & restored)
                self.assertEqual(len(kube.restart_calls), len(live.WORKLOADS))

    def test_unchanged_flags_still_require_the_original_entire_bundle(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        bundle = kube.bundle
        with patch.object(kube, "bundle", side_effect=lambda namespace: bundle(namespace) + pem("unexpected-root")), \
                patch.object(live, "wait_for", side_effect=lambda check, *_args: check()):
            with self.assertRaisesRegex(ValueError, "original CA bundles"):
                trial.restore()
        self.assertEqual(kube.restart_calls, [])

    def test_concurrent_flags_do_not_allow_a_trial_root_to_survive_cleanup(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        kube.current["spec"]["caBundle"]["includeDoDCerts"] = True
        bundle = kube.bundle
        with patch.object(kube, "bundle", side_effect=lambda namespace: bundle(namespace) + pem("temporary")), \
                patch.object(live, "wait_for", side_effect=lambda check, *_args: check()):
            with self.assertRaisesRegex(ValueError, "removed trial roots"):
                trial.restore()
        self.assertEqual(kube.restart_calls, [])

    def test_missing_original_certs_are_removed_again(self):
        kube = FakeKubectl(existing=False)
        before = copy.deepcopy(kube.current["spec"])
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        trial.restore()
        self.assertEqual(kube.current["spec"], before)

    def test_missing_original_bundle_object_is_removed_again(self):
        kube = FakeKubectl(existing=False)
        del kube.current["spec"]["caBundle"]
        before = copy.deepcopy(kube.current["spec"])
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        trial.restore()
        self.assertEqual(kube.current["spec"], before)

    def test_unchanged_pod_uids_do_not_count_as_a_reload(self):
        trial = live.Trial(FakeKubectl(), "uds.dev")
        with self.assertRaisesRegex(ValueError, "pre-rotation"):
            trial.replaced_pods(trial.kube.pods())

    def test_failure_after_a_successful_patch_still_restores(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        kube.fail_after_patch = True
        with self.assertRaises(TimeoutError):
            try:
                trial.phase(pem("temporary"))
            finally:
                trial.restore()
        self.assertEqual(live.certs_value(kube.current), kube.saved)

    def test_sso_failure_still_restores(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        kube.fail_discovery = True
        with self.assertRaisesRegex(RuntimeError, "SSO failed"):
            try:
                trial.phase(pem("temporary"))
            finally:
                trial.restore()
        self.assertEqual(live.certs_value(kube.current), kube.saved)

    def test_concurrent_custom_ca_edit_is_never_overwritten(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev")
        trial.phase(pem("temporary"))
        other = base64.b64encode(pem("other-admin").encode()).decode()
        kube.current["spec"]["caBundle"]["certs"] = other
        with self.assertRaisesRegex(ValueError, "concurrently"):
            trial.restore()
        self.assertEqual(live.certs_value(kube.current), other)

    def test_ui_is_required_when_requested(self):
        kube = FakeKubectl()
        trial = live.Trial(kube, "uds.dev", ui=True)
        with patch.object(live.subprocess, "run") as run:
            trial.phase(pem("temporary"))
        self.assertEqual(run.call_args.args[0], ["uds", "run", "test:ui", "--no-progress"])
        self.assertEqual(run.call_args.kwargs["env"]["REQUIRE_SSO_SETUP"], "true")


@unittest.skipUnless(shutil.which("node") and shutil.which("openssl"), "Node/OpenSSL are required")
class SsoDiscoveryTLS(unittest.TestCase):
    def test_real_intermediate_chain_uses_its_root_and_rejects_unrelated_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def openssl(*args):
                subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=30)

            for name in ("root", "trial"):
                openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=" + name,
                        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                        "-keyout", root / (name + ".key"), "-out", root / (name + ".pem"))
            for name in ("intermediate", "leaf"):
                openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=" + name,
                        "-keyout", root / (name + ".key"), "-out", root / (name + ".csr"))
            (root / "intermediate.ext").write_text("basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n")
            openssl("x509", "-req", "-in", root / "intermediate.csr", "-CA", root / "root.pem", "-CAkey", root / "root.key",
                    "-CAcreateserial", "-days", "1", "-extfile", root / "intermediate.ext", "-out", root / "intermediate.pem")
            (root / "leaf.ext").write_text("basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:localhost\nextendedKeyUsage=serverAuth\n")
            openssl("x509", "-req", "-in", root / "leaf.csr", "-CA", root / "intermediate.pem", "-CAkey", root / "intermediate.key",
                    "-CAcreateserial", "-days", "1", "-extfile", root / "leaf.ext", "-out", root / "leaf.pem")
            server_chain = root / "server.pem"
            # A normal gateway sends its intermediate, not the trusted root.
            server_chain.write_text((root / "leaf.pem").read_text() + (root / "intermediate.pem").read_text())
            combined = root / "combined.pem"
            combined.write_text((root / "intermediate.pem").read_text() + (root / "root.pem").read_text() + (root / "trial.pem").read_text())

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({"issuer": realm}).encode())

                def log_message(self, *_args):
                    pass

            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(server_chain, root / "leaf.key")
            server.socket = context.wrap_socket(server.socket, server_side=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            realm = f"https://localhost:{server.server_port}/realms/uds"
            kube = live.Kubectl()
            real_exec = kube.exec_sso

            def fixture_exec(code, *args):
                # Route only filesystem/transport to this isolated fixture;
                # execute the actual TLS, CA selection and negative controls.
                code = code.replace("new URL(realm).host", "new URL(realm).hostname").replace("port:443", "port:" + str(server.server_port))
                prefix = "const fixtureRead=require('node:fs').readFileSync;require('node:fs').readFileSync=(p,...a)=>fixtureRead(p==='/var/run/combined-trust/ca-bundle.pem'?" + json.dumps(str(combined)) + ":p,...a);\n"
                values = [realm, args[1]] if len(args) == 2 else ["localhost"]
                result = subprocess.run(["node", "-e", prefix + code, *values], text=True, capture_output=True, timeout=30,
                                        env={**os.environ, "NODE_EXTRA_CA_CERTS": "/var/run/combined-trust/ca-bundle.pem"})
                if result.returncode:
                    result.stderr += "\ncommand terminated with exit code 1\n"
                with patch.object(live.subprocess, "run", return_value=result):
                    return real_exec(code, *args)

            try:
                kube.exec_sso = fixture_exec
                root_fp = next(iter(live.fingerprints((root / "root.pem").read_text())))
                self.assertEqual(kube.signing_status("fixture"), "IN_BUNDLE " + root_fp)
                trial_fp = next(iter(live.fingerprints((root / "trial.pem").read_text())))
                output = kube.discovery("fixture", trial_fp)
                self.assertIn("signer=" + root_fp, output)
                self.assertIn("trial_ca_rejected=true", output)
                # Omitting the root must still fail; do not silently accept
                # an intermediate via allowPartialTrustChain or disabled TLS.
                combined.write_text((root / "intermediate.pem").read_text() + (root / "trial.pem").read_text())
                with self.assertRaisesRegex(RuntimeError, "UNABLE_TO_GET_ISSUER_CERT"):
                    kube.discovery("fixture", trial_fp)
                with self.assertRaisesRegex(RuntimeError, "SSO root CA is unavailable"):
                    kube.signing_status("fixture")
                # If the gateway sends its complete chain, bootstrap must add
                # the self-signed root, not its non-root intermediate.
                server_chain.write_text(server_chain.read_text() + (root / "root.pem").read_text())
                context.load_cert_chain(server_chain, root / "leaf.key")
                combined.write_text((root / "trial.pem").read_text())
                status = kube.signing_status("fixture")
                self.assertTrue(status.startswith("NEED_CA "), "missing root was not identified")
                self.assertEqual(live.fingerprints(base64.b64decode(status.split(" ", 1)[1]).decode()), {root_fp})
            finally:
                server.shutdown()
                server.server_close()


class GatewayFixtureTests(unittest.TestCase):
    def test_ephemeral_guard_rejects_other_clusters_and_domains(self):
        with self.assertRaisesRegex(RuntimeError, "ephemeral uds.dev k3d"):
            live.require_ephemeral_k3d("k3d-uds", ["k3d-uds-server-0"], "example.com")
        with self.assertRaisesRegex(RuntimeError, "ephemeral uds.dev k3d"):
            live.require_ephemeral_k3d("prod", ["k3d-uds-server-0"], "uds.dev")
        with self.assertRaisesRegex(RuntimeError, "ephemeral uds.dev k3d"):
            live.require_ephemeral_k3d("k3d-uds", ["ip-10-0-0-1"], "uds.dev")
        live.require_ephemeral_k3d("k3d-uds", ["k3d-uds-server-0"], "uds.dev")

    def test_unexpected_gateway_secret_is_refused(self):
        kube = live.Kubectl()
        secret = {"metadata": {"name": "gateway-tls", "namespace": "istio-tenant-gateway"}, "type": "Opaque", "data": {}}
        with patch.object(kube, "run", return_value=json.dumps(secret)) as run:
            with self.assertRaisesRegex(RuntimeError, "unexpected tenant gateway"):
                kube.gateway_secret()
        self.assertEqual(run.call_args.args[:4], ("get", "secret", "gateway-tls", "-n"))

    def test_install_replaces_only_the_gateway_keypair_and_restore_refuses_a_concurrent_edit(self):
        class Fake:
            def __init__(self):
                self.secret = {"metadata": {"name": "gateway-tls", "namespace": "istio-tenant-gateway",
                                            "uid": "uid-1", "resourceVersion": "9"},
                               "type": "kubernetes.io/tls",
                               "data": {"tls.crt": base64.b64encode(b"original-cert").decode(),
                                        "tls.key": base64.b64encode(b"original-key").decode(),
                                        "cacert": base64.b64encode(b"leave-me").decode()}}
                self.patches = []

            def current_context(self):
                return "k3d-uds"

            def node_names(self):
                return ["k3d-uds-server-0"]

            def gateway_secret(self):
                return copy.deepcopy(self.secret)

            def patch_gateway(self, operations):
                self.patches.append(json.loads(json.dumps(operations)))
                for operation in operations:
                    if operation["op"] == "test" and operation["path"] == "/metadata/resourceVersion":
                        self.assert_version(operation["value"])
                    elif operation["op"] == "replace":
                        self.secret["data"][operation["path"].rsplit("/", 1)[-1]] = operation["value"]
                self.secret["metadata"]["resourceVersion"] = str(int(self.secret["metadata"]["resourceVersion"]) + 1)

            def assert_version(self, value):
                if value != self.secret["metadata"]["resourceVersion"]:
                    raise AssertionError("resourceVersion was not tested against the current secret")

            def presented_issuer(self, _domain):
                chain = base64.b64decode(self.secret["data"]["tls.crt"]).decode()
                certs = live.re.findall(r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", chain)
                return next(iter(live.fingerprints(certs[-1])))

        kube = Fake()
        fixture = live.GatewayFixture(kube, "uds.dev")
        with tempfile.TemporaryDirectory() as directory:
            fingerprint = fixture.install(directory)
            self.assertEqual(kube.secret["data"]["cacert"], base64.b64encode(b"leave-me").decode())
            self.assertEqual([operation["path"] for operation in kube.patches[0]],
                             ["/metadata/uid", "/metadata/resourceVersion", "/data/tls.crt", "/data/tls.key"])
            kube.secret["data"]["tls.crt"] = base64.b64encode(b"someone-else").decode()
            with self.assertRaisesRegex(RuntimeError, "changed concurrently"):
                fixture.restore()
            self.assertEqual(len(kube.patches), 1)
            kube.secret["data"]["tls.crt"] = fixture.applied["tls.crt"]
            fixture.restore()
        self.assertEqual(base64.b64decode(kube.secret["data"]["tls.crt"]), b"original-cert")
        self.assertEqual(base64.b64decode(kube.secret["data"]["tls.key"]), b"original-key")
        self.assertEqual(fingerprint, next(iter(live.fingerprints(fixture.ca_pem))))
        self.assertIsNone(fixture.applied)

    def test_issued_gateway_leaf_fails_public_roots_and_verifies_with_its_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            ca_pem, chain, key = live.issue_gateway_certificate(directory, "uds.dev")
            (directory / "full.pem").write_text(chain)
            (directory / "gateway.key").write_text(key)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(directory / "full.pem", directory / "gateway.key")
            server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            probe = directory / "probe.mjs"
            probe.write_text(
                "import tls from 'node:tls';\nimport fs from 'node:fs';\n"
                "const port=Number(process.argv[2]);const ca=fs.readFileSync(process.argv[3]);\n"
                "function connect(trust){return new Promise(resolve=>{const socket=tls.connect({host:'127.0.0.1',port,servername:'sso.uds.dev',ca:trust,rejectUnauthorized:true,timeout:3000},()=>{socket.end();resolve('success')});socket.on('timeout',()=>{socket.destroy();resolve('fail:timeout')});socket.on('error',error=>resolve('fail:'+(error.code||error.message)))})}\n"
                "const pub=await connect(tls.rootCertificates);const priv=await connect([ca]);\n"
                "console.log(JSON.stringify({pub,priv}));\n")
            try:
                result = subprocess.run(["node", str(probe), str(server.server_port), str(directory / "gateway-ca.pem")],
                                        text=True, capture_output=True, timeout=20, check=True)
            finally:
                server.shutdown()
                server.server_close()
        outcomes = json.loads(result.stdout)
        self.assertTrue(outcomes["pub"].startswith("fail:"), outcomes)
        self.assertEqual(outcomes["priv"], "success")
        self.assertNotIn("PRIVATE KEY", ca_pem)


if __name__ == "__main__":
    unittest.main()
