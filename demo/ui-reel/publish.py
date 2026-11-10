#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Publish an existing verified UI reel; never render, create a release or overwrite."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

WORKFLOW = ".github/workflows/ui-reel.yaml"
REF = "refs/heads/main"
VIDEO = "uds-takserver-ui-preview.mp4"
MANIFEST = "edit-manifest.json"
BUNDLE = "attestation.sigstore.json"
OUTPUTS = {VIDEO, "poster.jpg", "review-strip.jpg", "Inter-LICENSE.txt"}
FILES = OUTPUTS | {MANIFEST, BUNDLE}
LIMIT = 64 * 1024 * 1024
MARKER = "<!-- ui-reel-preview -->"
END_MARKER = "<!-- /ui-reel-preview -->"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mode(tag, run_id, ref):
    require(ref == REF, "UI reel dispatch requires main")
    if not tag and not run_id:
        return "render"
    require(re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag),
            "publish requires a stable vMAJOR.MINOR.PATCH release tag")
    require(re.fullmatch(r"[1-9][0-9]{0,19}", run_id),
            "publish requires a positive source_run_id paired with release_tag")
    return "publish"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class GitHub:
    def run(self, *args, binary=False):
        # Never echo subprocess output on failure: CLI diagnostics may contain URLs
        # with signed download credentials. Every invocation has a finite timeout.
        try:
            result = subprocess.run(["gh", *args], check=True, capture_output=True,
                                    timeout=120)
        except (subprocess.SubprocessError, OSError) as error:
            raise ValueError("GitHub command failed; publication stopped") from error
        require(len(result.stdout) <= LIMIT, "GitHub response exceeds size bound")
        return result.stdout if binary else json.loads(result.stdout)

    def api(self, path):
        return self.run("api", path)


def run_identity(gh, repo, run_id):
    repository = gh.api(f"repos/{repo}")
    require(repository["full_name"] == repo, "repository identity changed")
    workflow = gh.api(f"repos/{repo}/actions/workflows/ui-reel.yaml")
    require(workflow["path"] == WORKFLOW, "unexpected source workflow")
    run = gh.api(f"repos/{repo}/actions/runs/{run_id}")
    require(run["id"] == int(run_id) and run["workflow_id"] == workflow["id"]
            and run["path"] == WORKFLOW, "source run/workflow mismatch")
    require(run["status"] == "completed" and run["conclusion"] == "success",
            "source run must be completed and successful")
    require(run["event"] == "workflow_dispatch" and run["head_branch"] == "main",
            "source must be a main-branch manual run")
    require(type(run["run_attempt"]) is int and run["run_attempt"] > 0,
            "invalid source run attempt")
    require(re.fullmatch(r"[0-9a-f]{40}", run["head_sha"]), "invalid source commit")
    for key in ("repository", "head_repository"):
        require(run[key]["id"] == repository["id"] and run[key]["full_name"] == repo,
                "source run must belong to this repository, not a fork")
    return repository, run


def identity_fingerprint(repository, run):
    """Compare provenance identity, excluding mutable display/repository metadata."""
    return (
        repository["id"], repository["full_name"], repository["owner"]["id"],
        tuple(run[key] for key in (
            "id", "workflow_id", "path", "status", "conclusion", "event",
            "head_branch", "head_sha", "run_attempt")),
        tuple((run[key]["id"], run[key]["full_name"])
              for key in ("repository", "head_repository")),
    )


