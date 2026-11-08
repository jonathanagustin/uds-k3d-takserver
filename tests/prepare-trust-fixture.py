#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Prepare private PKI for the disposable trust-only baseline install."""

import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile


PREFIX = "uds-private-gateway-"


def validate_domain(domain):
    domain = str(domain).lower().rstrip(".")
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("private gateway fixture requires a valid DNS domain")
    return domain


def prepare(config, parent, mask=lambda _value: None):
    config = copy.deepcopy(config)
    variables = config.setdefault("variables", {})
    application = variables.setdefault("takserver", {})
    core = variables.setdefault("core-base", {})
    domain = validate_domain(application.get("DOMAIN", "uds.dev"))
    if core.get("DOMAIN", domain) != domain:
        raise ValueError("Core and TAK domains must agree for the private gateway fixture")
    directory = Path(tempfile.mkdtemp(prefix=PREFIX, dir=parent))
    directory.chmod(0o700)
    previous_umask = os.umask(0o077)
    try:
        def openssl(*args):
            subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=30)

        ca, ca_key = directory / "ca.pem", directory / "ca.key"
        cert, key = directory / "tenant.pem", directory / "tenant.key"
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-sha256",
                "-subj", "/CN=UDS disposable private gateway CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", ca_key, "-out", ca)
        openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=*." + domain,
                "-keyout", key, "-out", directory / "tenant.csr")
        extensions = directory / "tenant.ext"
        extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                              "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
                              f"subjectAltName=DNS:*.{domain},DNS:{domain}\n")
        openssl("x509", "-req", "-in", directory / "tenant.csr", "-CA", ca, "-CAkey", ca_key,
                "-CAcreateserial", "-days", "1", "-sha256", "-extfile", extensions, "-out", cert)
        ca_key.unlink()
        private_key = key.read_text()
        encoded_key = base64.b64encode(private_key.encode()).decode()
        mask(encoded_key)
        for line in private_key.splitlines():
            mask(line)
        existing = core.get("CA_BUNDLE_CERTS", "")
        original = base64.b64decode(existing, validate=True).decode() if existing else ""
        ca_text = ca.read_text()
        core.update({"DOMAIN": domain,
                     "CA_BUNDLE_CERTS": base64.b64encode((original.rstrip() + "\n" + ca_text).encode()).decode(),
                     "TENANT_TLS_CERT": base64.b64encode((cert.read_text() + ca_text).encode()).decode(),
                     "TENANT_TLS_KEY": encoded_key})
        path = directory / "uds-config.yaml"
        # JSON is also YAML; no extra YAML dependency is needed on CI runners.
        path.write_text(json.dumps(config, indent=2) + "\n")
        path.chmod(0o600)
        key.chmod(0o600)
        # Retain public host roots for registries and add the private gateway CA.
        system_ca = ssl.get_default_verify_paths().cafile
        if not system_ca or not Path(system_ca).is_file():
            raise ValueError("system CA file is required for private gateway host trust")
        host_ca = directory / "host-ca.pem"
        host_ca.write_text(Path(system_ca).read_text() + "\n" + ca_text)
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(ca_text)).hexdigest()
        return {"directory": str(directory), "config": str(path), "ca": str(ca),
                "host-ca": str(host_ca), "fingerprint": fingerprint}
    except BaseException:
        shutil.rmtree(directory)
        raise
    finally:
        os.umask(previous_umask)


def cleanup(directory, parent):
    directory, parent = Path(directory), Path(parent)
    if directory.is_symlink() or directory.parent.resolve() != parent.resolve() or not directory.name.startswith(PREFIX):
        raise ValueError("refusing to remove a directory outside the private gateway fixture")
    shutil.rmtree(directory, ignore_errors=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "cleanup"))
    parser.add_argument("--parent", required=True)
    parser.add_argument("--directory")
    args = parser.parse_args()
    if args.action == "cleanup":
        if not args.directory:
            parser.error("cleanup requires --directory")
        cleanup(args.directory, args.parent)
        return

    def mask(value):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::add-mask::" + value, flush=True)

    result = prepare(json.load(sys.stdin), args.parent, mask)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as stream:
            for name, value in result.items():
                stream.write(f"{name}={value}\n")
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
