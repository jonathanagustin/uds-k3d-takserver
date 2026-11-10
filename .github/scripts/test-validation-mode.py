#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Plan Test's cluster work and verify intentional acceptance-mode skips."""

import json
import os
import sys


def trust_only(event, requested):
    return event == "workflow_dispatch" and requested == "true"


def diagnostic_case(event, requested, selected="none"):
    # Inputs from non-manual events cannot reduce required coverage.
    if event != "workflow_dispatch":
        return "none"
    selected = selected or "none"
    if selected not in {"none", "upgrade-amd64", "pg15-amd64"}:
        raise ValueError("Unknown diagnostic case")
    if selected != "none" and trust_only(event, requested):
        raise ValueError("Diagnostic case and trust_bundle cannot be combined")
    return selected


def plan(event, requested, amd64_runner, selected="none"):
    selected = diagnostic_case(event, requested, selected)
    upgrades = {"include": [{"arch": "amd64", "runner": amd64_runner},
                             {"arch": "arm64", "runner": "ubuntu-22.04-arm"}]}
    single = {"include": [{"arch": "amd64", "runner": amd64_runner}]}
    return {"install-matrix": install_matrix(event, requested, amd64_runner),
            "upgrade-matrix": single if selected == "upgrade-amd64" else upgrades,
            "pg15-matrix": single if selected == "pg15-amd64" else upgrades,
            "diagnostic-case": selected}


def install_matrix(event, requested, amd64_runner):
    include = [{"arch": "amd64", "runner": amd64_runner},
               {"arch": "arm64", "runner": "ubuntu-22.04-arm"}]
    if not trust_only(event, requested):
        include.append({"arch": "amd64", "runner": amd64_runner, "airgap": True})
    return {"include": include}


def verify(event, requested, install, upgrade, pg15, selected="none", pg15_required="false"):
    if pg15_required not in {"true", "false"}:
        raise ValueError("Unknown PostgreSQL 15 expectation")
    selected = diagnostic_case(event, requested, selected)
    if selected != "none":
        expected = (("skipped", "success", "skipped") if selected == "upgrade-amd64"
                    else ("skipped", "skipped", "success"))
        if (install, upgrade, pg15) != expected:
            raise ValueError(f"Diagnostic results {(install, upgrade, pg15)}; expected {expected}")
        return
    if install != "success":
        raise ValueError(f"Install did not pass: {install}")
    expected_upgrade = "skipped" if trust_only(event, requested) else "success"
    if upgrade != expected_upgrade:
        raise ValueError(f"Upgrade result {upgrade}; expected {expected_upgrade}")
    if trust_only(event, requested):
        allowed_pg15 = {"skipped"}
    elif event == "push" or (event == "pull_request" and pg15_required == "true"):
        # A missing or false flag cannot weaken the unconditional push policy.
        # For PRs the workflow supplies its label-based selection policy,
        # independently of the job result being verified.
        allowed_pg15 = {"success"}
    else:
        allowed_pg15 = {"success", "skipped"}
    if pg15 not in allowed_pg15:
        raise ValueError(f"PostgreSQL 15 upgrade did not pass or intentionally skip: {pg15}")


def main():
    event, requested = os.environ["EVENT_NAME"], os.environ.get("TRUST_BUNDLE", "false")
    selected = diagnostic_case(event, requested, os.environ.get("DIAGNOSTIC_CASE", "none"))
    if sys.argv[1:] == ["plan"]:
        outputs = plan(event, requested, os.environ.get("TEST_RUNNER") or "ubuntu-22.04", selected)
        output = "".join(key + "=" + (value if isinstance(value, str) else
                         json.dumps(value, separators=(",", ":"))) + "\n"
                         for key, value in outputs.items())
        if path := os.environ.get("GITHUB_OUTPUT"):
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(output)
        else:
            print(output, end="")
        return
    if sys.argv[1:] != ["verify"]:
        raise ValueError("expected plan or verify")
    verify(event, requested, os.environ["INSTALL_RESULT"], os.environ["UPGRADE_RESULT"], os.environ["PG15_RESULT"],
           selected, os.environ.get("PG15_REQUIRED", "false"))
    if selected != "none":
        print("Selected diagnostic case passed—not full acceptance")
        return
    print("Trust-only acceptance passed." if trust_only(event, requested) else "All tests passed successfully!")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError) as error:
        print(f"Test validation failed: {error}", file=sys.stderr)
        sys.exit(1)