def artifact_bytes(gh, repo, repository, run):
    pages = gh.run("api", "--paginate", "--slurp",
                   f"repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100")
    found = [a for page in pages for a in page["artifacts"]
             if a["name"] == "ui-reel-preview"]
    require(len(found) == 1 and not found[0]["expired"],
            "expected one unexpired ui-reel-preview artifact")
    artifact = found[0]
    expected = {"id": run["id"], "repository_id": repository["id"],
                "head_repository_id": repository["id"], "head_branch": "main",
                "head_sha": run["head_sha"]}
    require(all(artifact["workflow_run"].get(k) == v for k, v in expected.items()),
            "artifact source identity mismatch")
    require(0 < artifact["size_in_bytes"] <= LIMIT, "artifact exceeds size bound")
    data = gh.run("api", f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
    require(len(data) == artifact["size_in_bytes"]
            and artifact["digest"] == "sha256:" + sha(data), "artifact archive digest/size mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == len(FILES) and {e.filename for e in entries} == FILES,
                "artifact must contain exactly the six fixed preview files")
        require(all(not e.is_dir() and not stat.S_ISLNK(e.external_attr >> 16)
                    and 0 < e.file_size <= LIMIT for e in entries)
                and sum(e.file_size for e in entries) <= LIMIT,
                "unsafe or oversized archive entry")
        return {e.filename: archive.read(e) for e in entries}


def verify_manifest(files):
    manifest = json.loads(files[MANIFEST])
    outputs = manifest["outputs"]
    require(len(outputs) == len(OUTPUTS) and {item["file"] for item in outputs} == OUTPUTS,
            "manifest output inventory mismatch")
    for item in outputs:
        data = files[item["file"]]
        require(type(item["bytes"]) is int and item["bytes"] == len(data)
                and item["sha256"] == sha(data), "manifest output digest/size mismatch")


def verify_statement(statement, files, repo, repository, run):
    require(statement["_type"] == "https://in-toto.io/Statement/v1"
            and statement["predicateType"] == "https://slsa.dev/provenance/v1",
            "unexpected attestation type")
    subjects = statement["subject"]
    expected = {name: {"sha256": sha(files[name])} for name in (VIDEO, MANIFEST)}
    require(len(subjects) == 2 and {s["name"]: s["digest"] for s in subjects} == expected,
            "signed subject inventory/digest mismatch")
    definition = statement["predicate"]["buildDefinition"]
    require(definition["buildType"] == "https://actions.github.io/buildtypes/workflow/v1",
            "unexpected attested build type")
    require(definition["externalParameters"]["workflow"] == {
        "ref": REF, "repository": f"https://github.com/{repo}", "path": WORKFLOW},
        "signed workflow identity mismatch")
    github = definition["internalParameters"]["github"]
    require(github["event_name"] == "workflow_dispatch"
            and github["repository_id"] == str(repository["id"])
            and github["repository_owner_id"] == str(repository["owner"]["id"]),
            "signed repository/owner/event mismatch")
    require(definition["resolvedDependencies"] == [{
        "uri": f"git+https://github.com/{repo}@{REF}",
        "digest": {"gitCommit": run["head_sha"]}}], "signed source commit/ref mismatch")
    details = statement["predicate"]["runDetails"]
    require(details["builder"]["id"] == f"https://github.com/{repo}/{WORKFLOW}@{REF}",
            "signed builder mismatch")
    require(details["metadata"]["invocationId"] == invocation(repo, run),
            "signed invocation does not match the source run attempt")


def invocation(repo, run):
    return f"https://github.com/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}"


def verify_attestations(gh, directory, files, repo, repository, run):
    for name in (VIDEO, MANIFEST):
        results = gh.run("attestation", "verify", str(directory / name),
                         "--bundle", str(directory / BUNDLE), "--repo", repo,
                         "--signer-workflow", f"{repo}/{WORKFLOW}",
                         "--signer-digest", run["head_sha"], "--source-digest", run["head_sha"],
                         "--source-ref", REF, "--cert-oidc-issuer",
                         "https://token.actions.githubusercontent.com", "--predicate-type",
                         "https://slsa.dev/provenance/v1", "--format", "json")
        require(len(results) == 1, "expected one verified attestation per subject")
        # Only use the cryptographically verified result, never an unverified
        # decode of the bundle's DSSE payload.
        verify_statement(results[0]["verificationResult"]["statement"], files,
                         repo, repository, run)


def release(gh, repo, tag):
    result = gh.api(f"repos/{repo}/releases/tags/{tag}")
    require(result["tag_name"] == tag and result["draft"] is False
            and result["prerelease"] is False, "target must be an existing stable published release")
    return result


def matching_assets(gh, repo, release_id, files):
    pages = gh.run("api", "--paginate", "--slurp",
                   f"repos/{repo}/releases/{release_id}/assets?per_page=100")
    present = set()
    for asset in (a for page in pages for a in page):
        name = asset["name"]
        if name in FILES:
            require(name not in present and asset["state"] == "uploaded"
                    and asset["size"] == len(files[name])
                    and asset.get("digest") == "sha256:" + sha(files[name]),
                    "release asset collision or unverifiable existing asset: " + name)
            present.add(name)
    return present


def preview_section(repo, tag, run):
    base = f"https://github.com/{repo}/releases/download/{tag}"
    return (f"{MARKER}\n### UI preview\n\n"
            "An edit of previously recorded CloudTAK mapping and TAK Server "
            "administration footage.\n\n"
            f"[Video]({base}/{VIDEO}) · [Poster]({base}/poster.jpg) · "
            f"[Review strip]({base}/review-strip.jpg) · [Manifest]({base}/{MANIFEST}) · "
            f"[Attestation]({base}/{BUNDLE}) · [Font license]({base}/Inter-LICENSE.txt)\n\n"
            f"Source: [verified run {run['id']}, attempt {run['run_attempt']}]"
            f"({invocation(repo, run)}), commit `{run['head_sha']}`.\n{END_MARKER}")


def updated_body(body, section):
    body = body or ""
    if MARKER in body or END_MARKER in body:
        require(body.count(MARKER) == body.count(END_MARKER) == 1 and section in body,
                "release already contains a different or incomplete UI preview section")
        return body
    return body.rstrip() + "\n\n" + section + "\n"


def publish(gh, repo, tag, run_id, ref):
    require(mode(tag, run_id, ref) == "publish", "publisher requires paired inputs")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo), "invalid repository")
    repository, run = run_identity(gh, repo, run_id)
    target = release(gh, repo, tag)
    section = preview_section(repo, tag, run)
    updated_body(target.get("body"), section)  # Reject a section conflict before uploads.
    files = artifact_bytes(gh, repo, repository, run)
    verify_manifest(files)
    with tempfile.TemporaryDirectory(prefix="ui-reel-publish-") as temporary:
        directory = Path(temporary)
        for name, data in files.items():
            (directory / name).write_bytes(data)
        verify_attestations(gh, directory, files, repo, repository, run)
        present = matching_assets(gh, repo, target["id"], files)
        # Re-read mutable run/release metadata immediately before the first write.
        require(identity_fingerprint(*run_identity(gh, repo, run_id))
                == identity_fingerprint(repository, run),
                "source run changed during verification")
        current = release(gh, repo, tag)
        require(current["id"] == target["id"], "release identity changed")
        updated_body(current.get("body"), section)
        for name in sorted(FILES - present):
            require((directory / name).read_bytes() == files[name], "staged bytes changed")
            gh.run("release", "upload", tag, str(directory / name), "--repo", repo, binary=True)
            require(name in matching_assets(gh, repo, target["id"], files),
                    "uploaded asset was not confirmed by the API")
        require(matching_assets(gh, repo, target["id"], files) == FILES,
                "release preview is incomplete")
        current = release(gh, repo, tag)
        require(current["id"] == target["id"], "release identity changed")
        body = updated_body(current.get("body"), section)
        if body != (current.get("body") or ""):
            request = directory / "release-body.json"
            request.write_text(json.dumps({"body": body}), encoding="utf-8")
            gh.run("api", "--method", "PATCH", f"repos/{repo}/releases/{target['id']}",
                   "--input", str(request))
    print(f"Verified UI preview assets retained on {tag} from run {run_id}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode-only", action="store_true")
    args = parser.parse_args()
    try:
        tag = os.environ.get("RELEASE_TAG", "")
        run_id = os.environ.get("SOURCE_RUN_ID", "")
        ref = os.environ.get("GITHUB_REF", "")
        selected = mode(tag, run_id, ref)
        if args.mode_only:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"mode={selected}\n")
        else:
            publish(GitHub(), os.environ["GITHUB_REPOSITORY"], tag, run_id, ref)
    except ValueError as error:
        raise SystemExit(f"UI preview publication refused: {error}") from None
    except (KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
        # Do not include API/CLI response bodies or signed download URLs in logs.
        raise SystemExit(f"UI preview publication refused ({type(error).__name__}).") from None


if __name__ == "__main__":
    main()
