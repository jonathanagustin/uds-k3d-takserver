# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Execute image pinning in a real checkout; never change the source checkout."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ImageTagPinning(unittest.TestCase):
    def test_every_bundle_uses_the_tak_tag_packaged_by_ci(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT), str(root)], check=True)
            # Exercise the current script, including uncommitted changes.
            shutil.copy(ROOT / ".github/scripts/pin-image-tags.sh", root / ".github/scripts/pin-image-tags.sh")
            tag = subprocess.check_output(
                ["bash", ".github/container-and-chart/docker/build.sh", "--tag"], cwd=root, text=True,
            ).strip()
            subprocess.run(["bash", ".github/scripts/pin-image-tags.sh"], cwd=root, check=True,
                           capture_output=True, text=True, timeout=30)
            package = yaml.safe_load((root / "zarf.yaml").read_text())
            variables = {variable["name"]: variable for variable in package["variables"]}
            self.assertEqual(variables["TAK_IMAGE_TAG"]["default"], tag)
            images = [image for component in package["components"] for image in component.get("images", [])
                      if "/takserver-" in image]
            self.assertEqual(len(images), 6)
            self.assertTrue(all(image.endswith(":" + tag) for image in images))
            configs = [path for path in (root / "bundle").rglob("*.yaml") if "TAK_IMAGE_TAG:" in path.read_text()]
            self.assertIn(root / "bundle/airgap-config.yaml", configs)
            for config in configs:
                with self.subTest(config=str(config.relative_to(root))):
                    data = yaml.safe_load(config.read_text())
                    self.assertEqual(data["variables"]["takserver"]["TAK_IMAGE_TAG"], tag)
            self.assertIs(yaml.safe_load((root / "bundle/airgap-config.yaml").read_text())
                          ["variables"]["takserver"]["CLOUDTAK_BASEMAP_ENABLED"], False)


if __name__ == "__main__":
    unittest.main()
