#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Create or update the Keycloak user the demo signs in as.

Reads DEMO_KEYCLOAK_USER (default takuser) and DEMO_KEYCLOAK_PASSWORD. The
user gets /UDS Core/Admin (ROLE_ADMIN in TAK) and both directions of TAK
group Operators: /TAK/Operators_READ (TAK sends the group's traffic to the
user) and /TAK/Operators_WRITE (the user's CloudTAK can send to the group).
The ATAK test device is in Operators, so without _WRITE a marker or chat
shared from CloudTAK never reaches it. DEMO_KEYCLOAK_GROUPS, a
comma-separated list of group paths, replaces that list; a group that does
not exist yet is created. The non-admin CloudTAK chapter uses
"/CloudTAK/Users,/TAK/Operators_READ". The password is set on every run, so
record-web.sh can generate a new one each time. It is never printed.
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
GROUPS = [
    g.strip().strip("/")
    for g in os.environ.get("DEMO_KEYCLOAK_GROUPS", "/UDS Core/Admin,/TAK/Operators_READ,/TAK/Operators_WRITE").split(",")
    if g.strip()
]


def ensure_path(access, path):
    """The id of the group at PATH (no leading slash), created if missing."""
    found = kc.group_by_path(access, path)
    if found and found.get("id"):
        return found["id"]
    if path == "UDS Core/Admin":
        raise SystemExit("group /UDS Core/Admin was not found")
    parent, _, name = path.rpartition("/")
    if parent:
        parent_id = ensure_path(access, parent)
        kc.request("POST", f"/admin/realms/{REALM}/groups/{parent_id}/children", access, {"name": name})
    else:
        kc.request("POST", f"/admin/realms/{REALM}/groups", access, {"name": name})
    found = kc.group_by_path(access, path)
    if not found or not found.get("id"):
        raise SystemExit(f"could not create /{path}")
    return found["id"]


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
    for path in GROUPS:
        kc.request("PUT", f"/admin/realms/{REALM}/users/{uid}/groups/{ensure_path(access, path)}", access, {})
    print(f"Keycloak user {USER} is ready in " + " and ".join(f"/{path}" for path in GROUPS))


if __name__ == "__main__":
    sys.exit(main())
