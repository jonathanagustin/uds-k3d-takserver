# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Queue contracts and real build-script registry reuse, without hosted builds."""
import concurrent.futures
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ProducerQueues(unittest.TestCase):
    def test_atak_filters_include_every_hosted_scenario_runtime_input(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/atak-e2e.yaml').read_text())
        events = workflow.get('on', workflow.get(True))
        runtime = ['atak/scenarios/android-interoperability.py', 'atak/scenarios/observe-peer.py', 'atak/scenarios/android-ui.py', 'atak/scenarios/radial-details.py', 'atak/scenarios/details-icon.json', 'takx/mission-package/build_fixture.py', 'takx/mission-package/fixtures.lock.json', 'takx/mission-package/fixtures/manifest.xml', 'takx/mission-package/fixtures/point.cot', 'takx/mission-package/fixtures/README.txt']
        expected = ['atak/**', '!atak/scenarios/**', *runtime, 'demo/atak-adb.sh', '.github/workflows/atak-e2e.yaml']
        for event in ('pull_request', 'push'):
            patterns = events[event]['paths']
            self.assertEqual(patterns, expected)
            def included(path):
                answer = False
                for pattern in patterns:
                    if fnmatch.fnmatchcase(path, pattern.lstrip('!')):
                        answer = not pattern.startswith('!')
                return answer
            self.assertFalse(included('atak/scenarios/README.md'))
            self.assertFalse(included('atak/scenarios/fixtures/atak-marker-radial.json'))
            for path in [*runtime, 'demo/atak-adb.sh', 'atak/ci/e2e.sh', 'atak/ci/interoperability.py', 'atak/ci/reverse-marker.py', 'atak/ci/cleanup-scenario.py', 'atak/ci/interoperability.sh', 'atak/driver/drive.sh', 'atak/vm/Dockerfile', 'atak/apk/Dockerfile', 'atak/deploy/device.yaml', '.github/workflows/atak-e2e.yaml']:
                with self.subTest(event=event, path=path): self.assertTrue(included(path))
        self.assertIn('workflow_dispatch', events)
        step = next(step for step in workflow['jobs']['e2e']['steps'] if step.get('name') == 'ATAK device end to end')
        self.assertEqual(step['env']['ATAK_INTEROP_SCENARIO'], 'true')
        script = (ROOT / 'atak/ci/e2e.sh').read_text()
        self.assertIn('${ATAK_INTEROP_SCENARIO:-false}', script)
        self.assertIn('timeout --signal=TERM --kill-after=5s 475s ./atak/ci/interoperability.sh', script)

    def test_optional_apk_producers_share_a_queue_and_recheck_after_admission(self):
        standalone = yaml.safe_load((ROOT / ".github/workflows/atak.yaml").read_text())["jobs"]["apk"]
        device = yaml.safe_load((ROOT / ".github/workflows/atak-e2e.yaml").read_text())["jobs"]["images"]
        self.assertEqual(standalone["concurrency"], device["concurrency"])
        queue = standalone["concurrency"]
        self.assertEqual(queue["group"], "atak-apk-producer")
        self.assertIs(queue["cancel-in-progress"], False)
        self.assertEqual(queue["queue"], "max")
        self.assertTrue(any("imagetools inspect" in step.get("run", "")
                            for step in standalone["steps"]))
        self.assertTrue(any("device-images.sh missing" in step.get("run", "")
                            for step in device["steps"]))

    def test_immutable_apk_producers_are_outside_workflow_cancellation(self):
        workflows = {name: yaml.safe_load((ROOT / f".github/workflows/{name}.yaml").read_text())
                     for name in ("atak", "atak-e2e")}
        for name, workflow in workflows.items():
            with self.subTest(workflow=name):
                self.assertNotIn("concurrency", workflow,
                                 "A workflow cancellation can kill a productive immutable APK producer")
        consumer = workflows["atak-e2e"]["jobs"]["e2e"]["concurrency"]
        self.assertEqual(consumer["cancel-in-progress"],
                         "${{ github.event_name == 'pull_request' || github.event_name == 'push' }}")
        self.assertEqual(consumer["group"],
                         "${{ github.workflow }}-${{ github.event_name }}-"
                         "${{ github.event.pull_request.number || github.ref }}-"
                         "${{ (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch') "
                         "&& github.run_id || 'gate' }}-consumer")
        self.assertNotEqual(consumer["group"],
                            workflows["atak-e2e"]["jobs"]["images"]["concurrency"]["group"])

    def test_same_key_and_arch_share_fifo_groups_across_workflows(self):
        workflows = {name: yaml.safe_load((ROOT / f".github/workflows/{name}.yaml").read_text())
                     for name in ["test", "cloudtak-image", "postgis-image"]}
        for image in ["cloudtak", "postgis"]:
            for test_job, dedicated_job in [(f"{image}-image", "build"), (f"{image}-index", "index")]:
                first = workflows["test"]["jobs"][test_job]
                second = workflows[f"{image}-image"]["jobs"][dedicated_job]
                self.assertEqual(first["concurrency"], second["concurrency"])
                queue = first["concurrency"]
                self.assertEqual(set(queue), {"group", "queue", "cancel-in-progress"})
                self.assertEqual(queue["queue"], "max")
                self.assertIs(queue["cancel-in-progress"], False)
                self.assertIn(f"needs.image-keys.outputs.{image}", queue["group"])
                self.assertIn("image-keys", first["needs"])
                self.assertIn("image-keys", second["needs"])
                if dedicated_job == "build":
                    self.assertIn("matrix.arch", queue["group"])
                else:
                    self.assertTrue(queue["group"].endswith("-index"))
            # Reuse, PostGIS smoke and attestations still execute after admission.
            dedicated = workflows[f"{image}-image"]["jobs"]["build"]
            self.assertTrue(any("--if-changed" in step.get("run", "") for step in dedicated["steps"]))
            self.assertTrue(any(step.get("uses") == "./.github/actions/attest-images" for step in dedicated["steps"]))
        self.assertTrue(any("/postgis/smoke.sh" in step.get("run", "")
                            for step in workflows["postgis-image"]["jobs"]["build"]["steps"]))

    def test_actionlint_exception_only_accepts_the_supported_queue_key(self):
        config = yaml.safe_load((ROOT / ".github/actionlint.yaml").read_text())
        diagnostic = 'unexpected key "queue" for "concurrency" section. expected one of "cancel-in-progress", "group"'
        for name in ["test", "cloudtak-image", "postgis-image", "atak", "atak-e2e"]:
            patterns = config["paths"][f".github/workflows/{name}.yaml"]["ignore"]
            self.assertEqual(len(patterns), 1)
            self.assertIsNotNone(re.fullmatch(patterns[0], diagnostic))
            self.assertIsNone(re.fullmatch(patterns[0], diagnostic.replace('"queue"', '"quue"')))
            self.assertIsNone(re.fullmatch(patterns[0], diagnostic.replace('"concurrency"', '"permissions"')))


class RealBuildReuse(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        directory = self.root / ".github/container-and-chart/postgis"
        directory.mkdir(parents=True)
        self.script = directory / "build.sh"
        shutil.copy(ROOT / ".github/container-and-chart/postgis/build.sh", self.script)
        copa = self.root / ".github/scripts/copa-patch.sh"
        copa.parent.mkdir(parents=True)
        copa.write_text("#!/usr/bin/env bash\nexit 0\n")
        copa.chmod(0o755)
        for command in [["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.test",
                         "commit", "-qm", "fixture"]]:
            subprocess.run(command, cwd=self.root, check=True)
        binary = self.root / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["REGISTRY_FIXTURE"])
args = sys.argv[1:]
state = root / "published.json"
if args[:3] == ["buildx", "imagetools", "inspect"]:
    published = json.loads(state.read_text()) if state.exists() else {}
    if args[3] not in published:
        sys.exit(1)
    print(json.dumps(published[args[3]]))
elif args[:2] == ["buildx", "build"]:
    with (root / "builds").open("a") as target:
        target.write("build\\n")
    if (root / "fail").exists():
        sys.exit(19)
    inputs = next(value.split("=", 1)[1] for value in args if value.startswith("INPUTS="))
    arch = args[args.index("--platform") + 1].split("/")[1]
    image = args[args.index("--tag") + 1]
    time.sleep(0.05)
    (root / "loaded.json").write_text(json.dumps({image: {"os": "linux", "architecture": arch,
        "config": {"Labels": {"dev.uds-takserver.inputs": inputs}}}}))
elif args[0] == "push":
    state.write_text((root / "loaded.json").read_text())
else:
    raise SystemExit("unexpected fixture docker command: " + str(args))
''')
        docker.chmod(0o755)
        self.environment = {**os.environ, "PATH": f"{binary}:{os.environ['PATH']}",
                            "REGISTRY_FIXTURE": str(self.root), "PUSH_IMAGES": "true", "ARCH": "amd64",
                            "GITHUB_REF": "refs/pull/1/merge", "WRITE_VERSION_TAG": "false"}

    def producer(self):
        # Fixture admission represents the documented hosted concurrency mutex.
        # The test exercises the real script after admission, not the scheduler.
        with (self.root / "admission").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return subprocess.run(["bash", str(self.script), "--if-changed"], env=self.environment,
                                  cwd=self.root, text=True, capture_output=True, timeout=10)

    def test_simultaneous_admitted_consumers_recheck_and_compile_once(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.producer(), range(4)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["build"])
        self.assertEqual(sum("already has inputs" in result.stdout for result in results), 3)

    def test_failed_producer_releases_admission_and_next_producer_builds(self):
        (self.root / "fail").touch()
        self.assertNotEqual(self.producer().returncode, 0)
        self.assertFalse((self.root / "published.json").exists())
        (self.root / "fail").unlink()
        self.assertEqual(self.producer().returncode, 0)
        self.assertEqual(self.producer().returncode, 0)
        self.assertEqual(len((self.root / "builds").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
