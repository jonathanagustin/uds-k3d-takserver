#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Temporarily deny external egress in k3d node network namespaces only.

The host's firewall and the Docker daemon are never changed. State is saved
before mutation so a later always() CI step can restore after shell timeout.
"""

import argparse
import ipaddress
import importlib.util
import json
import os
import re
import selectors
import signal
import time
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlparse

CHAIN = "UDS_AIRGAP"
DEFAULT_PROBE_URL = "http://1.1.1.1/cdn-cgi/trace"


def run(args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=30)


def docker(*args, check=True):
    return run(["docker", *args], check=check)


def firewall_error_detail(stderr):
    """Sanitize the whole captured stream before bounding published detail."""
    try:
        raw = stderr.encode('utf-8') if isinstance(stderr, str) else (stderr or b'')
        if len(raw) > 65536:
            return 'omitted: oversized firewall stderr'
        spec = importlib.util.spec_from_file_location(
            'airgap_log_redactor', Path(__file__).with_name('redact-logs.py'))
        redactor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(redactor)
        text = redactor.decode_log(raw)
        # Authentication-bearing diagnostics are omitted in their entirety.
        if re.search(r'authorization|bearer|basic|registry[_. -]?(?:auth|password|credential|token|secret)|'
                     r'dockerconfigjson|\bauths?\b|identitytoken|accesstoken|_state=|'
                     r'[?&](?:sig|signature|token|access_token)=|://[^\s/@]+:[^\s/@]+@',
                     text, re.IGNORECASE):
            return 'omitted: authentication-bearing firewall stderr'
        safe = redactor.redact_text(text)[0]
        safe = ''.join(character if character.isprintable() else ' ' for character in safe)
        return ' '.join(safe.split())[:1024] or 'no stderr'
    except (OSError, UnicodeError, ValueError, AttributeError, ImportError):
        return 'omitted: unsanitizable firewall stderr'
    except Exception:
        # Includes the redactor's own Unsanitizable type: never fall back to raw.
        return 'omitted: unsanitizable firewall stderr'


# Fixed backend invocation bypasses the mutable generic links installed by K3s.
# Upstream reference (not an assertion about any failed checkpoint filesystem):
# k3s-io/k3s-root@1031ce26d1a575a7e073685c3f3341c20da27efc/iptables-detect/
VERSION = re.compile(r"(ip6tables|iptables) v([0-9]{1,4}(?:\.[0-9]{1,4}){1,3}) \((legacy|nf_tables)\)\n?")
CID = re.compile(r"[0-9a-f]{64}")
DIAGNOSED = set()


class BoundedCommandError(RuntimeError):
    def __init__(self, outcome, message):
        super().__init__(message)
        self.outcome = outcome


def bounded_command(args, deadline):
    """Own the local client group; bound complete output and remote execution."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BoundedCommandError('deadline', "airgap diagnostic deadline exhausted")
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BoundedCommandError('deadline', "airgap bounded command timed out")
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    streams[key.fileobj].extend(chunk)
                    if sum(map(len, streams.values())) > 65536:
                        raise BoundedCommandError('output-limit', "airgap bounded command output exceeded limit")
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
        return subprocess.CompletedProcess(args, process.returncode,
            streams[process.stdout].decode('utf-8', errors='strict'),
            streams[process.stderr].decode('utf-8', errors='strict'))
    finally:
        # Includes descendants retaining pipes after the client exits.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        selector.close()
        process.stdout.close()
        process.stderr.close()


def bounded_exec(cid, args, deadline):
    # The remote timeout owns the command inside the node; killing docker alone
    # does not terminate a command already started by docker exec.
    return bounded_command(["docker", "exec", cid, "timeout", "-s", "KILL", "3", *args], deadline)


def parse_version(result, family):
    match = VERSION.fullmatch(result.stdout)
    if result.returncode != 0 or not match or match[1] != family:
        raise RuntimeError("unsupported or unavailable iptables version")
    return match[2], "nft" if match[3] == "nf_tables" else "legacy"


