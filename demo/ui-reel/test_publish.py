# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Offline publishing contracts; fake gh enforces flags, identity and write boundaries."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import unittest
from unittest.mock import patch
import zipfile

import yaml

SPEC = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish.py"))
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
REPO = "example/project"
TAG = "v0.12.0"
RUN_ID = "42"
SHA = "a" * 40


class FakeGitHub(p.GitHub):
    def __init__(self):
        self.calls = []
        self.uploads = []
        self.patches = []
        self.fail_verification = False
        self.bad_upload = False
        self.fail_after = None
        self.repository = {"id": 123, "full_name": REPO, "owner": {"id": 456}}
        self.workflow = {"id": 789, "path": p.WORKFLOW}
        self.source = {"id": 42, "workflow_id": 789, "path": p.WORKFLOW,
                       "status": "completed", "conclusion": "success", "head_branch": "main",
                       "head_sha": SHA, "event": "workflow_dispatch", "run_attempt": 2,
                       "repository": self.repository.copy(), "head_repository": self.repository.copy()}
        self.target = {"id": 88, "tag_name": TAG, "draft": False, "prerelease": False,
                       "body": "Existing release notes."}
        self.files = {name: (name + " fixture\n").encode() for name in p.OUTPUTS}
        self.files[p.MANIFEST] = json.dumps({"outputs": [
            {"file": name, "sha256": p.sha(data), "bytes": len(data)}
            for name, data in self.files.items()]}).encode()
        self.files[p.BUNDLE] = b"signed bundle fixture; verification delegated to gh"
        self.statement = {
            "_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": name, "digest": {"sha256": p.sha(self.files[name])}}
                        for name in (p.VIDEO, p.MANIFEST)],
            "predicateType": "https://slsa.dev/provenance/v1",
            "predicate": {"buildDefinition": {
                "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                "externalParameters": {"workflow": {
                    "ref": p.REF, "repository": f"https://github.com/{REPO}", "path": p.WORKFLOW}},
                "internalParameters": {"github": {
                    "event_name": "workflow_dispatch", "repository_id": "123", "repository_owner_id": "456"}},
                "resolvedDependencies": [{"uri": f"git+https://github.com/{REPO}@{p.REF}",
                                          "digest": {"gitCommit": SHA}}]},
                "runDetails": {"builder": {"id": f"https://github.com/{REPO}/{p.WORKFLOW}@{p.REF}"},
                               "metadata": {"invocationId": p.invocation(REPO, self.source)}}}}
        self.assets = []
        self.artifact = {"id": 99, "name": "ui-reel-preview", "expired": False,
                         "workflow_run": {"id": 42, "repository_id": 123, "head_repository_id": 123,
                                          "head_branch": "main", "head_sha": SHA}}
        self.pack()
        self.artifacts = [self.artifact]

    def pack(self, symlink=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in self.files.items():
                entry = zipfile.ZipInfo(name)
                if name == symlink:
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, data)
        self.archive = output.getvalue()
        self.artifact.update(size_in_bytes=len(self.archive), digest="sha256:" + p.sha(self.archive))

    def asset(self, name):
        return {"name": name, "size": len(self.files[name]), "digest": "sha256:" + p.sha(self.files[name]),
                "state": "uploaded"}

    def run(self, *args, binary=False):
        self.calls.append(args)
        if args[:2] == ("attestation", "verify"):
            if self.fail_verification:
                raise ValueError("signature verification failed")
            expected = ("--bundle", str(Path(args[2]).parent / p.BUNDLE), "--repo", REPO,
                        "--signer-workflow", f"{REPO}/{p.WORKFLOW}", "--signer-digest", SHA,
                        "--source-digest", SHA, "--source-ref", p.REF, "--cert-oidc-issuer",
                        "https://token.actions.githubusercontent.com", "--predicate-type",
                        "https://slsa.dev/provenance/v1", "--format", "json")
            if args[3:] != expected or Path(args[2]).name not in (p.VIDEO, p.MANIFEST):
                raise AssertionError("verification policy omitted or changed")
            if Path(args[2]).read_bytes() != self.files[Path(args[2]).name]:
                raise AssertionError("verification did not consume exact artifact bytes")
            return [{"verificationResult": {"statement": copy.deepcopy(self.statement)}}]
        if args[:2] == ("release", "upload"):
            if args[2] != TAG or args[4:] != ("--repo", REPO):
                raise AssertionError("unexpected upload or clobber")
            if self.fail_after is not None and len(self.uploads) >= self.fail_after:
                raise ValueError("simulated interrupted upload")
            name = Path(args[3]).name
            if Path(args[3]).read_bytes() != self.files[name]:
                raise AssertionError("upload changed artifact bytes")
            if any(a["name"] == name for a in self.assets):
                raise AssertionError("overwrite attempted")
            self.uploads.append(name)
            asset = self.asset(name)
            if self.bad_upload:
                asset["digest"] = "sha256:" + "0" * 64
            self.assets.append(asset)
            return b""
        if args[:3] == ("api", "--method", "PATCH"):
            if args[3] != f"repos/{REPO}/releases/88" or args[4] != "--input":
                raise AssertionError("unexpected write")
            body = json.loads(Path(args[5]).read_text())
            if set(body) != {"body"}:
                raise AssertionError("release metadata mutation beyond body")
            self.patches.append(body)
            self.target.update(body)
            return self.target.copy()
        if args[:3] == ("api", "--paginate", "--slurp"):
            if args[3] == f"repos/{REPO}/actions/runs/{RUN_ID}/artifacts?per_page=100":
                return [{"artifacts": copy.deepcopy(self.artifacts)}]
            if args[3] == f"repos/{REPO}/releases/88/assets?per_page=100":
                return [copy.deepcopy(self.assets)]
        if args[0] == "api" and len(args) == 2:
            responses = {
                f"repos/{REPO}": self.repository,
                f"repos/{REPO}/actions/workflows/ui-reel.yaml": self.workflow,
                f"repos/{REPO}/actions/runs/{RUN_ID}": self.source,
                f"repos/{REPO}/releases/tags/{TAG}": self.target,
                f"repos/{REPO}/actions/artifacts/99/zip": self.archive,
            }
            if args[1] in responses:
                return copy.deepcopy(responses[args[1]])
        raise AssertionError(f"unexpected gh command: {args}")


