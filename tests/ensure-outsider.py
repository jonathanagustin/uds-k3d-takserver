#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Create a Keycloak user with no groups for the Portal tile check.

setup:keycloak-user puts doug in /UDS Core/Admin. TAK and CloudTAK both
require that group. This account is the one that must see neither tile.
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
USER = os.environ.get("KEYCLOAK_OUTSIDER", "outsider")
PASSWORD = os.environ.get("KEYCLOAK_OUTSIDER_PASSWORD", "outsider123!@#UN")


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
        if error.code in (404, 409):
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


def user_id(access):
    query = urllib.parse.urlencode({"username": USER, "exact": "true"})
    _status, body = request("GET", f"/admin/realms/{REALM}/users?{query}", access)
    if not body:
        return None
    return body[0]["id"]


def main():
    access = token()
    uid = user_id(access)
    if uid is None:
        status, _body = request(
            "POST",
            f"/admin/realms/{REALM}/users",
            access,
            {"username": USER, "enabled": True},
        )
        if status not in (201, 204, 409):
            raise SystemExit(f"creating {USER} returned {status}")
        uid = user_id(access)
    if not uid:
        raise SystemExit(f"Keycloak user {USER} was not created")
    request(
        "PUT",
        f"/admin/realms/{REALM}/users/{uid}/reset-password",
        access,
        {"type": "password", "value": PASSWORD, "temporary": False},
    )
    _status, groups = request("GET", f"/admin/realms/{REALM}/users/{uid}/groups", access)
    for group in groups or []:
        request("DELETE", f"/admin/realms/{REALM}/users/{uid}/groups/{group['id']}", access)
    print(f"{USER} has no groups")


if __name__ == "__main__":
    main()