def validate_binding(binding):
    if not isinstance(binding, dict) or set(binding) != {"family", "backend", "path", "version", "cid"}:
        raise RuntimeError("unsupported airgap backend state; legacy state requires manual review")
    family, backend, path = binding["family"], binding["backend"], binding["path"]
    if (family not in ("iptables", "ip6tables") or backend not in ("legacy", "nft") or
            not isinstance(path, str) or
            not re.fullmatch(r"/(?:usr/)?s?bin/(?:aux/)?xtables-" + backend + r"-multi|" +
                             r"/var/lib/rancher/k3s/data/[0-9a-f]+/bin/(?:aux/)?xtables-" + backend + r"-multi", path) or
            any(part in (".", "..") for part in path.split("/")) or
            not isinstance(binding["cid"], str) or not CID.fullmatch(binding["cid"]) or
            not isinstance(binding["version"], str) or
            not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}", binding["version"])):
        raise RuntimeError("invalid airgap backend state")
    return binding


def container_id(node):
    value = docker("inspect", "--format", "{{.Id}}", node).stdout.strip()
    if not CID.fullmatch(value):
        raise RuntimeError("unavailable node container identity")
    return value


def select_backend(cid, family):
    if not isinstance(cid, str) or not CID.fullmatch(cid) or family not in ("iptables", "ip6tables"):
        raise RuntimeError("invalid backend selection identity")
    deadline = time.monotonic() + 15
    version, backend = parse_version(bounded_exec(cid, [family, "--version"], deadline), family)
    candidate = "xtables-" + backend + "-multi"
    # The generic link may expose bin/aux even when that directory is not on
    # Docker exec PATH. Resolve it after version selection, never for rules.
    found = bounded_exec(cid, ["which", family], deadline)
    if found.returncode != 0 or not found.stdout.startswith("/") or len(found.stdout) > 1024:
        raise RuntimeError("fixed iptables backend unavailable")
    resolved = bounded_exec(cid, ["readlink", "-f", found.stdout.strip()], deadline)
    if resolved.returncode != 0:
        raise RuntimeError("fixed iptables backend unresolved")
    path = resolved.stdout.strip()
    if Path(path).name == "iptables-detect.sh":
        # Some wrappers remain scripts after --version. Only a known packaged
        # wrapper directory may trigger a same-backend fixed-name lookup.
        validate_binding(dict(family=family, backend=backend,
                              path=str(Path(path).with_name(candidate)), version=version, cid=cid))
        found = bounded_exec(cid, ["which", candidate], deadline)
        if found.returncode != 0 or not found.stdout.startswith("/") or len(found.stdout) > 1024:
            raise RuntimeError("fixed iptables backend unavailable")
        resolved = bounded_exec(cid, ["readlink", "-f", found.stdout.strip()], deadline)
        if resolved.returncode != 0:
            raise RuntimeError("fixed iptables backend unresolved")
        path = resolved.stdout.strip()
    binding = validate_binding(dict(family=family, backend=backend, path=path,
                                    version=version, cid=cid))
    for flag in ("-f", "-x"):
        if bounded_exec(cid, ["test", flag, binding["path"]], deadline).returncode != 0:
            raise RuntimeError("fixed iptables backend is not an executable regular file")
    # Also verifies this multicall binary supports the explicit family applet.
    if parse_version(bounded_exec(cid, [binding["path"], family, "--version"], deadline), family) != (version, backend):
        raise RuntimeError("fixed iptables backend version mismatch")
    return binding


