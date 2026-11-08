#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Plan Test's cluster work and verify intentional acceptance-mode skips."""

import json
import os
import sys


def trust_only(event, requested):
    return event == "workflow_dispatch" and requested == "true"


def install_matrix(event, requested, amd64_runner):
    include = [{"arch": "amd64", "runner": amd64_runner},
               {"arch": "arm64", "runner": "ubuntu-22.04-arm"}]
    if not trust_only(event, requested):
        include.append({"arch": "amd64", "runner": amd64_runner, "airgap": True})
    return {"include": include}


def verify(event, requested, install, upgrade, pg15):
    if install != "success":
        raise ValueError(f"Install did not pass: {install}")
    expected_upgrade = "skipped" if trust_only(event, requested) else "success"
    if upgrade != expected_upgrade:
        raise ValueError(f"Upgrade result {upgrade}; expected {expected_upgrade}")
    allowed_pg15 = {"skipped"} if trust_only(event, requested) else {"success", "skipped"}
    if pg15 not in allowed_pg15:
        raise ValueError(f"PostgreSQL 15 upgrade did not pass or intentionally skip: {pg15}")


def main():
    event, requested = os.environ["EVENT_NAME"], os.environ.get("TRUST_BUNDLE", "false")
    if sys.argv[1:] == ["plan"]:
        matrix = install_matrix(event, requested, os.environ.get("TEST_RUNNER") or "ubuntu-22.04")
        output = "install-matrix=" + json.dumps(matrix, separators=(",", ":")) + "\n"
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(output)
        else:
            print(output, end="")
        return
    if sys.argv[1:] != ["verify"]:
        raise ValueError("expected plan or verify")
    verify(event, requested, os.environ["INSTALL_RESULT"], os.environ["UPGRADE_RESULT"], os.environ["PG15_RESULT"])
    print("Trust-only acceptance passed." if trust_only(event, requested) else "All tests passed successfully!")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError) as error:
        print(f"Test validation failed: {error}", file=sys.stderr)
        sys.exit(1)
