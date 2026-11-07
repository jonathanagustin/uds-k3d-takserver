#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise Core CA propagation and automatic consumer reloads on a test cluster.

Only appends temporary public roots to the existing custom bundle. The actual
Keycloak gateway certificate is not changed; this checks propagation, reloads,
and live SSO discovery. test_trust_bundle.py separately tests private-CA TLS.
"""

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import ssl
import subprocess
import tempfile
import time

WORKLOADS = (("takserver", "takserver-api"), ("takserver", "takserver-messaging"), ("cloudtak", "cloudtak"))
MISSING = object()


def fingerprints(pem):
    return {hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest() for cert in
            re.findall(r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", pem)}


def append_ca(original, certificate):
    saved = "" if original is MISSING else base64.b64decode(original, validate=True).decode()
    return base64.b64encode((saved.rstrip() + "\n" + certificate.strip() + "\n").encode()).decode()


def wait_for(check, description, seconds=600):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            return check()
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            last = error
            time.sleep(5)
    raise RuntimeError(f"{description}: {last}")


class Kubectl:
    def run(self, *args, payload=None):
        return subprocess.run(["uds", "zarf", "tools", "kubectl", *args],
                              input=payload, text=True, capture_output=True, check=True, timeout=45).stdout

    def config(self):
        return json.loads(self.run("get", "clusterconfig", "uds-cluster-config", "-o", "json"))

    def patch(self, operations):
        self.run("patch", "clusterconfig", "uds-cluster-config", "--type=json", "-p", json.dumps(operations))

    def bundle(self, namespace):
        text = self.run("get", "configmap", "uds-trust-bundle", "-n", namespace,
                        "--ignore-not-found", "-o", "json")
        return json.loads(text).get("data", {}).get("ca-bundle.pem", "") if text.strip() else ""

    def pods(self):
        result = {}
        for namespace, name in WORKLOADS:
            items = json.loads(self.run("get", "pods", "-n", namespace, "-l", f"app={name}", "-o", "json"))["items"]
            items = [pod for pod in items if not pod["metadata"].get("deletionTimestamp")]
            if not items or any(not any(c.get("type") == "Ready" and c.get("status") == "True"
                                        for c in pod.get("status", {}).get("conditions", [])) for pod in items):
                raise ValueError(f"{namespace}/{name} has no ready replacement pod")
            result[f"{namespace}/{name}"] = {pod["metadata"]["uid"] for pod in items}
        return result

    def discovery(self, domain, fingerprint):
        code = r"""const fs = require('node:fs'); const { X509Certificate } = require('node:crypto');
