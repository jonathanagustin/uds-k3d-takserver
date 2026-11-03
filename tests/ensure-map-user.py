#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Create the non-admin CloudTAK test user.

The user is in /CloudTAK/Users, the CloudTAK login group, and in
/TAK/Operators_READ so TAK gives its certificate a TAK group. It is not in
/UDS Core/Admin, so Keycloak must refuse it for the TAK Server web UI, and
CloudTAK must not make it a system administrator. The script creates any
missing group and removes every other group from the user.
"""

import importlib.util
import os
import urllib.parse
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ensure_tak_group", Path(__file__).resolve().parent / "ensure-tak-group.py"
)
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)

REALM = kc.REALM
USER = os.environ.get("KEYCLOAK_MAP_USER", "mapuser")
PASSWORD = os.environ.get("KEYCLOAK_MAP_USER_PASSWORD", "mapuser123!@#UN")
GROUPS = ["/CloudTAK/Users", "/TAK/Operators_READ"]


def ensure_path(access, path):
    """Return the id of the group at path, creating each missing level."""
    parent = None
    walked = ""
    for name in path.strip("/").split("/"):
        walked = f"{walked}/{name}"
        group = kc.group_by_path(access, walked)
        if group is None or not group.get("id"):
            if parent is None:
                kc.request("POST", f"/admin/realms/{REALM}/groups", access, {"name": name})
            else:
                kc.request("POST", f"/admin/realms/{REALM}/groups/{parent}/children", access, {"name": name})
            group = kc.group_by_path(access, walked)
        if group is None or not group.get("id"):
            raise SystemExit(f"could not create {walked}")
        parent = group["id"]
    return parent


def user_id(access):
    query = urllib.parse.urlencode({"username": USER, "exact": "true"})
    _status, body = kc.request("GET", f"/admin/realms/{REALM}/users?{query}", access)
    return body[0]["id"] if body else None


def main():
    access = kc.token()
    wanted = {ensure_path(access, path): path for path in GROUPS}
    uid = user_id(access)
    if uid is None:
        kc.request(
            "POST",
            f"/admin/realms/{REALM}/users",
            access,
            {
                "username": USER,
                "enabled": True,
                "email": f"{USER}@uds.dev",
                "emailVerified": True,
                "firstName": "Map",
                "lastName": "User",
                "requiredActions": [],
            },
        )
        uid = user_id(access)
    if not uid:
        raise SystemExit(f"Keycloak user {USER} was not created")
    kc.request(
        "PUT",
        f"/admin/realms/{REALM}/users/{uid}/reset-password",
        access,
        {"type": "password", "value": PASSWORD, "temporary": False},
    )
    _status, current = kc.request("GET", f"/admin/realms/{REALM}/users/{uid}/groups", access)
    for group in current or []:
        if group["id"] not in wanted:
            kc.request("DELETE", f"/admin/realms/{REALM}/users/{uid}/groups/{group['id']}", access)
    for gid in wanted:
        kc.request("PUT", f"/admin/realms/{REALM}/users/{uid}/groups/{gid}", access, {})
    print(f"{USER} is in {', '.join(GROUPS)} and no other group")


if __name__ == "__main__":
    main()