class PublishTests(unittest.TestCase):
    def publish(self, gh):
        with patch("builtins.print"):
            p.publish(gh, REPO, TAG, RUN_ID, p.REF)

    def refused(self, gh):
        with self.assertRaises(ValueError):
            self.publish(gh)
        self.assertEqual(gh.uploads, [])
        self.assertEqual(gh.patches, [])

    def test_workflow_permissions_mode_routing_and_upload_queue(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / ".github/workflows/ui-reel.yaml").read_text())
        self.assertEqual(set(workflow[True]), {"workflow_dispatch"})
        self.assertNotIn("concurrency", workflow)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        inputs = workflow[True]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"release_tag", "source_run_id"})
        self.assertTrue(all(i["default"] == "" and i["type"] == "string" for i in inputs.values()))
        jobs = workflow["jobs"]
        self.assertEqual(jobs["render"]["permissions"],
                         {"contents": "read", "id-token": "write", "attestations": "write"})
        self.assertEqual(jobs["publish"]["permissions"], {"contents": "write", "actions": "read"})
        self.assertEqual(jobs["publish"]["concurrency"],
                         {"group": "ui-reel-publish", "queue": "max", "cancel-in-progress": False})
        self.assertNotEqual(jobs["render"]["concurrency"]["group"], jobs["publish"]["concurrency"]["group"])
        self.assertTrue(jobs["render"]["concurrency"]["cancel-in-progress"])
        for job in ("render", "publish"):
            self.assertEqual(jobs[job]["needs"], "mode")
            self.assertEqual(jobs[job]["if"],
                             f"github.ref == 'refs/heads/main' && needs.mode.outputs.mode == '{job}'")
        commands = [s.get("run", "") for s in jobs["publish"]["steps"]]
        self.assertIn("python3 demo/ui-reel/publish.py", commands)
        self.assertFalse(any("render.py" in command for command in commands))
        self.assertIn("python3 demo/ui-reel/publish.py --mode-only",
                      [s.get("run", "") for s in jobs["mode"]["steps"]])

    def test_modes_are_paired_stable_and_main_only(self):
        self.assertEqual(p.mode("", "", p.REF), "render")
        self.assertEqual(p.mode(TAG, RUN_ID, p.REF), "publish")
        for tag, run, ref in [(TAG, "", p.REF), ("", RUN_ID, p.REF),
                              ("v1.0.0-rc1", RUN_ID, p.REF), ("v01.0.0", RUN_ID, p.REF),
                              (TAG, "0", p.REF), (TAG, "-1", p.REF), (TAG, "1; echo", p.REF),
                              (TAG, " 42", p.REF), (TAG, "4.2", p.REF),
                              ("", "", "refs/heads/feature"), (TAG, RUN_ID, "refs/tags/v1.0.0")]:
            with self.subTest(tag=tag, run=run, ref=ref), self.assertRaises(ValueError):
                p.mode(tag, run, ref)

    def test_success_keeps_all_bytes_and_verifies_both_subjects(self):
        gh = FakeGitHub()
        self.publish(gh)
        self.assertEqual(set(gh.uploads), p.FILES)
        verified = [Path(c[2]).name for c in gh.calls if c[:2] == ("attestation", "verify")]
        self.assertEqual(verified, [p.VIDEO, p.MANIFEST])
        self.assertEqual(len(gh.patches), 1)
        self.assertIn("Existing release notes.", gh.target["body"])
        self.assertIn("An edit of previously recorded CloudTAK mapping and TAK Server administration footage.",
                      gh.target["body"])
        self.assertIn("/attempts/2", gh.target["body"])

    def test_invalid_run_identity_never_downloads_or_writes(self):
        for key, value in [("id", 43), ("workflow_id", 1), ("path", ".github/workflows/other.yaml"),
                           ("status", "in_progress"), ("conclusion", "failure"), ("head_branch", "feature"),
                           ("event", "pull_request"), ("head_sha", "main"), ("run_attempt", 0)]:
            with self.subTest(key=key):
                gh = FakeGitHub()
                gh.source[key] = value
                self.refused(gh)
                self.assertFalse(any(c[-1].endswith("/zip") for c in gh.calls))
        for key in ("repository", "head_repository"):
            gh = FakeGitHub()
            gh.source[key] = {"id": 999, "full_name": REPO}
            self.refused(gh)

    def test_signed_identity_binds_attempt_owner_event_workflow_and_source(self):
        mutations = [
            lambda s: s["predicate"]["runDetails"]["metadata"].update(invocationId="https://github.com/example/project/actions/runs/42/attempts/1"),
            lambda s: s["predicate"]["runDetails"]["metadata"].update(invocationId="https://github.com/example/project/actions/runs/43/attempts/2"),
            lambda s: s["predicate"]["buildDefinition"]["internalParameters"]["github"].update(repository_owner_id="999"),
            lambda s: s["predicate"]["buildDefinition"]["internalParameters"]["github"].update(repository_id="999"),
            lambda s: s["predicate"]["buildDefinition"]["internalParameters"]["github"].update(event_name="pull_request"),
            lambda s: s["predicate"]["buildDefinition"]["externalParameters"]["workflow"].update(path="other.yaml"),
            lambda s: s["predicate"]["buildDefinition"]["externalParameters"]["workflow"].update(ref="refs/heads/feature"),
            lambda s: s["predicate"]["buildDefinition"]["resolvedDependencies"][0]["digest"].update(gitCommit="b" * 40),
            lambda s: s["subject"][0]["digest"].update(sha256="0" * 64),
        ]
        for mutate in mutations:
            gh = FakeGitHub()
            mutate(gh.statement)
            self.refused(gh)

    def test_failed_signature_never_writes(self):
        gh = FakeGitHub()
        gh.fail_verification = True
        self.refused(gh)

    def test_artifact_identity_expiry_inventory_and_digest(self):
        for key, value in [("expired", True), ("digest", "sha256:" + "0" * 64), ("size_in_bytes", p.LIMIT + 1)]:
            gh = FakeGitHub()
            gh.artifact[key] = value
            self.refused(gh)
        gh = FakeGitHub()
        gh.artifact["workflow_run"]["head_repository_id"] = 999
        self.refused(gh)
        for inventory in ([], ["duplicate"]):
            gh = FakeGitHub()
            gh.artifacts = [] if not inventory else [gh.artifact, gh.artifact]
            self.refused(gh)

    def test_zip_extra_traversal_and_symlink_rejected(self):
        for extra in ("unexpected.txt", "../escape", "subdir/poster.jpg"):
            gh = FakeGitHub()
            gh.files[extra] = b"unexpected"
            gh.pack()
            self.refused(gh)
        gh = FakeGitHub()
        gh.pack(symlink=p.VIDEO)
        self.refused(gh)

    def test_manifest_content_size_and_duplicate_outputs(self):
        for mutation in ("bytes", "sha256", "duplicate", "file"):
            gh = FakeGitHub()
            manifest = json.loads(gh.files[p.MANIFEST])
            if mutation == "duplicate":
                manifest["outputs"].append(manifest["outputs"][0])
            else:
                manifest["outputs"][0][mutation] = {"bytes": 0, "sha256": "0" * 64, "file": "missing"}[mutation]
            gh.files[p.MANIFEST] = json.dumps(manifest).encode()
            gh.pack()
            self.refused(gh)
        gh = FakeGitHub()
        gh.files["poster.jpg"] += b"corrupt"
        gh.pack()
        self.refused(gh)

    def test_stable_existing_release_only(self):
        for key, value in (("draft", True), ("prerelease", True), ("tag_name", "v99.0.0")):
            gh = FakeGitHub()
            gh.target[key] = value
            self.refused(gh)

    def test_all_collisions_checked_before_any_upload(self):
        for key, value in (("digest", "sha256:" + "0" * 64), ("digest", None), ("size", 0), ("state", "starter")):
            gh = FakeGitHub()
            asset = gh.asset(p.VIDEO)  # Sorted last: collision must precede every upload.
            asset[key] = value
            gh.assets = [asset]
            self.refused(gh)
        gh = FakeGitHub()
        gh.assets = [gh.asset(p.VIDEO), gh.asset(p.VIDEO)]
        self.refused(gh)

    def test_partial_failure_retry_uploads_only_missing_and_body_is_idempotent(self):
        gh = FakeGitHub()
        gh.fail_after = 3
        with self.assertRaises(ValueError):
            self.publish(gh)
        self.assertEqual(len(gh.uploads), 3)
        self.assertEqual(gh.patches, [])
        first = set(gh.uploads)
        gh.fail_after = None
        self.publish(gh)
        self.assertEqual(len(gh.uploads), 6)
        self.assertEqual(set(gh.uploads[3:]), p.FILES - first)
        self.publish(gh)
        self.assertEqual(len(gh.uploads), 6)
        self.assertEqual(len(gh.patches), 1)

    def test_bad_post_upload_digest_stops_and_does_not_edit_notes(self):
        gh = FakeGitHub()
        gh.bad_upload = True
        with self.assertRaises(ValueError):
            self.publish(gh)
        self.assertEqual(len(gh.uploads), 1)
        self.assertEqual(gh.patches, [])

    def test_existing_incompatible_preview_section_refused(self):
        for body in (p.MARKER, p.END_MARKER, p.MARKER + "different source" + p.END_MARKER):
            gh = FakeGitHub()
            gh.target["body"] += body
            self.refused(gh)

    def test_run_rerun_between_verification_and_write_refused(self):
        gh = FakeGitHub()
        original = gh.run

        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[:2] == ("attestation", "verify"):
                gh.source["status"] = "in_progress"
            return result

        gh.run = changing
        self.refused(gh)

    def test_display_metadata_changes_do_not_block_verified_publication(self):
        gh = FakeGitHub()
        original = gh.run

        def changing(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[:2] == ("attestation", "verify"):
                gh.repository.update(stargazers_count=10, description="Updated description",
                                     pushed_at="2026-11-10T12:00:00Z")
                gh.repository["owner"]["avatar_url"] = "https://example.com/new-avatar"
                gh.source.update(display_title="Updated display title", name="Updated workflow name",
                                 updated_at="2026-11-10T12:00:00Z")
                gh.source["repository"]["description"] = "Updated description"
                gh.source["head_repository"]["stargazers_count"] = 10
            return result

        gh.run = changing
        self.publish(gh)
        self.assertEqual(set(gh.uploads), p.FILES)
        self.assertEqual(len(gh.patches), 1)

    def test_identity_changes_after_verification_still_refused(self):
        for field in ("run_attempt", "head_sha", "owner_id"):
            with self.subTest(field=field):
                gh = FakeGitHub()
                original = gh.run

                def changing(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if args[:2] == ("attestation", "verify"):
                        if field == "owner_id":
                            gh.repository["owner"]["id"] = 999
                        else:
                            gh.source[field] = 3 if field == "run_attempt" else "b" * 40
                    return result

                gh.run = changing
                self.refused(gh)

    def test_actual_cli_wrapper_bounds_and_redacts_failures(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b'{"ok":true}', b"")) as run:
            self.assertEqual(p.GitHub().api("repos/example/project"), {"ok": True})
            self.assertEqual(run.call_args.args[0], ["gh", "api", "repos/example/project"])
            self.assertEqual(run.call_args.kwargs, {"check": True, "capture_output": True, "timeout": 120})
        with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "gh", stderr="credential secret")):
            with self.assertRaisesRegex(ValueError, "GitHub command failed") as error:
                p.GitHub().api("repos/example/project")
            self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
