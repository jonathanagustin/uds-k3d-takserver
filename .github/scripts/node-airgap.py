#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Temporarily deny external egress in k3d node network namespaces only.

The host's firewall and the Docker daemon are never changed. State is saved
before mutation so a later always() CI step can restore after shell timeout.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

CHAIN = "UDS_AIRGAP"


def run(args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=30)


def docker(*args, check=True):
    return run(["docker", *args], check=check)


def firewall(node, tool, *args, check=True):
    return docker("exec", node, tool, "-w", "5", *args, check=check)



def require_private_network(node):
    # Labels alone do not establish namespace isolation: a mislabeled
    # --network=host container would otherwise change the daemon host's rules,
    # and container:<id> shares another container's network namespace.
    mode = json.loads(docker("inspect", "--format", "{{json .HostConfig.NetworkMode}}", node).stdout)
    if not isinstance(mode, str) or not mode or mode == "host" or mode.startswith("container:"):
        raise RuntimeError(f"{node}: refusing firewall changes in host/shared network mode")


def restore_node(node, tool):
    require_private_network(node)
    found = firewall(node, tool, "-L", CHAIN, check=False)
    if found.returncode == 1:
        return
    found.check_returncode()
    for parent in ("OUTPUT", "FORWARD"):
        while firewall(node, tool, "-C", parent, "-j", CHAIN, check=False).returncode == 0:
            firewall(node, tool, "-D", parent, "-j", CHAIN)
    firewall(node, tool, "-F", CHAIN)
    firewall(node, tool, "-X", CHAIN)


def block_node(node, tool, networks):
    require_private_network(node)
    # Refuse to replace an unrelated chain or another test's active guard.
    firewall(node, tool, "-N", CHAIN)
    # Docker's embedded resolver can forward through the host. Refuse that
    # route as well; Kubernetes DNS serves internal names independently.
    if tool == "iptables":
        firewall(node, tool, "-A", CHAIN, "-d", "127.0.0.11/32", "-j", "REJECT")
    firewall(node, tool, "-A", CHAIN, "-o", "lo", "-j", "RETURN")
    for network in networks:
        firewall(node, tool, "-A", CHAIN, "-d", str(ipaddress.ip_network(network)), "-j", "RETURN")
    firewall(node, tool, "-A", CHAIN, "-j", "REJECT")
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
        tools = ["iptables"]
        ipv6 = docker("exec", name, "cat", "/proc/sys/net/ipv6/conf/all/disable_ipv6", check=False)
        if ipv6.returncode == 0 and ipv6.stdout.strip() == "0":
            # If IPv6 is enabled but its filter is unavailable, fail closed.
            firewall(name, "ip6tables", "-L")
            tools.append("ip6tables")
        result.append({"name": name, "tools": tools, "networks": by_family})
    return result


def probe(nodes, url, blocked):
    host = urlparse(url).hostname
    if not host or not ipaddress.ip_address(host).is_global:
        raise ValueError("AIRGAP_PROBE_URL must use a public IP literal, not DNS or a local address")
    # wget is provided by the k3d node's BusyBox. No DNS failure can masquerade
    # as an egress denial because this control uses an IP literal.
    for node in nodes:
        result = docker("exec", node["name"], "wget", "-T", "5", "-q", "-O", "/dev/null", url, check=False)
        if (result.returncode == 0) == blocked:
            raise RuntimeError(f"{node['name']}: external control unexpectedly {'succeeded' if blocked else 'failed'}")
        print(f"{node['name']}: external IP control {'denied' if blocked else 'reachable'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("block", "check", "restore"))
    parser.add_argument("--cluster", default="uds")
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    url = os.environ.get("AIRGAP_PROBE_URL", "http://1.1.1.1/cdn-cgi/trace")
    if args.action == "block":
        if args.state.exists():
            raise RuntimeError("airgap state already exists; restore it before starting another test")
        nodes = discover(args.cluster)
        # Prove the external control is reachable before attributing a denial
        # to the firewall. A remote outage fails setup instead of passing.
        probe(nodes, url, blocked=False)
        for node in nodes:
            for tool in node["tools"]:
                if firewall(node["name"], tool, "-L", CHAIN, check=False).returncode == 0:
                    raise RuntimeError(f"{node['name']}: {CHAIN} already exists")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(nodes, indent=2))
        for node in nodes:
            for tool in node["tools"]:
                family = "4" if tool == "iptables" else "6"
                block_node(node["name"], tool, node["networks"][family])
        probe(nodes, url, blocked=True)
    elif args.action == "restore":
        if not args.state.exists():
            print("No active airgap state")
            return
        nodes = json.loads(args.state.read_text())
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
        nodes = json.loads(args.state.read_text())
        probe(nodes, url, blocked=True)
        for node in nodes:
            for tool in node["tools"]:
                print(firewall(node["name"], tool, "-L", CHAIN, "-n", "-v", "-x").stdout)


if __name__ == "__main__":
    main()