(async () => {
  if (process.env.NODE_TLS_REJECT_UNAUTHORIZED === '0') throw Error('TLS validation is disabled');
  const path = '/var/run/combined-trust/ca-bundle.pem';
  if (process.env.NODE_EXTRA_CA_CERTS !== path) throw Error('combined trust file is not configured');
  const certificates = fs.readFileSync(path, 'utf8').match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) || [];
  const hashes = certificates.map(pem => new X509Certificate(pem).fingerprint256.replaceAll(':', '').toLowerCase());
  if (!hashes.includes(process.argv[2])) throw Error('test CA is missing from the process trust file');
  const response = await fetch(process.argv[1] + '/.well-known/openid-configuration', { signal: AbortSignal.timeout(20000) });
  if (!response.ok || (await response.json()).issuer !== process.argv[1]) throw Error('Keycloak discovery failed');
  console.log('CloudTAK SSO Node discovery verified with the combined trust file');
})().catch(() => { console.error('CloudTAK SSO trust/discovery check failed'); process.exitCode = 1; });"""
        return self.run("exec", "-n", "cloudtak", "deploy/cloudtak", "-c", "sso", "--", "node", "-e", code,
                        f"https://sso.{domain}/realms/uds", fingerprint).strip()


def certs_value(config):
    return config.get("spec", {}).get("caBundle", {}).get("certs", MISSING)


def replacement_patch(current, expected, desired):
    """Change only custom certs, with a lease; never replace other CA settings."""
    actual = certs_value(current)
    if actual != expected:
        raise ValueError("custom CA certs changed concurrently; refusing to overwrite them")
    operations = [{"op": "test", "path": "/metadata/resourceVersion", "value": current["metadata"]["resourceVersion"]}]
    bundle = current.get("spec", {}).get("caBundle", MISSING)
    if desired is MISSING:
        if actual is not MISSING:
            operations.append({"op": "remove", "path": "/spec/caBundle/certs"})
    else:
        if bundle is MISSING:
            operations.append({"op": "add", "path": "/spec/caBundle", "value": {}})
        operations.append({"op": "add", "path": "/spec/caBundle/certs", "value": desired})
    return operations


class Trial:
    def __init__(self, kube, domain, ui=False):
        self.kube, self.domain, self.ui = kube, domain, ui
        self.original = copy.deepcopy(kube.config())
        self.saved = certs_value(self.original)
        self.issued = []
        self.original_bundles = {ns: fingerprints(kube.bundle(ns)) for ns in ("takserver", "cloudtak")}
        self.evidence = []

    def set_certs(self, desired):
        expected = self.issued[-1] if self.issued else self.saved
        operations = replacement_patch(self.kube.config(), expected, desired)
        # Track the attempted value before submitting: a timeout may happen
        # after the API accepted the patch, so cleanup must recognize it.
        self.issued.append(desired)
        self.kube.patch(operations)

    def bundles_match(self, expected, excluded=None):
        for namespace in ("takserver", "cloudtak"):
            found = fingerprints(self.kube.bundle(namespace))
            if expected not in found or (excluded and excluded in found):
                raise ValueError(f"{namespace} bundle has not propagated")

    def replaced_pods(self, before):
        after = self.kube.pods()
        if any(before[name] & after[name] for name in before):
            raise ValueError("a consumer still has its pre-rotation pod UID")
        return after

    def phase(self, certificate, excluded=None):
        fingerprint = next(iter(fingerprints(certificate)))
        before = self.kube.pods()
        self.set_certs(append_ca(self.saved, certificate))
        wait_for(lambda: self.bundles_match(fingerprint, excluded), "CA ConfigMap propagation", 180)
        after = wait_for(lambda: self.replaced_pods(before), "automatic consumer rollouts")
        print(wait_for(lambda: self.kube.discovery(self.domain, fingerprint), "CloudTAK SSO discovery", 180), flush=True)
        if self.ui:
            subprocess.run(["uds", "run", "test:ui", "--no-progress"], check=True, timeout=900,
                           env={**os.environ, "REQUIRE_SSO_SETUP": "true"})
        self.evidence.append({"ca_sha256": fingerprint, "pods_before": {k: sorted(v) for k, v in before.items()},
                              "pods_after": {k: sorted(v) for k, v in after.items()}, "sso_ui": self.ui})
        print(f"CA {fingerprint}: both namespace bundles and all three automatic rollouts verified", flush=True)
        return fingerprint

    def restore(self):
        if not self.issued:
            return
        current = self.kube.config()
        value = certs_value(current)
        if value != self.saved and value not in self.issued:
            raise ValueError("custom CA certs changed concurrently; cleanup cannot safely restore them")
        operations = replacement_patch(current, value, self.saved)
        # If this test created the entire caBundle object, remove only that
        # object when it still contains just our certs. Preserve concurrent flags.
        if "caBundle" not in self.original.get("spec", {}) and set(current["spec"].get("caBundle", {})) == {"certs"}:
            operations[-1] = {"op": "remove", "path": "/spec/caBundle"}
        self.kube.patch(operations)

        saved_custom = fingerprints("" if self.saved is MISSING else base64.b64decode(self.saved).decode())
        baseline = set().union(*self.original_bundles.values(), saved_custom)
        trial_only = set().union(*(fingerprints(base64.b64decode(value).decode()) for value in self.issued)) - baseline

        def non_custom_settings(config):
            return {key: value for key, value in config.get("spec", {}).get("caBundle", {}).items() if key != "certs"}

        def restored_bundles():
            latest = self.kube.config()
            if certs_value(latest) != self.saved:
                raise ValueError("custom CA certs changed again during cleanup")
            flags_changed = non_custom_settings(latest) != non_custom_settings(self.original)
            for namespace, saved in self.original_bundles.items():
                found = fingerprints(self.kube.bundle(namespace))
                if flags_changed:
                    # An administrator may have legitimately added or removed
                    # public/DoD roots. Preserve those flags and roots, but still
                    # require our saved custom roots and removal of trial roots.
                    if not saved_custom <= found or trial_only & found:
                        raise ValueError(f"{namespace} has not restored custom trust and removed trial roots")
                elif found != saved:
                    raise ValueError("original CA bundles have not returned")

        wait_for(restored_bundles, "restore namespace trust without replacing concurrent CA settings", 180)
        # Empty original bundles are deleted by Core. Restart explicitly in
        # cleanup so a cached temporary root cannot survive a ConfigMap deletion.
        before = wait_for(self.kube.pods, "consumers ready before cleanup restart")
        for namespace, name in WORKLOADS:
            self.kube.run("rollout", "restart", f"deploy/{name}", "-n", namespace)
        wait_for(lambda: self.replaced_pods(before), "cleanup consumer rollouts")
        print("Saved Core custom CA setting restored and temporary roots removed; consumers restarted", flush=True)


def generate_ca(directory, name):
    certificate = directory / f"{name}.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", f"/CN={name}", "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                    "-keyout", str(directory / f"{name}.key"), "-out", str(certificate)],
                   check=True, capture_output=True, timeout=30)
    return certificate.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", action="store_true", help="rerun existing test:ui suite after each CA change")
    args = parser.parse_args()
    # Give CI cancellation a chance to restore settings; SIGKILL cannot run cleanup.
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    trial = Trial(Kubectl(), os.environ.get("DOMAIN", "uds.dev"), args.ui)
    output = Path("out/trust-bundle-live.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    backup = {"caBundlePresent": "caBundle" in trial.original.get("spec", {}),
              "caBundle": trial.original.get("spec", {}).get("caBundle")}
    Path("out/trust-bundle-original-ca.json").write_text(json.dumps(backup, indent=2) + "\n")
    restored = False
    with tempfile.TemporaryDirectory(prefix="trust-bundle-live-") as directory:
        try:
            first = trial.phase(generate_ca(Path(directory), "uds-test-ca-a"))
            trial.phase(generate_ca(Path(directory), "uds-test-ca-b"), excluded=first)
        finally:
            try:
                trial.restore()
                restored = True
            finally:
                output.write_text(json.dumps({"phases": trial.evidence, "restored": restored}, indent=2) + "\n")


if __name__ == "__main__":
    main()