def backend_diagnostic(node, binding):
    """One bounded bundle; never publish rule output or raw inspect."""
    key = (binding["cid"], binding["family"])
    if key in DIAGNOSED:
        return
    DIAGNOSED.add(key)
    deadline = time.monotonic() + 10
    report = {"family": binding["family"], "backend": binding["backend"], "cid": binding["cid"]}
    try:
        result = bounded_command(["docker", "inspect", "--format", "{{.Id}}", node], deadline)
        report["same_container"] = result.returncode == 0 and result.stdout.strip() == binding["cid"]
        for label, command in (("generic", [binding["family"]]),
                               ("selected", [binding["path"], binding["family"]])):
            try:
                report[label + "_version"] = parse_version(
                    bounded_exec(binding["cid"], [*command, "--version"], deadline), binding["family"])
            except RuntimeError:
                report[label + "_version"] = "unavailable"
        # Never publish chain contents; other backend availability is not assumed.
        result = bounded_exec(binding["cid"], [binding["path"], binding["family"],
                              "-w", "1", "-L", CHAIN, "-n"], deadline)
        report["selected_chain_status"] = result.returncode
        other = "nft" if binding["backend"] == "legacy" else "legacy"
        found = bounded_exec(binding["cid"], ["which", "xtables-" + other + "-multi"], deadline)
        report["other_chain_status"] = "unavailable"
        if found.returncode == 0 and found.stdout.startswith("/") and len(found.stdout) <= 1024:
            resolved = bounded_exec(binding["cid"], ["readlink", "-f", found.stdout.strip()], deadline)
            if resolved.returncode == 0:
                candidate = dict(binding, backend=other, path=resolved.stdout.strip())
                validate_binding(candidate)
                version, backend = parse_version(bounded_exec(binding["cid"],
                    [candidate["path"], binding["family"], "--version"], deadline), binding["family"])
                if backend == other:
                    report["other_version"] = (version, backend)
                    result = bounded_exec(binding["cid"], [candidate["path"], binding["family"],
                                          "-w", "1", "-L", CHAIN, "-n"], deadline)
                    report["other_chain_status"] = result.returncode
    except (OSError, UnicodeError, RuntimeError, subprocess.SubprocessError):
        report["remaining"] = "unavailable"
    print("Airgap backend diagnostic: " + json.dumps(report, sort_keys=True), file=sys.stderr)


def firewall(node, tool, *args, check=True):
    binding = validate_binding(tool)
    started = time.monotonic()
    try:
        result = bounded_exec(binding["cid"], [binding["path"], binding["family"], "-w", "1", *args],
                              time.monotonic() + 5)
        if check:
            result.check_returncode()
        return result
    except (subprocess.SubprocessError, RuntimeError, OSError, UnicodeError) as error:
        print('Airgap firewall failure metadata: ' + json.dumps(
            firewall_failure_metadata(args, error, started), sort_keys=True), file=sys.stderr)
        print('Node firewall command failed; sanitized stderr: ' +
              firewall_error_detail(getattr(error, 'stderr', None)), file=sys.stderr)
        backend_diagnostic(node, binding)
        raise RuntimeError("node firewall command failed") from None


def firewall_failure_metadata(args, error, started):
    """Only fixed operation/role labels and bounded numbers; never argv/text."""
    operations = {'-N': 'create-chain', '-A': 'append-rule', '-I': 'insert-rule',
                  '-L': 'list-chain', '-C': 'check-rule', '-D': 'delete-rule',
                  '-F': 'flush-chain', '-X': 'delete-chain'}
    roles = {'-d': 'destination', '-o': 'output-interface', '-j': 'jump-target',
             '-n': 'numeric-listing', '-v': 'verbose-listing', '-x': 'exact-counters'}
    code = getattr(error, 'returncode', None)
    code = code if type(code) is int and -255 <= code <= 255 else None
    if isinstance(error, BoundedCommandError) and error.outcome in ('deadline', 'output-limit'):
        outcome = error.outcome
    elif isinstance(error, subprocess.CalledProcessError):
        outcome = 'process-signal' if code is not None and code < 0 else 'process-exit'
    elif isinstance(error, subprocess.TimeoutExpired):
        outcome = 'wait-deadline'
    elif isinstance(error, OSError):
        outcome = 'os-error'
    elif isinstance(error, UnicodeError):
        outcome = 'invalid-utf8'
    else:
        outcome = 'unknown-error'
    return {'outcome': outcome, 'exit': code,
            # Only a negative local process return code establishes a signal.
            # Remote exit 137 remains exit 137, not a claimed signal cause.
            'signal': -code if code is not None and -64 <= code < 0 else None,
            'elapsed_ms': min(60000, max(0, int((time.monotonic() - started) * 1000))),
            'operation': operations.get(args[0], 'unknown') if args else 'unknown',
            'argument_roles': sorted({roles[arg] for arg in args if arg in roles})}


