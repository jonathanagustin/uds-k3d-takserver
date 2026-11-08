#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
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

    def exec_sso(self, code, *args):
        result = subprocess.run(
            ["uds", "zarf", "tools", "kubectl", "exec", "-n", "cloudtak", "deploy/cloudtak",
             "-c", "sso", "--", "node", "-e", code, *args],
            text=True, capture_output=True, timeout=60)
        if result.returncode == 0:
            return result.stdout.strip()
        detail = (result.stderr or result.stdout or "no error text").strip().splitlines()
        first = detail[-1][:300] if detail else "no error text"
        raise RuntimeError(f"CloudTAK SSO trust check failed: {first}")

    def signing_status(self, domain):
        # The inspection handshake records the peer certificate only. Acceptance
        # uses a separate connection that requires the bundled signing CA.
        code = r"""const tls=require('node:tls');const crypto=require('node:crypto');const fs=require('node:fs');
const host=process.argv[1];
function pems(text){return text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g)||[]}
function fp(cert){return cert.fingerprint256.replaceAll(':','').toLowerCase()}
function derPem(raw){const b64=raw.toString('base64');return '-----BEGIN CERTIFICATE-----\n'+b64.match(/.{1,64}/g).join('\n')+'\n-----END CERTIFICATE-----\n'}
(async()=>{
  const peer=await new Promise((resolve,reject)=>{const socket=tls.connect({host,port:443,servername:host,rejectUnauthorized:false,timeout:20000},()=>{const cert=socket.getPeerCertificate(true);socket.end();resolve(cert)});socket.on('error',reject)});
  if(!peer||!peer.raw) throw new Error('SSO server sent no certificate');
  const leaf=new crypto.X509Certificate(peer.raw);
  const bundled=pems(fs.readFileSync('/var/run/combined-trust/ca-bundle.pem','utf8')).map(pem=>new crypto.X509Certificate(pem));
  const signer=bundled.find(ca=>{try{return fp(ca)===fp(leaf)||leaf.verify(ca.publicKey)}catch{return false}});
  if(signer){console.log('IN_BUNDLE '+fp(signer));return}
  if(!peer.issuerCertificate||!peer.issuerCertificate.raw) throw new Error('SSO signing CA is not in the combined trust file and the server sent no issuer certificate: peer='+fp(leaf));
  const issuerPem=derPem(peer.issuerCertificate.raw);
  const issuer=new crypto.X509Certificate(issuerPem);
  if(!(fp(issuer)===fp(leaf)||leaf.verify(issuer.publicKey))) throw new Error('presented issuer did not sign the SSO certificate: peer='+fp(leaf));
  console.log('NEED_CA '+Buffer.from(issuerPem).toString('base64'));
})().catch(error=>{console.error(String(error&&error.message||error).replace(/\s+/g,' ').slice(0,300));process.exitCode=1});"""
        return self.exec_sso(code, f"sso.{domain}")

    def discovery(self, domain, fingerprint):
        code = r"""const tls=require('node:tls');const https=require('node:https');const fs=require('node:fs');const crypto=require('node:crypto');
const realm=process.argv[1];const host=new URL(realm).host;const trial=process.argv[2];
if(process.env.NODE_TLS_REJECT_UNAUTHORIZED==='0') throw new Error('TLS validation is disabled');
const path='/var/run/combined-trust/ca-bundle.pem';
if(process.env.NODE_EXTRA_CA_CERTS!==path) throw new Error('combined trust file is not configured');
function pems(text){return text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g)||[]}
function fp(cert){return cert.fingerprint256.replaceAll(':','').toLowerCase()}
function connect(ca){return new Promise((resolve,reject)=>{const socket=tls.connect({host,port:443,servername:host,ca,rejectUnauthorized:true,timeout:20000},()=>{const peer=socket.getPeerCertificate();socket.end();if(!peer||!peer.raw) reject(new Error('SSO server sent no certificate')); else resolve(peer)});socket.on('error',reject)})}
(async()=>{
  const parsed=pems(fs.readFileSync(path,'utf8')).map(pem=>new crypto.X509Certificate(pem));
  const trialCert=parsed.find(cert=>fp(cert)===trial);
  if(!trialCert) throw new Error('trial CA is missing from the combined trust file');
  let publiclyTrusted=false;
  try{await connect(tls.rootCertificates);publiclyTrusted=true}catch{publiclyTrusted=false}
  if(publiclyTrusted) throw new Error('SSO certificate is trusted by public roots without the bundled CA');
  const peer=await connect(parsed.map(cert=>cert.toString()));
  const leaf=new crypto.X509Certificate(peer.raw);
  const signer=parsed.find(cert=>{try{return fp(cert)===fp(leaf)||leaf.verify(cert.publicKey)}catch{return false}});
  if(!signer) throw new Error('SSO signing CA is not in the combined trust file: peer='+fp(leaf));
  await connect([signer.toString()]);
  const body=await new Promise((resolve,reject)=>{const req=https.get(realm+'/.well-known/openid-configuration',{ca:[signer.toString()],servername:host,rejectUnauthorized:true,timeout:20000},res=>{const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,text:Buffer.concat(chunks).toString('utf8')}))});req.on('error',reject)});
  const document=JSON.parse(body.text);
  if(body.status!==200||document.issuer!==realm) throw new Error('Keycloak discovery failed: HTTP '+body.status);
  let unrelatedRejected=false;
  try{await connect([trialCert.toString()])}catch{unrelatedRejected=true}
  if(!unrelatedRejected) throw new Error('unrelated trial CA validated the SSO certificate');
  console.log('CloudTAK SSO verified peer='+fp(leaf)+' signer='+fp(signer)+' trial_ca_rejected=true');
})().catch(error=>{console.error(String(error&&error.message||error).replace(/\s+/g,' ').slice(0,300));process.exitCode=1});"""
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
        before = self.kube.pods()
        self.set_certs(append_ca(self.saved, pem_text))
        wait_for(lambda: self.bundles_match(fingerprint), "signing CA propagation", 180)
        wait_for(lambda: self.replaced_pods(before), "reload after installing the SSO signing CA")
        print(f"installed SSO signing CA {fingerprint} into the trust bundle and reloaded consumers", flush=True)

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
