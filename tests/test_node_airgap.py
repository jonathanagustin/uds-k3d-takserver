# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Exercise node-only firewall isolation with actual Docker network traffic.

Build tests/fixtures/airgap/Dockerfile as tak-airgap-firewall-test, then set
AIRGAP_FIREWALL_INTEGRATION=1 to run the integration test. It uses two local
Docker networks, not an Internet server, so endpoint outages cannot pass it.
"""

import importlib.util
import contextlib
import io
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

# Ordinary Test events keep this producer output. A trust-only manual trial
# may omit the airgap row, but only through the same function.
INSTALL_MATRIX_EXPRESSION = "${{ fromJSON(needs.check-flavor.outputs.install-matrix) }}"


def airgap_rows(rows):
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        raise AssertionError("install matrix rows must be mappings")
    return [row for row in rows if row.get("airgap")]


def resolve_install_matrices(workflow, root):
    """Return the install rows a workflow will actually run.

    A static include list is used as written. The fromJSON expression is
    executed through test-validation-mode.py; a bare string is not a matrix.
    """
    matrix = workflow["jobs"]["validate-install"]["strategy"]["matrix"]
    if isinstance(matrix, dict):
        include = matrix.get("include")
        if isinstance(include, str):
            raise AssertionError("install matrix include is an expression; resolve its producer")
        return {"ordinary": include}
    if not isinstance(matrix, str) or matrix.strip() != INSTALL_MATRIX_EXPRESSION:
        raise AssertionError("dynamic install matrix must be fromJSON(needs.check-flavor.outputs.install-matrix)")
    producer = Path(root) / ".github/scripts/test-validation-mode.py"
    if not producer.is_file():
        raise AssertionError(f"missing install-matrix producer: {producer}")
    spec = importlib.util.spec_from_file_location(f"validation_mode_{producer.stat().st_mtime_ns}", producer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "install_matrix", None)):
        raise AssertionError("install-matrix producer must define install_matrix")
    runner = "ubuntu-26.04"
    return {
        "ordinary": module.install_matrix("pull_request", "false", runner)["include"],
        "push": module.install_matrix("push", "false", runner)["include"],
        "dispatch": module.install_matrix("workflow_dispatch", "false", runner)["include"],
        "trust": module.install_matrix("workflow_dispatch", "true", runner)["include"],
    }


def assert_native_plus_one_airgap(test, rows):
    selected = airgap_rows(rows)
    test.assertEqual(len(selected), 1)
    native = [row for row in rows if not row.get("airgap")]
    test.assertEqual([row["arch"] for row in native], ["amd64", "arm64"])
    test.assertEqual(selected[0]["arch"], "amd64")
    test.assertEqual(selected[0]["runner"], native[0]["runner"])


class AirgapContracts(unittest.TestCase):
    def test_drop_denial_preserves_docker_dns_and_internal_rule_order(self):
        with patch.object(AIRGAP, 'require_private_network') as private, \
                patch.object(AIRGAP, 'firewall') as command:
            AIRGAP.block_node('k3d-node', 'iptables', ['172.18.0.0/16', '10.42.0.0/16'])
        private.assert_called_once_with('k3d-node')
        self.assertEqual([call.args[2:] for call in command.call_args_list], [
            ('-N', AIRGAP.CHAIN),
            ('-A', AIRGAP.CHAIN, '-d', '127.0.0.11/32', '-j', 'DROP'),
            ('-A', AIRGAP.CHAIN, '-o', 'lo', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-d', '172.18.0.0/16', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-d', '10.42.0.0/16', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-j', 'DROP'),
            ('-I', 'OUTPUT', '1', '-j', AIRGAP.CHAIN),
            ('-I', 'FORWARD', '1', '-j', AIRGAP.CHAIN)])
        with patch.object(AIRGAP, 'require_private_network'), patch.object(AIRGAP, 'firewall') as command:
            AIRGAP.block_node('k3d-node', 'ip6tables', ['fe80::/10'])
        self.assertEqual(command.call_args_list[1].args[2:],
                         ('-A', AIRGAP.CHAIN, '-o', 'lo', '-j', 'RETURN'))
        self.assertIn(('-A', AIRGAP.CHAIN, '-j', 'DROP'),
                      [call.args[2:] for call in command.call_args_list])
        self.assertFalse(any('REJECT' in call.args for call in command.call_args_list))

    def test_firewall_failure_reports_sanitized_stderr_and_still_raises(self):
        error = subprocess.CalledProcessError(1, ['docker', 'exec'], stderr=
                                               'iptables v1.8.11: lock timeout; password=DO_NOT_EMIT\n')
        output = io.StringIO()
        with patch.object(AIRGAP, 'docker', side_effect=error), contextlib.redirect_stderr(output):
            with self.assertRaises(subprocess.CalledProcessError):
                AIRGAP.firewall('k3d-node', 'iptables', '-A', AIRGAP.CHAIN, '-j', 'DROP')
        self.assertIn('iptables v1.8.11: lock timeout', output.getvalue())
        self.assertNotIn('DO_NOT_EMIT', output.getvalue())
        self.assertIn('[REDACTED]', output.getvalue())

    def test_firewall_stderr_is_redacted_before_truncation_and_auth_is_omitted_whole(self):
        detail = AIRGAP.firewall_error_detail('-----BEGIN PRIVATE KEY-----\n' +
                                              'sensitive' * 500 + '\n-----END PRIVATE KEY-----\nbackend error')
        self.assertNotIn('sensitive', detail)
        self.assertIn('backend error', detail)
        self.assertLessEqual(len(detail), 1024)
        detail = AIRGAP.firewall_error_detail('public-prefix ' * 200 +
                                              '{"auths":{"registry":{"auth":"DO_NOT_EMIT"}}}')
        self.assertEqual(detail, 'omitted: authentication-bearing firewall stderr')
        self.assertEqual(AIRGAP.firewall_error_detail('upload failed http://registry/v2/blobs?_state=DO_NOT_EMIT'),
                         'omitted: authentication-bearing firewall stderr')
        self.assertEqual(AIRGAP.firewall_error_detail(b'\xffprivate'),
                         'omitted: unsanitizable firewall stderr')
        self.assertEqual(AIRGAP.firewall_error_detail('x' * 65537),
                         'omitted: oversized firewall stderr')

    def test_unreachable_precontrol_fails_closed_and_reports_wget(self):
        failed = subprocess.CompletedProcess([], 1, "", "wget: download timed out\n")
        with patch.object(AIRGAP, "docker", return_value=failed) as command:
            with self.assertRaisesRegex(RuntimeError, r"k3d-node: external control unexpectedly failed \(exit 1: wget: download timed out\)"):
                AIRGAP.probe([{"name": "k3d-node"}], "http://1.1.1.1/cdn-cgi/trace", blocked=False)
        self.assertEqual(command.call_args.args[:3], ("exec", "k3d-node", "wget"))

    def test_http_responses_prove_egress_even_when_transfer_fails(self):
        for status in ["HTTP/1.1 301 Moved Permanently", "HTTP/2 403 Forbidden", "HTTP/1.0 500 Server Error"]:
            response = subprocess.CompletedProcess([], 1, "", f"  {status}\nwget: TLS error")
            with self.subTest(status=status), patch.object(AIRGAP, "docker", return_value=response) as command:
                AIRGAP.probe([{"name": "node"}], "http://1.1.1.1/", blocked=False)
                with self.assertRaisesRegex(RuntimeError, "unexpectedly succeeded"):
                    AIRGAP.probe([{"name": "node"}], "http://1.1.1.1/", blocked=True)
                self.assertIn("-S", command.call_args.args)
                self.assertEqual(command.call_args.args[3:5], ("-Y", "off"))

    def test_diagnostic_text_without_a_status_line_is_not_a_response(self):
        result = subprocess.CompletedProcess([], 1, "", "wget: HTTP/1.1 TLS failed")
        with patch.object(AIRGAP, "docker", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "unexpectedly failed"):
                AIRGAP.probe([{"name": "node"}], "http://1.1.1.1/", blocked=False)

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

    def test_restore_does_not_request_dns_lookups_for_either_family(self):
        for tool in ("iptables", "ip6tables"):
            def result(_node, _tool, *args, **_kwargs):
                return subprocess.CompletedProcess([], 1 if "-C" in args else 0, "", "")
            with self.subTest(tool=tool), patch.object(AIRGAP, "require_private_network"), \
                    patch.object(AIRGAP, "firewall", side_effect=result) as command:
                AIRGAP.restore_node("node", tool)
                listings = [call.args for call in command.call_args_list if "-L" in call.args]
                self.assertEqual(listings, [("node", tool, "-L", AIRGAP.CHAIN, "-n")])

    def test_ci_always_restores_and_offline_ui_keeps_the_core_flow(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/test.yaml").read_text())
        job = workflow["jobs"]["validate-install"]
        resolved = resolve_install_matrices(workflow, ROOT)
        assert_native_plus_one_airgap(self, resolved["ordinary"])
        for name in ("push", "dispatch"):
            if name in resolved:
                assert_native_plus_one_airgap(self, resolved[name])
        if "trust" in resolved:
            self.assertEqual(airgap_rows(resolved["trust"]), [])
            self.assertEqual([row["arch"] for row in resolved["trust"]], ["amd64", "arm64"])
        self.assertIn("matrix.airgap", job["env"]["AIRGAP_TEST"])
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

    def test_dynamic_matrix_keeps_ordinary_airgap_and_trust_trial_omits_it(self):
        producer = '''
def install_matrix(event, requested, amd64_runner):
    include = [{"arch": "amd64", "runner": amd64_runner},
               {"arch": "arm64", "runner": "ubuntu-26.04-arm"}]
    if not (event == "workflow_dispatch" and requested == "true"):
        include.append({"arch": "amd64", "runner": amd64_runner, "airgap": True})
    return {"include": include}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / ".github/scripts/test-validation-mode.py"
            script.parent.mkdir(parents=True)
            script.write_text(producer)
            workflow = {"jobs": {"validate-install": {"strategy": {"matrix": INSTALL_MATRIX_EXPRESSION}}}}
            resolved = resolve_install_matrices(workflow, root)
        for name in ("ordinary", "push", "dispatch"):
            assert_native_plus_one_airgap(self, resolved[name])
        self.assertEqual(airgap_rows(resolved["trust"]), [])
        self.assertEqual([row["arch"] for row in resolved["trust"]], ["amd64", "arm64"])

    def test_unresolved_matrix_text_fails_closed(self):
        for matrix in (
            "${{ fromJSON(needs.other.outputs.matrix) }}",
            {"include": INSTALL_MATRIX_EXPRESSION},
            "include",
        ):
            workflow = {"jobs": {"validate-install": {"strategy": {"matrix": matrix}}}}
            with self.subTest(matrix=matrix), self.assertRaises(AssertionError):
                resolve_install_matrices(workflow, ROOT)


@unittest.skipUnless(os.environ.get("AIRGAP_CLEANUP_INTEGRATION") == "1", "set AIRGAP_CLEANUP_INTEGRATION=1 for real DNS-blocked cleanup")
class AirgapCleanupIntegration(unittest.TestCase):
    def test_numeric_cleanup_finishes_with_unresponsive_dns(self):
        name = f"airgap-cleanup-{uuid.uuid4().hex[:10]}"
        try:
            AIRGAP.docker("run", "-d", "--network", "none", "--cap-add", "NET_ADMIN", "--name", name,
                          os.environ.get("AIRGAP_FIREWALL_IMAGE", "tak-airgap-firewall-test:latest"),
                          "sh", "-c", "nc -u -l -p 53 >/dev/null & exec sleep infinity")
            # All mutations are inside this disposable private network namespace.
            AIRGAP.docker("exec", name, "sh", "-c",
                          'printf "nameserver 127.0.0.1\\noptions timeout:1 attempts:1\\n" > /etc/resolv.conf')
            AIRGAP.firewall(name, "iptables", "-N", AIRGAP.CHAIN)
            for address in ("10.43.0.1", "10.43.0.2", "10.43.0.3", "10.43.0.4"):
                AIRGAP.firewall(name, "iptables", "-A", AIRGAP.CHAIN, "-d", address, "-j", "RETURN")
            # Bound the old behavior inside the container so its process is
            # terminated too; no hanging child remains after the comparison.
            old = AIRGAP.docker("exec", name, "timeout", "-s", "KILL", "2", "iptables", "-w", "5",
                                "-L", AIRGAP.CHAIN, check=False)
            self.assertEqual(old.returncode, 137, old.stderr)
            numeric = AIRGAP.firewall(name, "iptables", "-L", AIRGAP.CHAIN, "-n")
            self.assertIn("10.43.0.1", numeric.stdout)
            AIRGAP.restore_node(name, "iptables")
            self.assertEqual(AIRGAP.firewall(name, "iptables", "-L", AIRGAP.CHAIN, "-n", check=False).returncode, 1)
            AIRGAP.restore_node(name, "iptables")
        finally:
            AIRGAP.docker("rm", "-f", name, check=False)


@unittest.skipUnless(os.environ.get("AIRGAP_WGET_INTEGRATION") == "1", "set AIRGAP_WGET_INTEGRATION=1 for real BusyBox wget")
class AirgapWgetIntegration(unittest.TestCase):
    def test_redirect_proves_reachability_but_initial_refusal_does_not(self):
        # Isolated loopback traffic only: no public endpoint or firewall mutation.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cgi-bin").mkdir()
            redirect = root / "cgi-bin/redirect"
            redirect.write_text('#!/bin/sh\nprintf "Status: 301 Moved Permanently\\r\\nLocation: https://127.0.0.1:1/\\r\\n\\r\\n"\n')
            redirect.chmod(0o755)
            name = f"airgap-wget-{uuid.uuid4().hex[:10]}"
            docker = AIRGAP.docker
            try:
                docker("run", "-d", "--network", "none", "--name", name,
                       "--mount", f"type=bind,src={root},dst=/www,readonly",
                       os.environ.get("AIRGAP_FIREWALL_IMAGE", "tak-airgap-firewall-test:latest"),
                       "httpd", "-f", "-p", "8080", "-h", "/www")
                results = []

                def actual_wget(*args, **kwargs):
                    # Map the public literal to the isolated fixture; preserve
                    # the production wget arguments and all classification.
                    fixture_url = "http://127.0.0.1:8080/cgi-bin/redirect" if redirect.exists() else "http://127.0.0.1:1/"
                    result = docker("exec", "-e", "http_proxy=http://127.0.0.1:1",
                                    "-e", "https_proxy=http://127.0.0.1:1",
                                    name, *args[2:-1], fixture_url, **kwargs)
                    results.append(result)
                    return result

                with patch.object(AIRGAP, "docker", side_effect=actual_wget):
                    AIRGAP.probe([{"name": name}], "http://1.1.1.1/", blocked=False)
                    self.assertNotEqual(results[-1].returncode, 0)
                    self.assertIn("HTTP/1.1 301", results[-1].stderr)
                    self.assertIn("Connection refused", results[-1].stderr)
                    # A redirect cannot count as successful isolation.
                    with self.assertRaisesRegex(RuntimeError, "unexpectedly succeeded"):
                        AIRGAP.probe([{"name": name}], "http://1.1.1.1/", blocked=True)
                    redirect.unlink()
                    with self.assertRaisesRegex(RuntimeError, "unexpectedly failed"):
                        AIRGAP.probe([{"name": name}], "http://1.1.1.1/", blocked=False)
                    self.assertNotIn("HTTP/", results[-1].stderr)
                    AIRGAP.probe([{"name": name}], "http://1.1.1.1/", blocked=True)
            finally:
                docker("rm", "-f", name, check=False)


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
            dropped = [line.split() for line in counters.splitlines() if "DROP" in line]
            self.assertTrue(any(int(fields[0]) > 0 for fields in dropped))
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
