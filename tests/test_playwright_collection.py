# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Playwright in the UI container sees only this directory, mounted at /app.

Node unit files stay here and run with `node --test`. They must not be part
of the browser collection, and every browser spec must still be listed.
"""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
NODE_UNITS = (
    "sso-fetch.test.mjs",
    "sso-trust-class.test.mjs",
    "test_tak_error_guard.mjs",
)


def pnpm(*args):
    # The UI job uses corepack. A checkout without it uses the same pnpm release.
    if shutil.which("corepack"):
        return ["corepack", "pnpm", *args]
    return ["npx", "--yes", "pnpm@12.18.0", *args]


class PlaywrightCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mount = Path(tempfile.mkdtemp(prefix="ui-mount-"))
        for path in TESTS.iterdir():
            if path.name in {"node_modules", ".playwright"}:
                continue
            dest = cls.mount / path.name
            if path.is_dir():
                shutil.copytree(path, dest)
            else:
                shutil.copy2(path, dest)
        subprocess.run(
            pnpm("install", "--frozen-lockfile"),
            cwd=cls.mount, check=True, capture_output=True, text=True, timeout=180,
            env={**os.environ, "CI": "true", "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"},
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.mount, ignore_errors=True)

    def listing(self, skip_sso):
        env = {**os.environ, "CI": "true"}
        if skip_sso:
            env["SKIP_SSO_SETUP"] = "1"
        else:
            env.pop("SKIP_SSO_SETUP", None)
        result = subprocess.run(
            pnpm("exec", "playwright", "test", "--list"),
            cwd=self.mount, check=True, capture_output=True, text=True, timeout=60, env=env,
        )
        return result.stdout

    def test_mounted_layout_lists_every_browser_spec_and_no_node_unit(self):
        specs = sorted(path.name for path in TESTS.glob("*.spec.ts"))
        self.assertGreaterEqual(len(specs), 9)
        listing = self.listing(skip_sso=False)
        for name in specs:
            self.assertIn(name, listing, listing)
        self.assertIn("auth.setup.ts", listing)
        for name in NODE_UNITS:
            self.assertNotIn(name, listing)
        self.assertNotIn(".test.mjs", listing)

    def test_skip_sso_keeps_browser_specs_and_drops_only_setup(self):
        listing = self.listing(skip_sso=True)
        for name in sorted(path.name for path in TESTS.glob("*.spec.ts")):
            self.assertIn(name, listing, listing)
        self.assertNotIn("auth.setup.ts", listing)
        self.assertNotIn(".test.mjs", listing)


if __name__ == "__main__":
    unittest.main()
