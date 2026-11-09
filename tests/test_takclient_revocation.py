# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("revocation", Path(__file__).with_name("takclient-revocation.py"))
revocation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revocation)


class ActiveEndpointsTests(unittest.TestCase):
    def test_real_api_envelope_uses_active_filter_and_fresh_admin_tls(self):
        ctx = MagicMock()
        api = ctx.wrap_socket.return_value.__enter__.return_value
        # The default API includes these disconnected historical rows. The
        # active query excludes them server-side; it must not delete history.
        history = {"version": "3", "type": "com.bbn.marti.remote.ClientEndpoint", "data": [
            {"callsign": "revoked", "uid": "revoked", "lastStatus": "Disconnected"},
        ]}
        active = {**history, "data": []}
        with patch.object(revocation.socket, "create_connection") as connect, \
                patch.object(revocation.http.client, "HTTPResponse") as response:
            response.return_value.status = 200
            response.return_value.read.return_value = json.dumps(active).encode()
            for _ in range(2):
                self.assertEqual(revocation.active_endpoints(ctx, 443, "uds.dev"), [])
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(ctx.wrap_socket.call_count, 2)
            request = api.sendall.call_args.args[0]
            self.assertIn(b"GET /Marti/api/clientEndPoints?showCurrentlyConnectedClients=true HTTP/1.1", request)
            self.assertEqual(history["data"][0]["lastStatus"], "Disconnected")

    def test_admin_rejection_is_immediate(self):
        with patch.object(revocation.socket, "create_connection"), \
                patch.object(revocation.http.client, "HTTPResponse") as response:
            response.return_value.status = 403
            with self.assertRaisesRegex(AssertionError, "admin certificate"):
                revocation.active_endpoints(MagicMock(), 443, "uds.dev")
            response.return_value.read.assert_not_called()

    def test_malformed_identity_fails_closed_and_optional_callsign_may_be_null(self):
        ctx = MagicMock()
        with patch.object(revocation.socket, "create_connection"), \
                patch.object(revocation.http.client, "HTTPResponse") as response:
            response.return_value.status = 200
            for row in ({}, {"unknown": "revoked"}, {"uid": None}, {"uid": 7},
                        {"uid": ""}, {"uid": "revoked", "callsign": 7}):
                with self.subTest(row=row):
                    response.return_value.read.return_value = json.dumps({"data": [row]}).encode()
                    with self.assertRaisesRegex(AssertionError, "invalid active endpoint identity"):
                        revocation.active_endpoints(ctx, 443, "uds.dev")
            response.return_value.read.return_value = json.dumps({"data": [{"uid": "control", "callsign": None}]}).encode()
            self.assertEqual(revocation.active_endpoints(ctx, 443, "uds.dev"), [{"uid": "control", "callsign": None}])

    def test_cached_active_entry_expires_and_controls_checked_each_poll(self):
        now = [0]
        fetch = MagicMock(side_effect=[[{"callsign": "revoked", "lastStatus": "Connected"}]] * 5 + [[]])
        controls = MagicMock()
        revocation.wait_for_revoked_endpoint("revoked", fetch, controls,
            clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(now[0], 5)
        self.assertEqual(controls.call_count, 6)

    def test_persistent_active_entry_fails_at_deadline(self):
        now = [0]
        with self.assertRaisesRegex(AssertionError, "after 30 seconds"):
            revocation.wait_for_revoked_endpoint("revoked", lambda: [{"uid": "revoked"}], lambda: None,
                clock=lambda: now[0], sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        self.assertEqual(now[0], 30)

    def test_poll_does_not_mask_admin_or_control_failure(self):
        for failure in (AssertionError("admin certificate no longer authenticates"), OSError("TLS failed")):
            fetch = MagicMock(side_effect=failure)
            with self.assertRaises(type(failure)):
                revocation.wait_for_revoked_endpoint("revoked", fetch, lambda: None)
            self.assertEqual(fetch.call_count, 1)
        fetch = MagicMock()
        with self.assertRaisesRegex(AssertionError, "control closed"):
            revocation.wait_for_revoked_endpoint("revoked", fetch,
                MagicMock(side_effect=AssertionError("control closed")))
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
