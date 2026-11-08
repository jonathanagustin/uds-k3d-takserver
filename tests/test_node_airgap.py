# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise node-only firewall isolation with actual Docker network traffic.

Build tests/fixtures/airgap/Dockerfile as tak-airgap-firewall-test, then set
AIRGAP_FIREWALL_INTEGRATION=1 to run the integration test. It uses two local
Docker networks, not an Internet server, so endpoint outages cannot pass it.
"""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("node_airgap", ROOT / ".github/scripts/node-airgap.py")
AIRGAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AIRGAP)


class AirgapContracts(unittest.TestCase):
    def test_unreachable_precontrol_fails_closed_and_reports_wget(self):
        failed = subprocess.CompletedProcess([], 1, "", "wget: download timed out\n")
        with patch.object(AIRGAP, "docker", return_value=failed) as command:
            with self.assertRaisesRegex(RuntimeError, r"k3d-node: external control unexpectedly failed \(exit 1: wget: download timed out\)"):
                AIRGAP.probe([{"name": "k3d-node"}], "http://1.1.1.1/cdn-cgi/trace", blocked=False)
        self.assertEqual(command.call_args.args[:3], ("exec", "k3d-node", "wget"))

    def test_a_denied_control_is_not_reported_as_a_precontrol_failure(self):
        failed = subprocess.CompletedProcess([], 1, "", "wget: connection refused")
        with patch.object(AIRGAP, "docker", return_value=failed):
            AIRGAP.probe([{"name": "k3d-node"}], "http://1.1.1.1/", blocked=True)

    def test_wget_diagnostics_are_bounded(self):
        failed = subprocess.CompletedProcess([], 4, "body", "x" * 500)
        with patch.object(AIRGAP, "docker", return_value=failed):
            with self.assertRaises(RuntimeError) as raised:
                AIRGAP.probe([{"name": "n"}], "http://8.8.8.8/", blocked=False)
        message = str(raised.exception)
        self.assertLess(len(message), 280)
        self.assertIn("...", message)
        self.assertNotIn("body", message)

    def test_precontrol_failure_does_not_install_the_firewall(self):
        failed = subprocess.CompletedProcess([], 1, "", "wget: download timed out")
        nodes = [{"name": "k3d-uds-server-0", "tools": ["iptables"], "networks": {"4": [], "6": []}}]
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with patch.object(AIRGAP, "discover", return_value=nodes), \
                    patch.object(AIRGAP, "docker", return_value=failed), \
                    patch.object(AIRGAP, "block_node") as block, \
                    patch("sys.argv", ["node-airgap.py", "block", "--state", str(state)]):
                with self.assertRaisesRegex(RuntimeError, "unexpectedly failed"):
                    AIRGAP.main()
            block.assert_not_called()
            self.assertFalse(state.exists())

    def test_external_control_requires_a_public_ip_literal(self):
        for url in ("http://localhost", "http://127.0.0.1", "http://172.18.0.1", "http://example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                AIRGAP.probe([], url, blocked=False)

    def test_host_and_shared_namespaces_are_refused_before_any_firewall_command(self):
        for mode in ("host", "container:other-container", "", None):
            for operation in (lambda: AIRGAP.block_node("tagged-node", "iptables", []),
                              lambda: AIRGAP.restore_node("tagged-node", "iptables")):
                with self.subTest(mode=mode), patch.object(AIRGAP, "docker") as command:
                    command.return_value = subprocess.CompletedProcess([], 0, json.dumps(mode), "")
                    with self.assertRaisesRegex(RuntimeError, "host/shared"):
                        operation()
                    self.assertEqual(command.call_count, 1)
                    self.assertEqual(command.call_args.args,
                                     ("inspect", "--format", "{{json .HostConfig.NetworkMode}}", "tagged-node"))

    def test_ci_always_restores_and_offline_ui_keeps_the_core_flow(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/test.yaml").read_text())
        job = workflow["jobs"]["validate-install"]
        self.assertEqual(sum(bool(row.get("airgap")) for row in job["strategy"]["matrix"]["include"]), 1)
        steps = {step.get("name"): step for step in job["steps"]}
        restore = steps["Restore airgap node egress"]
        self.assertIn("always()", restore["if"])
        self.assertIn("node-airgap.py restore", restore["run"])
        script = (ROOT / ".github/scripts/test-airgap.sh").read_text()
        self.assertIn("trap restore EXIT", script)
        self.assertLess(script.index('"${firewall[@]}" block'), script.index("uds run deploy:test-bundle"))
        self.assertIn("uds run test:all", script)
        self.assertIn('"${firewall[@]}" check', script)
        config = yaml.safe_load((ROOT / "bundle/airgap-config.yaml").read_text())
        self.assertIs(config["variables"]["takserver"]["CLOUDTAK_BASEMAP_ENABLED"], False)
        self.assertIn('-e AIRGAP_TEST="${AIRGAP_TEST:-false}"', (ROOT / "tasks/test.yaml").read_text())


@unittest.skipUnless(os.environ.get("AIRGAP_FIREWALL_INTEGRATION") == "1", "set AIRGAP_FIREWALL_INTEGRATION=1 for real Docker traffic")
class AirgapNetworkIntegration(unittest.TestCase):
    def test_ipv4_allow_deny_host_connection_and_restore(self):
        self.exercise(ipv6=False)

    @unittest.skipUnless(os.environ.get("AIRGAP_FIREWALL_IPV6") == "1", "set AIRGAP_FIREWALL_IPV6=1 on a host with IPv6 packet filtering")
    def test_ipv6_allow_deny_host_connection_and_restore(self):
        self.exercise(ipv6=True)

    def exercise(self, ipv6):
        tool = "ip6tables" if ipv6 else "iptables"
        tag = "tak-airgap-" + uuid.uuid4().hex[:8]
        image = os.environ.get("AIRGAP_FIXTURE_IMAGE", "tak-airgap-firewall-test")
        names = []
        networks = []
        node = tag + "-node"
        try:
            details = []
            for index, suffix in enumerate(("allowed", "denied"), 1):
                network = tag + "-" + suffix
                flags = ["--ipv6", "--subnet", f"fd42:{tag[-4:]}:{index}::/64"] if ipv6 else []
                AIRGAP.docker("network", "create", *flags, network)
                networks.append(network)
                info = json.loads(AIRGAP.docker("network", "inspect", network).stdout)[0]
                details.append(next(config["Subnet"] for config in info["IPAM"]["Config"]
                                    if (":" in config["Subnet"]) == ipv6))
                peer = tag + "-" + suffix + "-peer"
                AIRGAP.docker("run", "-d", "--name", peer, "--network", network, "-p", "127.0.0.1::8080", image,
                              "sh", "-c", "mkdir -p /tmp/www; echo reachable > /tmp/www/index.html; exec httpd -f -p 8080 -h /tmp/www")
                names.append(peer)
            AIRGAP.docker("run", "-d", "--name", node, "--cap-add", "NET_ADMIN", "--network", networks[0], image)
            names.append(node)
            AIRGAP.docker("network", "connect", networks[1], node)
            addresses = []
            for peer, network in zip(names[:2], networks):
                info = json.loads(AIRGAP.docker("inspect", peer).stdout)[0]
                addresses.append(info["NetworkSettings"]["Networks"][network]["GlobalIPv6Address" if ipv6 else "IPAddress"])

            def gets(address):
                target = f"[{address}]" if ipv6 else address
                return AIRGAP.docker("exec", node, "curl", "--noproxy", "*",
                                     "--fail", "--silent", "--show-error", "--connect-timeout", "2",
                                     f"http://{target}:8080", check=False)

            for address in addresses:
                result = gets(address)
                self.assertEqual(result.returncode, 0, result.stderr)
            allowed = [details[0], "fe80::/10", "ff02::/16"] if ipv6 else [details[0]]
            AIRGAP.block_node(node, tool, allowed)
            self.assertEqual(gets(addresses[0]).returncode, 0)
            self.assertNotEqual(gets(addresses[1]).returncode, 0)
            counters = AIRGAP.firewall(node, tool, "-L", AIRGAP.CHAIN, "-n", "-v", "-x").stdout
            rejected = [line.split() for line in counters.splitlines() if "REJECT" in line]
            self.assertTrue(any(int(fields[0]) > 0 for fields in rejected))
            # A host-side connection to the same denied peer still succeeds.
            # A published loopback port also works with rootless Docker, where
            # the agent host cannot route directly to the bridge's subnet.
            peer = json.loads(AIRGAP.docker("inspect", names[1]).stdout)[0]
            port = peer["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
            host = build_opener(ProxyHandler({}))
            self.assertEqual(host.open(f"http://127.0.0.1:{port}", timeout=3).read().strip(), b"reachable")
            AIRGAP.restore_node(node, tool)
            self.assertEqual(gets(addresses[1]).returncode, 0)
            # Cleanup is idempotent and never flushes another chain.
            AIRGAP.restore_node(node, tool)
        finally:
            if node in names:
                try:
                    AIRGAP.restore_node(node, tool)
                except subprocess.SubprocessError:
                    pass
            for name in reversed(names):
                AIRGAP.docker("rm", "-f", name, check=False)
            for network in networks:
                AIRGAP.docker("network", "rm", network, check=False)


if __name__ == "__main__":
    unittest.main()