def require_private_network(node):
    # Labels alone do not establish namespace isolation: a mislabeled
    # --network=host container would otherwise change the daemon host's rules,
    # and container:<id> shares another container's network namespace.
    mode = json.loads(docker("inspect", "--format", "{{json .HostConfig.NetworkMode}}", node).stdout)
    if not isinstance(mode, str) or not mode or mode == "host" or mode.startswith("container:"):
        raise RuntimeError(f"{node}: refusing firewall changes in host/shared network mode")


def require_binding_node(node, binding):
    validate_binding(binding)
    if container_id(node) != binding["cid"]:
        raise RuntimeError("refusing airgap operation on replaced node container")
    require_private_network(binding["cid"])
    deadline = time.monotonic() + 15
    resolved = bounded_exec(binding["cid"], ["readlink", "-f", binding["path"]], deadline)
    if resolved.returncode != 0 or resolved.stdout.strip() != binding["path"]:
        raise RuntimeError("fixed airgap executable identity changed")
    for flag in ("-f", "-x"):
        if bounded_exec(binding["cid"], ["test", flag, binding["path"]], deadline).returncode != 0:
            raise RuntimeError("fixed airgap executable unavailable")
    if parse_version(bounded_exec(binding["cid"], [binding["path"], binding["family"], "--version"], deadline),
                     binding["family"]) != (binding["version"], binding["backend"]):
        raise RuntimeError("fixed airgap executable version changed")


