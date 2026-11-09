#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise Core CA propagation and automatic consumer reloads on a test cluster.

Appends temporary roots to the saved custom bundle and proves the live SSO
certificate is accepted only by its signing CA from the combined trust file.
Public roots and the unrelated trial CA must reject it. A signing CA missing
from the bundle is installed, then the consumers reload. test_trust_bundle.py
separately tests private-CA TLS with local servers.
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


def without_trial_roots(content, trial_roots):
    """Remove only exact certificate fingerprints introduced by this trial."""
    def keep(match):
        return "" if fingerprints(match.group()) & trial_roots else match.group()

    return re.sub(r"-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----", keep, content)


def sso_failure(result):
    """Read our bounded Node diagnostic, never kubectl's trailing exit line."""
    for line in (result.stderr or "").splitlines():
        if not line.startswith("UDS_SSO_TRUST_ERROR "):
            continue
        try:
            error = json.loads(line.split(" ", 1)[1])
        except (ValueError, TypeError):
            continue
        if not isinstance(error, dict):
            continue
        message = str(error.get("message", "Node trust check failed"))
        # A crypto library must not cause certificate/key material to be logged.
        message = message.split("-----BEGIN", 1)[0]
        message = " ".join("".join(ch for ch in message if ch.isprintable()).split())[:240]
        code = str(error.get("code", ""))
        code = code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code) else ""
        return (message if not code or message.startswith(code) else f"{code}: {message}")[:300]
    for line in (result.stderr or "").splitlines():
        if re.match(r"^(?:Error|[A-Za-z]+Error):", line):
            return " ".join(line.split("-----BEGIN", 1)[0].split())[:300]
    return f"Node trust check exited {result.returncode} without a structured diagnostic"


def append_ca(original, certificate):
    saved = "" if original is MISSING else base64.b64decode(original, validate=True).decode()
    return base64.b64encode((saved.rstrip() + "\n" + certificate.strip() + "\n").encode()).decode()


