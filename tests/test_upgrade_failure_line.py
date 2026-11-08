# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The upgrade script names its failing line without copying the command."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPGRADE = ROOT / "tests" / "upgrade.sh"


class UpgradeFailureLineTests(unittest.TestCase):
    def test_err_trap_reports_the_line_and_not_the_command(self):
        text = UPGRADE.read_text()
        self.assertIn('msg="upgrade.sh exited ${rc} at line ${line}"', text)
        self.assertIn("::error title=Upgrade script failed::", text)
        self.assertIn('trap \'upgrade_failed "$?" "${LINENO}"\' ERR', text)
        self.assertNotIn("BASH_COMMAND", text)
        trap = next(line for line in text.splitlines() if line.startswith("trap "))
        self.assertLess(text.splitlines().index(trap), 25)