def validate_nodes(nodes):
    if not isinstance(nodes, list) or not 0 < len(nodes) <= 32:
        raise RuntimeError("unsupported airgap state")
    for node in nodes:
        if (not isinstance(node, dict) or set(node) != {"name", "tools", "networks"} or
                not isinstance(node["tools"], list) or not 0 < len(node["tools"]) <= 2 or
                not isinstance(node["name"], str) or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", node["name"])):
            raise RuntimeError("unsupported airgap node state")
        families, cids = set(), set()
        for binding in node["tools"]:
            validate_binding(binding)
            families.add(binding["family"])
            cids.add(binding["cid"])
        if len(families) != len(node["tools"]) or "iptables" not in families or len(cids) != 1:
            raise RuntimeError("ambiguous airgap family/container state")
        for binding in node["tools"]:
            require_binding_node(node["name"], binding)
    return nodes


def read_state(path):
    if path.stat().st_size > 65536:
        raise RuntimeError("oversized airgap state")
    return validate_nodes(json.loads(path.read_text()))


def require_base_filter(node, tool):
    # Exit 1 from a chain lookup or jump check can also mean backend failure.
    # Prove both base filter chains readable before treating it as absence.
    for parent in ("OUTPUT", "FORWARD"):
        firewall(node, tool, "-L", parent, "-n")


def restore_node(node, tool):
    require_binding_node(node, tool)
    # DNS is intentionally unavailable while guarded. Listing without -n can
    # block on reverse lookups before any rule is removed.
    found = firewall(node, tool, "-L", CHAIN, "-n", check=False)
    if found.returncode == 1:
        require_base_filter(node, tool)
        return
    found.check_returncode()
    for parent in ("OUTPUT", "FORWARD"):
        for _ in range(8):
            found = firewall(node, tool, "-C", parent, "-j", CHAIN, check=False)
            if found.returncode == 1:
                require_base_filter(node, tool)
                break
            found.check_returncode()
            firewall(node, tool, "-D", parent, "-j", CHAIN)
        else:
            raise RuntimeError("too many airgap jump rules; refusing unbounded cleanup")
    firewall(node, tool, "-F", CHAIN)
    firewall(node, tool, "-X", CHAIN)


def block_node(node, tool, networks):
    require_binding_node(node, tool)
    # Refuse to replace an unrelated chain or another test's active guard.
    firewall(node, tool, "-N", CHAIN)
    # DROP is built in; denial does not depend on a REJECT target extension.
    # Docker's embedded resolver can forward through the host. Refuse that
    # route as well; Kubernetes DNS serves internal names independently.
    if tool["family"] == "iptables":
        firewall(node, tool, "-A", CHAIN, "-d", "127.0.0.11/32", "-j", "DROP")
    firewall(node, tool, "-A", CHAIN, "-o", "lo", "-j", "RETURN")
    for network in networks:
        firewall(node, tool, "-A", CHAIN, "-d", str(ipaddress.ip_network(network)), "-j", "RETURN")
    firewall(node, tool, "-A", CHAIN, "-j", "DROP")
    for parent in ("OUTPUT", "FORWARD"):
        firewall(node, tool, "-I", parent, "1", "-j", CHAIN)


def discover(cluster):
    ids = docker("ps", "-q", "--filter", f"label=k3d.cluster={cluster}").stdout.split()
    if not ids:
        raise RuntimeError(f"no containers for k3d cluster {cluster}")
    containers = json.loads(docker("inspect", *ids).stdout)
    nodes = [c for c in containers if c["Config"]["Labels"].get("k3d.role") in ("server", "agent")]
    if not nodes:
        raise RuntimeError(f"no server/agent nodes in k3d cluster {cluster}")
    networks = sorted({name for node in nodes for name in node["NetworkSettings"]["Networks"]})
    addresses = set()
    for network in json.loads(docker("network", "inspect", *networks).stdout):
        for config in network["IPAM"]["Config"]:
            if config.get("Subnet"):
                addresses.add(str(ipaddress.ip_network(config["Subnet"])))
    kube = json.loads(run(["uds", "zarf", "tools", "kubectl", "get", "nodes", "-o", "json"]).stdout)
    for node in kube["items"]:
        addresses.update(node["spec"].get("podCIDRs", []))
    services = json.loads(run(["uds", "zarf", "tools", "kubectl", "get", "svc", "-A", "-o", "json"]).stdout)
    for service in services["items"]:
        for address in service["spec"].get("clusterIPs", []):
            if address != "None":
                addresses.add(str(ipaddress.ip_network(address)))
    # Ambient mesh DNS returns these synthetic, internally routed addresses.
    addresses.update(("240.240.0.0/16", "fe80::/10", "ff02::/16"))
    by_family = {str(version): sorted(a for a in addresses if ipaddress.ip_network(a).version == version)
                 for version in (4, 6)}
    result = []
    for node in nodes:
        name = node["Name"].lstrip("/")
        require_private_network(name)
        cid = container_id(name)
        tools = [select_backend(cid, "iptables")]
        ipv6 = docker("exec", name, "cat", "/proc/sys/net/ipv6/conf/all/disable_ipv6", check=False)
        if ipv6.returncode == 0 and ipv6.stdout.strip() == "0":
            # If IPv6 is enabled but its filter is unavailable, fail closed.
            binding = select_backend(cid, "ip6tables")
            firewall(name, binding, "-L", "-n")
            tools.append(binding)
        result.append({"name": name, "tools": tools, "networks": by_family})
    return result


def probe_failure(node, blocked, result):
    """Fail closed with a short wget diagnostic.

    An unreachable control before the firewall is not an egress denial.
    stderr is one line and bounded so a hung transfer cannot fill the log.
    """
    outcome = "succeeded" if blocked else "failed"
    detail = (result.stderr or "").replace("\r", " ").replace("\n", " ")
    detail = "".join(ch if ch.isprintable() else " " for ch in detail)
    detail = " ".join(detail.split())
    if len(detail) > 160:
        detail = detail[:160] + "..."
    message = f"{node}: external control unexpectedly {outcome} (exit {result.returncode}"
    if detail:
        message += f": {detail}"
    return RuntimeError(message + ")")


def validate_probe_url(url):
    message = 'AIRGAP_PROBE_URL requires HTTP(S) and a public IP literal without credentials, query or fragment'
    try:
        if (not isinstance(url, str) or len(url) > 2048 or
                any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url)):
            raise ValueError(message)
        parsed = urlparse(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or '%' in parsed.hostname or
                parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or
                (parsed.port is not None and not 0 < parsed.port <= 65535) or
                not ipaddress.ip_address(parsed.hostname).is_global):
            raise ValueError(message)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    return url