def automatic_reload_expected(bundle_already_present):
    """Core records the first observation of a ConfigMap and does not restart pods.

    A later change to that ConfigMap's data reloads pods selected by
    uds.dev/pod-reload-selector. Creating the namespace bundle is propagation
    only; the following rotation is the reload.
    """
    return bundle_already_present


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

    def configured_roots(self, config):
        """Roots legitimately enabled now, including concurrent public/DoD flags."""
        value = certs_value(config)
        roots = fingerprints("" if value is MISSING else base64.b64decode(value, validate=True).decode())
        flags = config.get("spec", {}).get("caBundle", {})
        if not (flags.get("includePublicCerts") or flags.get("includeDoDCerts")):
            return roots
        source = json.loads(self.run("get", "configmap", "uds-ca-certs", "-n", "pepr-system", "-o", "json"))
        for flag, key in (("includePublicCerts", "publicCACerts"), ("includeDoDCerts", "dodCACerts")):
            if flags.get(flag):
                roots |= fingerprints(base64.b64decode(source.get("data", {}).get(key, ""), validate=True).decode())
        return roots

    def prune_trial_roots(self, namespace, trial_roots):
        """CAS-prune only our roots; retain the object, owners and all other data."""
        resource = json.loads(self.run("get", "configmap", "uds-trust-bundle", "-n", namespace, "-o", "json"))
        metadata = resource.get("metadata", {})
        labels = metadata.get("labels", {})
        owners = metadata.get("ownerReferences", [])
        if namespace not in {"takserver", "cloudtak"} or metadata.get("name") != "uds-trust-bundle" \
                or metadata.get("namespace") != namespace or labels.get("uds/ca-bundle") != "true" \
                or labels.get("uds/package") != namespace \
                or not any(owner.get("kind") == "Package" and owner.get("name") == namespace
                           and owner.get("apiVersion", "").startswith("uds.dev/") for owner in owners):
            raise ValueError(f"refusing cleanup of a bundle not owned by Core's {namespace} Package")
        content = resource.get("data", {}).get("ca-bundle.pem", "")
        updated = without_trial_roots(content, trial_roots)
        if updated == content:
            return
        operations = [
            {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
            {"op": "test", "path": "/data/ca-bundle.pem", "value": content},
            {"op": "replace", "path": "/data/ca-bundle.pem", "value": updated},
        ]
        self.run("patch", "configmap", "uds-trust-bundle", "-n", namespace, "--type=json", "-p", json.dumps(operations))
        print(f"CAS-pruned trial-owned CA roots from {namespace}; all other roots and metadata preserved", flush=True)

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

    def exec_sso(self, code, *args):
        result = subprocess.run(
            ["uds", "zarf", "tools", "kubectl", "exec", "-n", "cloudtak", "deploy/cloudtak",
             "-c", "sso", "--", "node", "-e", code, *args],
            text=True, capture_output=True, timeout=60)
        if result.returncode == 0:
            return result.stdout.strip()
        raise RuntimeError(f"CloudTAK SSO trust check failed: {sso_failure(result)}")

    def signing_status(self, domain):
        # The inspection handshake records the peer certificate only. Acceptance
        # uses a separate connection that requires the bundled signing CA.
        classifier = Path(__file__).with_name("sso-trust-class.mjs").read_text().replace("export function", "function")
        code = classifier + r"""const tls=require('node:tls');const crypto=require('node:crypto');const fs=require('node:fs');
const host=process.argv[1];
function pems(text){return text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g)||[]}
function fp(cert){return cert.fingerprint256.replaceAll(':','').toLowerCase()}
(async()=>{
  const peer=await new Promise((resolve,reject)=>{const socket=tls.connect({host,port:443,servername:host,rejectUnauthorized:false,timeout:20000},()=>{const cert=socket.getPeerCertificate(true);socket.end();resolve(cert)});socket.on('error',reject)});
  if(!peer||!peer.raw) throw new Error('SSO server sent no certificate');
  const leaf=new crypto.X509Certificate(peer.raw);
  const bundled=pems(fs.readFileSync('/var/run/combined-trust/ca-bundle.pem','utf8')).map(pem=>new crypto.X509Certificate(pem));
  const signer=bundledAnchor(peer,bundled,raw=>new crypto.X509Certificate(raw));
  if(signer&&signer.checkIssued(signer)&&signer.verify(signer.publicKey)){console.log('IN_BUNDLE '+fp(signer));return}
  const chain=certificateChain(peer,raw=>new crypto.X509Certificate(raw),bundled);
  const root=chain.at(-1);
  if(!root||!root.ca||!root.checkIssued(root)||!root.verify(root.publicKey)) throw new Error('SSO root CA is unavailable: configure its private root before this trial; peer='+fp(leaf));
  console.log('NEED_CA '+Buffer.from(root.toString()).toString('base64'));
})().catch(error=>{console.error('UDS_SSO_TRUST_ERROR '+JSON.stringify({code:String(error&&error.code||''),message:String(error&&error.message||error).replace(/\s+/g,' ').slice(0,240)}));process.exitCode=1});"""
        return self.exec_sso(code, f"sso.{domain}")

    def discovery(self, domain, fingerprint):
        classifier = Path(__file__).with_name("sso-trust-class.mjs").read_text().replace("export function", "function")
        code = classifier + r"""
const tls=require('node:tls');const https=require('node:https');const fs=require('node:fs');const crypto=require('node:crypto');
const realm=process.argv[1];const host=new URL(realm).host;const trial=process.argv[2];
const path='/var/run/combined-trust/ca-bundle.pem';
function pems(text){return text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g)||[]}
function fp(cert){return cert.fingerprint256.replaceAll(':','').toLowerCase()}
function connect(ca){return new Promise((resolve,reject)=>{const socket=tls.connect({host,port:443,servername:host,ca,rejectUnauthorized:true,timeout:20000},()=>{const peer=socket.getPeerCertificate(true);socket.end();if(!peer||!peer.raw) reject(new Error('SSO server sent no certificate')); else resolve(peer)});socket.on('timeout',()=>{const error=new Error('TLS connection timed out');error.code='ETIMEDOUT';socket.destroy();reject(error)});socket.on('error',reject)})}
async function outcome(ca){try{await connect(ca);return {kind:'success',detail:''}}catch(error){return {kind:classifyTlsError(error),detail:boundedDiagnostic(error)}}}
(async()=>{
if(process.env.NODE_TLS_REJECT_UNAUTHORIZED==='0') throw new Error('TLS validation is disabled');
if(process.env.NODE_EXTRA_CA_CERTS!==path) throw new Error('combined trust file is not configured');
  const parsed=pems(fs.readFileSync(path,'utf8')).map(pem=>new crypto.X509Certificate(pem));
  const trialCert=parsed.find(cert=>fp(cert)===trial);
  if(!trialCert) throw new Error('trial CA is missing from the combined trust file');
  const publicOutcome=await outcome(tls.rootCertificates);
  if(publicOutcome.kind==='success') throw new Error('SSO certificate is trusted by public roots without the bundled CA');
  const publicDecision=negativeControl(publicOutcome,'public-root check');
  if(!publicDecision.pass) throw new Error(publicDecision.reason);
  const peer=await connect(parsed.map(cert=>cert.toString()));
  const leaf=new crypto.X509Certificate(peer.raw);
  const signer=bundledAnchor(peer,parsed,raw=>new crypto.X509Certificate(raw));
  if(!signer) throw new Error('SSO signing CA is not in the combined trust file: peer='+fp(leaf));
  await connect([signer.toString()]);
  const body=await new Promise((resolve,reject)=>{const req=https.get(realm+'/.well-known/openid-configuration',{ca:[signer.toString()],servername:host,rejectUnauthorized:true,timeout:20000},res=>{const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,text:Buffer.concat(chunks).toString('utf8')}))});req.on('error',reject);req.on('timeout',()=>{req.destroy();const error=new Error('TLS connection timed out');error.code='ETIMEDOUT';reject(error)})});
  const document=JSON.parse(body.text);
  if(body.status!==200||document.issuer!==realm) throw new Error('Keycloak discovery failed: HTTP '+body.status);
  const trialDecision=negativeControl(await outcome([trialCert.toString()]),'trial-CA check');
  if(!trialDecision.pass) throw new Error(trialDecision.reason);
  console.log('CloudTAK SSO verified peer='+fp(leaf)+' signer='+fp(signer)+' trial_ca_rejected=true');
})().catch(error=>{console.error('UDS_SSO_TRUST_ERROR '+JSON.stringify({code:String(error&&error.code||''),message:boundedDiagnostic(error)}));process.exitCode=1});"""
        return self.exec_sso(code, f"https://sso.{domain}/realms/uds", fingerprint)


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
        self.signer_pem = None
        self.original_bundles = {ns: fingerprints(kube.bundle(ns)) for ns in ("takserver", "cloudtak")}
        self.evidence = []

    def desired_certs(self, certificate):
        base = self.saved
        if self.signer_pem:
            base = append_ca(base, self.signer_pem)
        return append_ca(base, certificate)

    def ensure_signing_ca(self):
        status = self.kube.signing_status(self.domain)
        if status.startswith("IN_BUNDLE "):
            print(f"SSO signing CA {status.split()[1]} is already in the combined trust file", flush=True)
            return
        if not status.startswith("NEED_CA "):
            raise RuntimeError(f"CloudTAK SSO trust check failed: {status[:300]}")
        pem_text = base64.b64decode(status.split(" ", 1)[1]).decode()
        if "PRIVATE KEY" in pem_text:
            raise RuntimeError("refusing a private key from the gateway handshake")
        self.signer_pem = pem_text
        fingerprint = next(iter(fingerprints(pem_text)))
        present = {namespace for namespace in ("takserver", "cloudtak")
                   if automatic_reload_expected(bool(self.kube.bundle(namespace)))}
        # Core's first-observation rule applies separately to each namespace.
        # An existing TAK bundle must not imply a first CloudTAK bundle reload.
        before = {name: uids for name, uids in self.kube.pods().items()
                  if name.split("/", 1)[0] in present}
        self.set_certs(append_ca(self.saved, pem_text))
        wait_for(lambda: self.bundles_match(fingerprint), "signing CA propagation", 180)
        if before:
            wait_for(lambda: self.replaced_pods(before), "reload after updating the existing SSO signing CA bundle")
            print(f"updated SSO signing CA {fingerprint} and reloaded {', '.join(sorted(before))}", flush=True)
        else:
            print(f"installed SSO signing CA {fingerprint}; namespace bundle was created and Core does not reload on first observation", flush=True)

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
        stuck = [name for name in before if before[name] & after[name]]
        if stuck:
            raise ValueError(f"{', '.join(stuck)} still has its pre-rotation pod UID")
        return after

    def phase(self, certificate, excluded=None):
        fingerprint = next(iter(fingerprints(certificate)))
        before = self.kube.pods()
        self.set_certs(self.desired_certs(certificate))
        wait_for(lambda: self.bundles_match(fingerprint, excluded), "CA ConfigMap propagation", 180)
        after = wait_for(lambda: self.replaced_pods(before), "automatic consumer rollouts")
        sso = wait_for(lambda: self.kube.discovery(self.domain, fingerprint), "CloudTAK SSO discovery", 180)
        print(sso, flush=True)
        if self.ui:
            subprocess.run(["uds", "run", "test:ui", "--no-progress"], check=True, timeout=900,
                           env={**os.environ, "REQUIRE_SSO_SETUP": "true"})
        self.evidence.append({"ca_sha256": fingerprint, "pods_before": {k: sorted(v) for k, v in before.items()},
                              "pods_after": {k: sorted(v) for k, v in after.items()}, "sso_ui": self.ui,
                              "sso": sso[:300]})
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

        def restored_bundles(allow_prune=True):
            latest = self.kube.config()
            if certs_value(latest) != self.saved:
                raise ValueError("custom CA certs changed again during cleanup")
            if latest.get("status", {}).get("phase") == "Failed":
                raise RuntimeError("Core failed to reconcile restored custom CA settings")
            generation = latest.get("metadata", {}).get("generation")
            if generation is None or latest.get("status", {}).get("phase") != "Ready" \
                    or latest.get("status", {}).get("observedGeneration") != generation:
                raise ValueError("Core has not reconciled the restored CA generation")
            flags_changed = non_custom_settings(latest) != non_custom_settings(self.original)
            # Core can leave the last namespace bundle after clearing all roots.
            # Remove only roots we introduced, excluding roots now legitimately
            # enabled by concurrent flags. Never delete the ConfigMap or unknown CAs.
            unwanted = trial_only - self.kube.configured_roots(latest)
            for namespace, saved in self.original_bundles.items():
                found = fingerprints(self.kube.bundle(namespace))
                if allow_prune and unwanted & found:
                    self.kube.prune_trial_roots(namespace, unwanted)
                    found = fingerprints(self.kube.bundle(namespace))
                if flags_changed:
                    # An administrator may have legitimately added or removed
                    # public/DoD roots. Preserve those flags and roots, but still
                    # require our saved custom roots and removal of trial roots.
                    if not saved_custom <= found or unwanted & found:
                        raise ValueError(f"{namespace} has not restored custom trust and removed trial roots")
                elif found != saved:
                    state = "absent" if not found else f"{len(found)} certificate(s) still present"
                    added = ",".join(sorted(found - saved)[:3]) or "none"
                    removed = ",".join(sorted(saved - found)[:3]) or "none"
                    raise ValueError(
                        f"original CA bundles have not returned: {namespace} is {state}; "
                        f"extra fingerprints={added}; missing fingerprints={removed}")

        wait_for(restored_bundles, "restore namespace trust without replacing concurrent CA settings", 180)
        # Restart explicitly after restoring/pruning roots: init containers
        # and Node processes must not retain a cached temporary certificate.
        before = wait_for(self.kube.pods, "consumers ready before cleanup restart")
        for namespace, name in WORKLOADS:
            self.kube.run("rollout", "restart", f"deploy/{name}", "-n", namespace)
        wait_for(lambda: self.replaced_pods(before), "cleanup consumer rollouts")
        # A controller reintroducing a temporary root is a failure, not another
        # opportunity to prune it after consumers have already restarted.
        restored_bundles(allow_prune=False)
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
            trial.ensure_signing_ca()
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
