#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Read the TAK and CloudTAK Keycloak clients and check their attributes.

The expected values are the chart values in charts/takserver/values.yaml and
charts/cloudtak/values.yaml. Keycloak's default session idle is 1800 seconds
and the default max lifespan is 36000. UDS Core 1.15.2 does not override those
realm settings.
"""

import importlib.util
import os
import sys
import urllib.parse
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ensure_tak_group", Path(__file__).resolve().parent / "ensure-tak-group.py"
)
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)

REALM = kc.REALM
DOMAIN = os.environ.get("DOMAIN", "uds.dev")
IDLE = "1800"
LIFESPAN = "36000"

EXPECTED = {
    "uds-takserver": {
        "use.refresh.tokens": "true",
        "client.session.idle.timeout": IDLE,
        "client.session.max.lifespan": LIFESPAN,
        "post.logout.redirect.uris": f"https://takserver.{DOMAIN}/login/redirect",
    },
    "uds-cloudtak": {
        "pkce.code.challenge.method": "S256",
        "client.session.idle.timeout": IDLE,
        "client.session.max.lifespan": LIFESPAN,
        "post.logout.redirect.uris": f"https://map.{DOMAIN}/api/login/oidc",
    },
}


def client_by_id(access, client_id):
    query = urllib.parse.urlencode({"clientId": client_id})
    _status, body = kc.request("GET", f"/admin/realms/{REALM}/clients?{query}", access)
    for client in body or []:
        if client.get("clientId") == client_id:
            return client
    return None


def main():
    access = kc.token()
    failed = False
    for client_id, want in EXPECTED.items():
        client = client_by_id(access, client_id)
        if client is None:
            print(f"missing client {client_id}", file=sys.stderr)
            failed = True
            continue
        got = client.get("attributes") or {}
        for key, value in want.items():
            actual = str(got.get(key, ""))
            if value not in actual.split("##") and value not in actual:
                print(f"{client_id} {key}: got {actual!r}, want {value}", file=sys.stderr)
                failed = True
            else:
                print(f"{client_id} {key}={actual}")
    if failed:
        raise SystemExit(1)
    print("Keycloak client attributes match the chart")


if __name__ == "__main__":
    sys.exit(main())