def probe(nodes, url, blocked):
    validate_probe_url(url)
    # Test direct transport reachability, not resource health. A redirect or
    # HTTP error proves egress even when wget later fails (for example on TLS).
    # Disable proxies so an allowed local proxy cannot stand in for the IP.
    for node in nodes:
        result = docker("exec", node["name"], "wget", "-Y", "off", "-S", "-T", "5", "-q", "-O", "/dev/null", url, check=False)
        response = re.search(r"^\s*HTTP/[0-9]+(?:\.[0-9]+)? [1-5][0-9]{2}(?:\s|$)", result.stderr or "", re.MULTILINE)
        reachable = result.returncode == 0 or response is not None
        if reachable == blocked:
            raise probe_failure(node["name"], blocked, result)
        print(f"{node['name']}: external IP control {'denied' if blocked else 'reachable'}")


def probe_host(url):
    """Prove direct host transport to the same node control, not service health."""
    validate_probe_url(url)
    try:
        result = run(['curl', '--disable', '--globoff', '--noproxy', '*', '--proxy', '',
                      '--silent', '--show-error', '--head', '--connect-timeout', '5', '--max-time', '10',
                      '--output', '/dev/null', '--write-out', '%{http_code}', url], check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Host external IP control timed out: ' +
                           firewall_error_detail(error.stderr)) from None
    except OSError:
        raise RuntimeError('Host external IP control unavailable: curl could not start') from None
    status = (result.stdout or '').strip()
    if result.returncode != 0 or not re.fullmatch(r'[1-5][0-9]{2}', status):
        raise RuntimeError(f'Host external IP control failed (exit {result.returncode}): ' +
                           firewall_error_detail(result.stderr)) from None
    print(f'Host external IP control reachable (HTTP {status})')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("block", "check", "restore", "host-check"))
    parser.add_argument("--cluster", default="uds")
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    url = os.environ.get("AIRGAP_PROBE_URL", DEFAULT_PROBE_URL)
    if args.action == "host-check":
        probe_host(url)
        return
    if args.action == "block":
        if args.state.exists():
            raise RuntimeError("airgap state already exists; restore it before starting another test")
        nodes = discover(args.cluster)
        # Prove the external control is reachable before attributing a denial
        # to the firewall. A remote outage fails setup instead of passing.
        probe(nodes, url, blocked=False)
        for node in nodes:
            for tool in node["tools"]:
                if firewall(node["name"], tool, "-L", CHAIN, "-n", check=False).returncode == 0:
                    raise RuntimeError(f"{node['name']}: {CHAIN} already exists")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(nodes, indent=2))
        for node in nodes:
            for tool in node["tools"]:
                family = "4" if tool["family"] == "iptables" else "6"
                block_node(node["name"], tool, node["networks"][family])
        probe(nodes, url, blocked=True)
    elif args.action == "restore":
        if not args.state.exists():
            print("No active airgap state")
            return
        nodes = read_state(args.state)
        errors = []
        for node in nodes:
            for tool in node["tools"]:
                try:
                    restore_node(node["name"], tool)
                except (subprocess.SubprocessError, RuntimeError) as error:
                    errors.append(str(error))
        if errors:
            raise RuntimeError("; ".join(errors))
        args.state.unlink()
        print("Restored k3d node egress; host firewall was unchanged")
    else:
        nodes = read_state(args.state)
        probe(nodes, url, blocked=True)
        for node in nodes:
            for tool in node["tools"]:
                print(firewall(node["name"], tool, "-L", CHAIN, "-n", "-v", "-x").stdout)


if __name__ == "__main__":
    main()
