#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Create or update the Keycloak user the demo signs in as.

Reads DEMO_KEYCLOAK_USER (default takuser) and DEMO_KEYCLOAK_PASSWORD. The
user gets the same groups as the test user: /UDS Core/Admin (ROLE_ADMIN in
TAK) and /TAK/Operators_READ (TAK group Operators). The password is set on
every run, so record-web.sh can generate a new one each time. It is never
printed.
"""

import importlib.util
import os
import sys
import urllib.parse
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ensure_tak_group", Path(__file__).resolve().parent.parent / "tests" / "ensure-tak-group.py"
)
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)

REALM = kc.REALM
USER = os.environ.get("DEMO_KEYCLOAK_USER", "takuser")
PASSWORD = os.environ.get("DEMO_KEYCLOAK_PASSWORD", "")


def find_user(access):
    query = urllib.parse.urlencode({"username": USER, "exact": "true"})
    _status, body = kc.request("GET", f"/admin/realms/{REALM}/users?{query}", access)
    return body[0]["id"] if body else None


def main():
    if not PASSWORD:
        raise SystemExit("DEMO_KEYCLOAK_PASSWORD is not set")
    access = kc.token()
    uid = find_user(access)
    if uid is None:
        kc.request(
            "POST",
            f"/admin/realms/{REALM}/users",
            access,
            {
                "username": USER,
                "firstName": "TAK",
                "lastName": "User",
                "email": f"{USER}@uds.dev",
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
            },
        )
        uid = find_user(access)
    if uid is None:
        raise SystemExit(f"could not create Keycloak user {USER}")
    kc.request(
        "PUT",
        f"/admin/realms/{REALM}/users/{uid}/reset-password",
        access,
        {"type": "password", "value": PASSWORD, "temporary": False},
    )
    admin = kc.group_by_path(access, "UDS Core/Admin")
    if not admin or not admin.get("id"):
        raise SystemExit("group /UDS Core/Admin was not found")
    for group_id in (admin["id"], kc.ensure_group(access)):
        kc.request("PUT", f"/admin/realms/{REALM}/users/{uid}/groups/{group_id}", access, {})
    print(f"Keycloak user {USER} is ready in /UDS Core/Admin and /TAK/Operators_READ")


if __name__ == "__main__":
    sys.exit(main())
