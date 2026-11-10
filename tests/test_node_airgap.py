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
import http.server
import json
import os
from pathlib import Path
import subprocess
import shutil
import socket
import tempfile
import time
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("node_airgap", ROOT / ".github/scripts/node-airgap.py")
AIRGAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AIRGAP)


def binding(family="iptables", backend="legacy"):
    return dict(family=family, backend=backend, path="/bin/xtables-" + backend + "-multi",
                version="1.8.11", cid="a" * 64)

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
    def test_real_process_generic_flip_does_not_change_bound_mutations_or_restore(self):
        # This executable is a protocol fixture, not Docker or a firewall.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "docker"
            fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ["AIRGAP_FIXTURE_ROOT"])
a = sys.argv[1:]
with (root / "calls").open("a") as stream: stream.write(json.dumps(a) + "\\n")
c = a[6:]  # exec CID timeout -s KILL 3 COMMAND...
if c[0] == "which": print("/bin/" + c[1])
elif c[0] == "readlink": print(c[-1])
elif c[0] == "test": pass
elif "--version" in c:
    family = c[1] if c[0].startswith("/") else c[0]
    mode = "legacy" if c[0].startswith("/") or not (root / "flipped").exists() else "nf_tables"
    print(f"{family} v1.8.11 ({mode})")
else:
    if "-N" in c: (root / "flipped").touch()
    if "-C" in c: sys.exit(1)
