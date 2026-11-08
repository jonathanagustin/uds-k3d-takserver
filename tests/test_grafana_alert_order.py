# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""CloudTAK is scaled back up only after messaging is Ready."""

import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tests" / "grafana-alerts.sh"


class GrafanaAlertOrderTests(unittest.TestCase):
    def test_messaging_is_ready_before_cloudtak_returns(self):
        text = SCRIPT.read_text()
        start = text.index("are firing in Alertmanager")
        rest = text[start:]
        messaging = rest.index("rollout status deploy/takserver-messaging")
        cloudtak = rest.index("scale deploy/cloudtak -n cloudtak --replicas=1")
        self.assertLess(messaging, cloudtak)
