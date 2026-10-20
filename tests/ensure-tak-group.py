#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Put the test user in /TAK/Operators_READ as well as /UDS Core/Admin.

setup:keycloak-user accepts one group. TAK maps groups under /TAK/ and
strips the _READ suffix, so the groups API can show Operators.
"""

import base64
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ADMIN = os.environ.get("KEYCLOAK_ADMIN_URL", "https://keycloak.admin.uds.dev")
REALM = "uds"
USER = os.environ.get("KEYCLOAK_USER", "doug")
PARENT = "TAK"
CHILD = "Operators_READ"


def kubectl(*args):
    configured = os.environ.get("KUBECTL", "")
    base = shlex.split(configured) if configured else ["kubectl"]
    if not configured and subprocess.call(["bash", "-lc", "command -v kubectl"], stdout=subprocess.DEVNULL) != 0:
        base = ["./zarf", "tools", "kubectl"]
    result = subprocess.run(base + list(args), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def request(method, path, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        ADMIN + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        if error.code == 404:
            return error.code, None
        sys.stderr.write(raw + "\n")
        raise SystemExit(error.code) from error


def token():
    encoded = kubectl(
        "get",
        "secret",
        "-n",
        "keycloak",
        "keycloak-admin-password",
        "-o",
        "jsonpath={.data.password}",
    )
    password = base64.b64decode(encoded).decode().strip()
    form = urllib.parse.urlencode(
        {
            "username": "admin",
            "password": password,
            "client_id": "admin-cli",
            "grant_type": "password",
        }
    ).encode()
    req = urllib.request.Request(
        ADMIN + "/realms/master/protocol/openid-connect/token",
        data=form,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["access_token"]


def group_by_path(access, path):
    encoded = urllib.parse.quote(path.strip("/"))
    status, body = request("GET", f"/admin/realms/{REALM}/group-by-path/{encoded}", access)
    if status == 404:
        return None
    return body


def ensure_group(access):
    existing = group_by_path(access, f"{PARENT}/{CHILD}")
    if existing and existing.get("id"):
        return existing["id"]
    parent = group_by_path(access, PARENT)
    if parent is None:
        request("POST", f"/admin/realms/{REALM}/groups", access, {"name": PARENT})
        parent = group_by_path(access, PARENT)
    if parent is None or not parent.get("id"):
        raise SystemExit(f"could not create /{PARENT}")
    request(
        "POST",
        f"/admin/realms/{REALM}/groups/{parent['id']}/children",
        access,
        {"name": CHILD},
    )
    created = group_by_path(access, f"{PARENT}/{CHILD}")
    if created is None or not created.get("id"):
        raise SystemExit(f"could not create /{PARENT}/{CHILD}")
    return created["id"]


def user_id(access):
    query = urllib.parse.urlencode({"username": USER, "exact": "true"})
    _status, body = request("GET", f"/admin/realms/{REALM}/users?{query}", access)
    if not body:
        raise SystemExit(f"Keycloak user {USER} was not found")
    return body[0]["id"]


def main():
    access = token()
    group_id = ensure_group(access)
    uid = user_id(access)
    request("PUT", f"/admin/realms/{REALM}/users/{uid}/groups/{group_id}", access, {})
    print(f"{USER} is in /{PARENT}/{CHILD}")


if __name__ == "__main__":
    main()
