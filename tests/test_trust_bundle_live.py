# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""CA trial keeps existing trust settings and safely restores after failures."""

import base64
import copy
import importlib.util
from pathlib import Path
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
        self.current = {"metadata": {"resourceVersion": "1"}, "spec": {"caBundle": bundle, "policy": {"unchanged": True}}}
        self.generation = 0
        self.operations = []
        self.fail_after_patch = False
        self.fail_discovery = False
        self.discovery_checks = []
        self.restart_calls = []

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
        if self.fail_after_patch:
            self.fail_after_patch = False
            raise TimeoutError("response timed out after API accepted patch")

    def bundle(self, _namespace):
        value = live.certs_value(self.current)
        content = "" if value is live.MISSING else base64.b64decode(value).decode()
        flags = self.current.get("spec", {}).get("caBundle", {})
        if flags.get("includePublicCerts"):
            content += pem("public-root")
        if flags.get("includeDoDCerts"):
            content += pem("dod-root")
        return content

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


if __name__ == "__main__":
    unittest.main()