''')
            fake.chmod(0o755)
            with patch.dict(os.environ, {"PATH": str(root) + os.pathsep + os.environ["PATH"],
                                         "AIRGAP_FIXTURE_ROOT": str(root)}):
                selected = AIRGAP.select_backend("a" * 64, "iptables")
                with patch.object(AIRGAP, "require_binding_node"):
                    AIRGAP.block_node("node", selected, ["10.42.0.0/16"])
                    AIRGAP.restore_node("node", json.loads(json.dumps(selected)))
                generic = AIRGAP.bounded_exec("a" * 64, ["iptables", "--version"], AIRGAP.time.monotonic() + 5)
            self.assertIn("nf_tables", generic.stdout)
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            mutations = [a for a in calls if any(flag in a for flag in ("-N", "-A", "-I", "-F", "-X"))]
            self.assertGreater(len(mutations), 6)
            for args in mutations:
                self.assertEqual(args[:2], ["exec", "a" * 64])
                self.assertEqual(args[6:8], ["/bin/xtables-legacy-multi", "iptables"])
            self.assertTrue(any("127.0.0.11/32" in a for a in mutations))

    def test_source_packaged_aux_and_extracted_data_paths_are_supported(self):
        for path in ("/bin/aux/xtables-legacy-multi", "/var/lib/rancher/k3s/data/" + "a" * 64 +
                     "/bin/aux/xtables-legacy-multi"):
            self.assertEqual(AIRGAP.validate_binding(dict(binding(), path=path))["path"], path)

    def test_unknown_mismatched_backend_and_unsafe_paths_fail_before_mutation(self):
        good = subprocess.CompletedProcess([], 0, "iptables v1.8.11 (legacy)\n", "")
        for output in ("iptables v1.8.11 (unknown)\n", "ip6tables v1.8.11 (legacy)\n", "secret"):
            with patch.object(AIRGAP, "bounded_exec", return_value=subprocess.CompletedProcess([], 0, output, "")) as command:
                with self.assertRaises(RuntimeError):
                    AIRGAP.select_backend("a" * 64, "iptables")
                self.assertEqual(command.call_count, 1)
        for path in ("/tmp/xtables-legacy-multi", "/bin/../bin/xtables-legacy-multi", "/bin/iptables"):
            values = [good, subprocess.CompletedProcess([], 0, "/bin/xtables-legacy-multi\n", ""),
                      subprocess.CompletedProcess([], 0, path + "\n", "")]
            with patch.object(AIRGAP, "bounded_exec", side_effect=values):
                with self.assertRaises(RuntimeError):
                    AIRGAP.select_backend("a" * 64, "iptables")
        values = [good, subprocess.CompletedProcess([], 0, "/bin/xtables-legacy-multi\n", "")] * 1
        values += [subprocess.CompletedProcess([], 0, "/bin/xtables-legacy-multi\n", "")]
        values += [subprocess.CompletedProcess([], 0, "", "")] * 2
        values += [subprocess.CompletedProcess([], 0, "iptables v1.8.11 (nf_tables)\n", "")]
        with patch.object(AIRGAP, "bounded_exec", side_effect=values):
            with self.assertRaisesRegex(RuntimeError, "mismatch"):
                AIRGAP.select_backend("a" * 64, "iptables")

    def test_legacy_state_and_replaced_container_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "legacy state"):
            AIRGAP.validate_nodes([dict(name="node", tools=["iptables"], networks={})])
        with patch.object(AIRGAP, "container_id", return_value="b" * 64), \
                patch.object(AIRGAP, "firewall") as command:
            with self.assertRaisesRegex(RuntimeError, "replaced"):
                AIRGAP.restore_node("node", binding())
            command.assert_not_called()

    def test_diagnostic_is_one_bounded_bundle_without_rules_or_raw_version(self):
        good = subprocess.CompletedProcess([], 0, "iptables v1.8.11 (legacy)\n", "")
        values = [good, good, subprocess.CompletedProcess([], 1, "PRIVATE_RULE_PAYLOAD", "PRIVATE_ERROR"),
                  subprocess.CompletedProcess([], 1, "PRIVATE_PATH", "PRIVATE_ERROR")]
        output = io.StringIO()
        with patch.object(AIRGAP, "DIAGNOSED", set()), \
                patch.object(AIRGAP, "bounded_command", return_value=subprocess.CompletedProcess([], 0, "a" * 64 + "\n", "")), \
                patch.object(AIRGAP, "bounded_exec", side_effect=values) as command, contextlib.redirect_stderr(output):
            AIRGAP.backend_diagnostic("node", binding())
            AIRGAP.backend_diagnostic("node", binding())
        self.assertEqual(command.call_count, 4)
        self.assertIn('"selected_chain_status": 1', output.getvalue())
        self.assertIn('"same_container": true', output.getvalue())
        self.assertNotIn("PRIVATE", output.getvalue())

    def test_bounded_command_caps_complete_stream_and_kills_ignoring_descendant(self):
        with self.assertRaisesRegex(RuntimeError, "output exceeded"):
            AIRGAP.bounded_command([sys.executable, "-c", "print('x' * 70000)"], time.monotonic() + 3)
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "child"
            child = "import os,signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid())); time.sleep(60)"
            parent = "import subprocess,time,sys; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(60)"
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                AIRGAP.bounded_command([sys.executable, "-c", parent], time.monotonic() + 0.5)
            self.assertTrue(pidfile.exists())
            stat = Path('/proc') / pidfile.read_text() / 'stat'
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    if stat.read_text().split(') ', 1)[1].split()[0] == 'Z':
                        break
                except (FileNotFoundError, ProcessLookupError):
                    break
                time.sleep(0.02)
            else:
                self.fail("owned descendant survived timeout")

    def test_drop_denial_preserves_docker_dns_and_internal_rule_order(self):
        with patch.object(AIRGAP, 'require_binding_node') as private, \
                patch.object(AIRGAP, 'firewall') as command:
            AIRGAP.block_node('k3d-node', binding(), ['172.18.0.0/16', '10.42.0.0/16'])
        private.assert_called_once_with('k3d-node', binding())
        self.assertEqual([call.args[2:] for call in command.call_args_list], [
            ('-N', AIRGAP.CHAIN),
            ('-A', AIRGAP.CHAIN, '-d', '127.0.0.11/32', '-j', 'DROP'),
            ('-A', AIRGAP.CHAIN, '-o', 'lo', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-d', '172.18.0.0/16', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-d', '10.42.0.0/16', '-j', 'RETURN'),
            ('-A', AIRGAP.CHAIN, '-j', 'DROP'),
            ('-I', 'OUTPUT', '1', '-j', AIRGAP.CHAIN),
            ('-I', 'FORWARD', '1', '-j', AIRGAP.CHAIN)])
        with patch.object(AIRGAP, 'require_binding_node'), patch.object(AIRGAP, 'firewall') as command:
            AIRGAP.block_node('k3d-node', binding('ip6tables'), ['fe80::/10'])
        self.assertEqual(command.call_args_list[1].args[2:],
                         ('-A', AIRGAP.CHAIN, '-o', 'lo', '-j', 'RETURN'))
        self.assertIn(('-A', AIRGAP.CHAIN, '-j', 'DROP'),
                      [call.args[2:] for call in command.call_args_list])
        self.assertFalse(any('REJECT' in call.args for call in command.call_args_list))

    def test_firewall_failure_reports_sanitized_stderr_and_still_raises(self):
        stderr = 'iptables v1.8.11: lock timeout; password=DO_NOT_EMIT\n'
        for error in (subprocess.CalledProcessError(1, ['docker', 'exec'], stderr=stderr),
                      subprocess.TimeoutExpired(['docker', 'exec'], 30, stderr=stderr.encode())):
            output = io.StringIO()
            with self.subTest(error=type(error).__name__), \
                    patch.object(AIRGAP, 'bounded_exec', side_effect=error), patch.object(AIRGAP, 'backend_diagnostic'), contextlib.redirect_stderr(output):
                with self.assertRaisesRegex(RuntimeError, "node firewall command failed"):
                    AIRGAP.firewall('k3d-node', binding(), '-A', AIRGAP.CHAIN, '-j', 'DROP')
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

    def test_host_control_accepts_http500_without_proxy_or_tls_bypass(self):
        output = io.StringIO()
        with patch.object(AIRGAP, 'run', return_value=subprocess.CompletedProcess([], 0, '500', '')) as command, \
                contextlib.redirect_stdout(output):
            AIRGAP.probe_host(AIRGAP.DEFAULT_PROBE_URL)
        self.assertIn('reachable (HTTP 500)', output.getvalue())
        args = command.call_args.args[0]
        self.assertEqual(args[:2], ['curl', '--disable'])
        self.assertEqual(args[args.index('--noproxy') + 1], '*')
        self.assertEqual(args[args.index('--proxy') + 1], '')
        self.assertEqual(args[args.index('--max-time') + 1], '10')
        self.assertEqual(args[-1], AIRGAP.DEFAULT_PROBE_URL)
        self.assertIn('--head', args)
        for forbidden in ('--fail', '--insecure', '-k', '--retry'):
            self.assertNotIn(forbidden, args)
        self.assertFalse(command.call_args.kwargs['check'])

    def test_host_control_eof_nonhttp_and_timeout_fail_without_secret_output(self):
        for result in (subprocess.CompletedProcess([], 35, '000', 'curl: unexpected EOF password=DO_NOT_EMIT'),
                       subprocess.CompletedProcess([], 0, 'nonHTTP-DO_NOT_EMIT', '')):
            with self.subTest(code=result.returncode), patch.object(AIRGAP, 'run', return_value=result):
                with self.assertRaises(RuntimeError) as raised:
                    AIRGAP.probe_host(AIRGAP.DEFAULT_PROBE_URL)
                self.assertNotIn('DO_NOT_EMIT', str(raised.exception))
        with patch.object(AIRGAP, 'run', side_effect=subprocess.TimeoutExpired(['curl'], 30,
                          stderr=b'password=DO_NOT_EMIT')):
            with self.assertRaises(RuntimeError) as raised:
                AIRGAP.probe_host(AIRGAP.DEFAULT_PROBE_URL)
            self.assertIn('timed out', str(raised.exception))
            self.assertNotIn('DO_NOT_EMIT', str(raised.exception))

    def test_host_and_node_share_validated_url_and_invalid_values_are_not_logged(self):
        for url in ('file:///private/DO_NOT_EMIT', 'http://u:DO_NOT_EMIT@1.1.1.1/',
                    'http://1.1.1.1/?token=DO_NOT_EMIT', 'http://1.1.1.1/#DO_NOT_EMIT',
                    'http://1.1.1.1:DO_NOT_EMIT/', 'http://127.0.0.1/',
                    'http://example.com/DO_NOT_EMIT', 'http://1.1.1.1/\nDO_NOT_EMIT'):
            for call in (lambda: AIRGAP.probe_host(url), lambda: AIRGAP.probe([], url, blocked=False)):
                with self.subTest(url_kind=url.split(':', 1)[0]), patch.object(AIRGAP, 'run') as command:
                    with self.assertRaises(ValueError) as raised:
                        call()
                    self.assertNotIn('DO_NOT_EMIT', str(raised.exception))
                    command.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'not-created.json'
            url = 'http://8.8.8.8/transport'
            with patch.dict(os.environ, {'AIRGAP_PROBE_URL': url}), \
                    patch('sys.argv', ['node-airgap.py', 'host-check', '--state', str(state)]), \
                    patch.object(AIRGAP, 'probe_host') as host, patch.object(AIRGAP, 'discover') as discover:
                AIRGAP.main()
            host.assert_called_once_with(url)
            discover.assert_not_called()
            self.assertFalse(state.exists())
        script = (ROOT / '.github/scripts/test-airgap.sh').read_text()
        self.assertNotIn('api.github.com/zen', script)
        self.assertEqual(script.count('"${firewall[@]}" host-check'), 1)
        self.assertLess(script.index('"${firewall[@]}" block'), script.index('"${firewall[@]}" host-check'))
        self.assertLess(script.index('"${firewall[@]}" host-check'), script.index('uds run deploy:test-bundle'))

    @unittest.skipUnless(shutil.which('curl'), 'curl is required for the owned-loopback proxy fixture')
    def test_real_host_control_proxy_environment_cannot_stand_in_for_direct_transport(self):
        class Proxy(http.server.BaseHTTPRequestHandler):
            requests = 0

            def do_HEAD(self):
                type(self).requests += 1
                self.send_response(500)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        unavailable = socket.socket()
        unavailable.bind(('127.0.0.1', 0))
        target = f'http://127.0.0.1:{unavailable.getsockname()[1]}/transport'
        proxy = f'http://127.0.0.1:{server.server_port}'
        env = {name: proxy for name in ('http_proxy', 'HTTP_PROXY', 'https_proxy', 'HTTPS_PROXY',
                                       'all_proxy', 'ALL_PROXY')}
        env.update(no_proxy='', NO_PROXY='')
        try:
            with patch.dict(os.environ, env):
                # Positive fixture: a proxy can manufacture an HTTP response
                # while this reserved, non-listening destination is unreachable.
                result = subprocess.run([shutil.which('curl'), '--disable', '--proxy', proxy,
                                         '--noproxy', '', '--head', '--max-time', '2', '--output',
                                         '/dev/null', '--write-out', '%{http_code}', target],
                                        capture_output=True, text=True, check=False, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '500')
                before = Proxy.requests
                # Fixture only: production validation rejects this loopback URL.
                with patch.object(AIRGAP, 'validate_probe_url', return_value=target):
                    with self.assertRaises(RuntimeError):
                        AIRGAP.probe_host(target)
                self.assertEqual(Proxy.requests, before)
        finally:
            unavailable.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_external_control_requires_a_public_ip_literal(self):
        for url in ("http://localhost", "http://127.0.0.1", "http://172.18.0.1", "http://example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                AIRGAP.probe([], url, blocked=False)

    def test_host_and_shared_namespaces_are_refused_before_any_firewall_command(self):
        for mode in ("host", "container:other-container", "", None):
            for operation in (lambda: AIRGAP.block_node("tagged-node", binding(), []),
                              lambda: AIRGAP.restore_node("tagged-node", binding())):
                with self.subTest(mode=mode), patch.object(AIRGAP, "container_id", return_value="a" * 64), patch.object(AIRGAP, "docker") as command:
                    command.return_value = subprocess.CompletedProcess([], 0, json.dumps(mode), "")
                    with self.assertRaisesRegex(RuntimeError, "host/shared"):
                        operation()
                    self.assertEqual(command.call_count, 1)
                    self.assertEqual(command.call_args.args,
                                     ("inspect", "--format", "{{json .HostConfig.NetworkMode}}", "a" * 64))

    def test_restore_does_not_request_dns_lookups_for_either_family(self):
        for tool in ("iptables", "ip6tables"):
            def result(_node, _tool, *args, **_kwargs):
                return subprocess.CompletedProcess([], 1 if "-C" in args else 0, "", "")
            with self.subTest(tool=tool), patch.object(AIRGAP, "require_binding_node"), \
                    patch.object(AIRGAP, "firewall", side_effect=result) as command:
                AIRGAP.restore_node("node", binding(tool))
                listings = [call.args for call in command.call_args_list if "-L" in call.args]
                self.assertEqual(listings, [("node", binding(tool), "-L", AIRGAP.CHAIN, "-n")])

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
            selected = AIRGAP.select_backend(AIRGAP.container_id(name), "iptables")
            AIRGAP.firewall(name, selected, "-N", AIRGAP.CHAIN)
            for address in ("10.43.0.1", "10.43.0.2", "10.43.0.3", "10.43.0.4"):
                AIRGAP.firewall(name, selected, "-A", AIRGAP.CHAIN, "-d", address, "-j", "RETURN")
            # Bound the old behavior inside the container so its process is
            # terminated too; no hanging child remains after the comparison.
            old = AIRGAP.docker("exec", name, "timeout", "-s", "KILL", "2", "iptables", "-w", "5",
                                "-L", AIRGAP.CHAIN, check=False)
            self.assertEqual(old.returncode, 137, old.stderr)
            numeric = AIRGAP.firewall(name, selected, "-L", AIRGAP.CHAIN, "-n")
            self.assertIn("10.43.0.1", numeric.stdout)
            AIRGAP.restore_node(name, selected)
            self.assertEqual(AIRGAP.firewall(name, selected, "-L", AIRGAP.CHAIN, "-n", check=False).returncode, 1)
            AIRGAP.restore_node(name, selected)
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
        selected = None
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
            selected = AIRGAP.select_backend(AIRGAP.container_id(node), tool)
            AIRGAP.block_node(node, selected, allowed)
            self.assertEqual(gets(addresses[0]).returncode, 0)
            self.assertNotEqual(gets(addresses[1]).returncode, 0)
            counters = AIRGAP.firewall(node, selected, "-L", AIRGAP.CHAIN, "-n", "-v", "-x").stdout
            dropped = [line.split() for line in counters.splitlines() if "DROP" in line]
            self.assertTrue(any(int(fields[0]) > 0 for fields in dropped))
            # A host-side connection to the same denied peer still succeeds.
            # A published loopback port also works with rootless Docker, where
            # the agent host cannot route directly to the bridge's subnet.
            peer = json.loads(AIRGAP.docker("inspect", names[1]).stdout)[0]
            port = peer["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
            host = build_opener(ProxyHandler({}))
            self.assertEqual(host.open(f"http://127.0.0.1:{port}", timeout=3).read().strip(), b"reachable")
            AIRGAP.restore_node(node, selected)
            self.assertEqual(gets(addresses[1]).returncode, 0)
            # Cleanup is idempotent and never flushes another chain.
            AIRGAP.restore_node(node, selected)
        finally:
            if node in names and selected is not None:
                try:
                    AIRGAP.restore_node(node, selected)
                except subprocess.SubprocessError:
                    pass
            for name in reversed(names):
                AIRGAP.docker("rm", "-f", name, check=False)
            for network in networks:
                AIRGAP.docker("network", "rm", network, check=False)


if __name__ == "__main__":
    unittest.main()
