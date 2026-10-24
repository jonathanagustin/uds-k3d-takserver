#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""List the TCP connections between pods in the takserver namespace.

Reads /proc/net/tcp and /proc/net/tcp6 in every running container (no
tools needed in the image), keeps ESTABLISHED sockets, and maps addresses
to pods and Services. A connection is reported as client -> server:port,
where the server is the side that listens on that port. Each flow is
checked against the allow list from the Package CR, so a flow the rules do
not cover shows up here before it shows up as a failure.

    flows.py [--check]
    TAK_NAMESPACE=cloudtak flows.py --check

--check exits 1 when an observed in-namespace flow has no matching allow
rule. Connections to the Kubernetes API, DNS, and the mesh are ignored.

--check also exits 1 when an Ingress rule from other pods (a remoteSelector
with no remoteGenerated) has no remoteServiceAccount, or when a generated
AuthorizationPolicy in the namespace admits this namespace or a peer
namespace by namespace alone, with no principal.
"""

import ipaddress
import json
import shlex
import socket
import struct
import subprocess
import sys
import os

NS = os.environ.get("TAK_NAMESPACE", "takserver")
# Package CR to check against. The CloudTAK namespace has its own.
PACKAGE = os.environ.get("TAK_PACKAGE", NS)


def kubectl(*args, check=True):
    configured = os.environ.get("KUBECTL", "")
    base = shlex.split(configured) if configured else ["uds", "zarf", "tools", "kubectl"]
    result = subprocess.run(base + list(args), text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def parse_addr(hexaddr):
    ip_hex, port_hex = hexaddr.split(":")
    port = int(port_hex, 16)
    raw = bytes.fromhex(ip_hex)
    if len(raw) == 4:
        ip = socket.inet_ntoa(struct.pack("<I", struct.unpack(">I", raw)[0]))
    else:
        words = struct.unpack("<4I", raw)
        ip = str(ipaddress.IPv6Address(struct.pack(">4I", *words)))
        mapped = ipaddress.IPv6Address(ip).ipv4_mapped
        if mapped:
            ip = str(mapped)
    return ip, port


def sockets(pod, container):
    result = kubectl("exec", "-n", NS, pod, "-c", container, "--", "cat", "/proc/net/tcp", "/proc/net/tcp6", check=False)
    listen, established = set(), set()
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[0] == "sl":
            continue
        local, remote, state = parse_addr(fields[1]), parse_addr(fields[2]), fields[3]
        if state == "0A":
            listen.add(local[1])
        elif state == "01":
            established.add((local, remote))
    return result.returncode == 0, listen, established


def main():
    check = "--check" in sys.argv
    pods = json.loads(kubectl("get", "pods", "-n", NS, "-o", "json").stdout)["items"]
    services = json.loads(kubectl("get", "svc", "-n", NS, "-o", "json").stdout)["items"]
    package = json.loads(kubectl("get", "package", PACKAGE, "-n", NS, "-o", "json").stdout)

    by_ip, labels = {}, {}
    for pod in pods:
        name = pod["metadata"]["name"]
        labels[name] = pod["metadata"].get("labels") or {}
        ip = pod.get("status", {}).get("podIP")
        if ip:
            by_ip[ip] = name
    svc_ip = {}
    for svc in services:
        ip = svc["spec"].get("clusterIP")
        if ip and ip != "None":
            svc_ip[ip] = svc

    def svc_pods(svc):
        selector = svc["spec"].get("selector") or {}
        return [n for n, l in labels.items() if selector and all(l.get(k) == v for k, v in selector.items())]

    listening, conns = {}, {}
    for pod in pods:
        if pod.get("status", {}).get("phase") != "Running":
            continue
        name = pod["metadata"]["name"]
        ok = False
        ports, est = set(), set()
        for container in pod["spec"]["containers"]:
            done, lp, es = sockets(name, container["name"])
            ok = ok or done
            ports |= lp
            est |= es
        if not ok:
            print(f"skip {name}: could not read /proc/net/tcp")
        listening[name] = ports
        conns[name] = est

    # ztunnel shares the pod network namespace. Its HBONE (15008), capture
    # (15001, 15006), and DNS (15053) sockets are the mesh, not app flows.
    mesh_ports = {15001, 15006, 15008, 15053}
    flows = set()
    for name, est in conns.items():
        for (lip, lport), (rip, rport) in est:
            if rport in mesh_ports or lport in mesh_ports:
                continue
            if rip in svc_ip:
                targets = svc_pods(svc_ip[rip])
                # A Service port may map to a different targetPort.
                port_map = {p["port"]: p.get("targetPort", p["port"]) for p in svc_ip[rip]["spec"]["ports"]}
                tport = port_map.get(rport, rport)
                tport = tport if isinstance(tport, int) else rport
                for target in targets:
                    flows.add((name, target, tport))
                continue
            peer = by_ip.get(rip)
            if not peer or peer == name:
                continue
            if rport in listening.get(peer, set()) and lport not in listening.get(name, set()):
                flows.add((name, peer, rport))

    def app(name):
        l = labels.get(name, {})
        return l.get("app") or l.get("app.kubernetes.io/name") or l.get("batch.kubernetes.io/job-name") or name

    rules = package["spec"].get("network", {}).get("allow", [])

    def matches(selector, name):
        if not selector:
            return True
        return all(labels.get(name, {}).get(k) == v for k, v in selector.items())

    def allowed(src, dst, port):
        egress = ingress = False
        for rule in rules:
            # Rules for hosts and CIDRs outside the cluster cover no pod here.
            if rule.get("remoteHost") or rule.get("remoteCidr"):
                continue
            if rule.get("remoteNamespace") not in (None, "", NS) and not rule.get("remoteGenerated"):
                continue
            generated = rule.get("remoteGenerated")
            if generated and generated != "IntraNamespace":
                continue
            rport = rule.get("port")
            ports = rule.get("ports") or ([rport] if rport else [])
            if ports and port not in ports:
                continue
            if rule["direction"] == "Egress" and matches(rule.get("selector"), src) and (generated or matches(rule.get("remoteSelector"), dst)):
                egress = True
            if rule["direction"] == "Ingress" and matches(rule.get("selector"), dst) and (generated or matches(rule.get("remoteSelector"), src)):
                ingress = True
        return egress and ingress

    summary = sorted({(app(s), app(d), p, allowed(s, d, p)) for s, d, p in flows})
    print(f"{'client':<24} {'server':<24} {'port':>6}  allowed")
    missing = 0
    for src, dst, port, ok in summary:
        print(f"{src:<24} {dst:<24} {port:>6}  {'yes' if ok else 'NO'}")
        missing += 0 if ok else 1
    unscoped = unscoped_rules(rules) + unscoped_policies(rules)
    for line in unscoped:
        print(f"no workload identity: {line}")
    if check and (missing or unscoped):
        if missing:
            print(f"{missing} observed flows have no allow rule", file=sys.stderr)
        if unscoped:
            print(f"{len(unscoped)} pod-to-pod rules or policies have no service account", file=sys.stderr)
        raise SystemExit(1)


def unscoped_rules(rules):
    """Ingress rules from other pods that do not name the client's ServiceAccount."""
    return [
        f"Package rule {rule.get('description', rule)}"
        for rule in rules
        if rule.get("direction") == "Ingress"
        and rule.get("remoteSelector")
        and not rule.get("remoteGenerated")
        and not rule.get("remoteServiceAccount")
    ]


def unscoped_policies(rules):
    """Generated AuthorizationPolicy sources that admit a pod namespace without a principal."""
    peers = {NS} | {r["remoteNamespace"] for r in rules if r.get("remoteNamespace")}
    out = kubectl("get", "authorizationpolicies.security.istio.io", "-n", NS, "-l", f"uds/package={PACKAGE}", "-o", "json")
    found = []
    for policy in json.loads(out.stdout)["items"]:
        if policy["spec"].get("action", "ALLOW") != "ALLOW":
            continue
        for rule in policy["spec"].get("rules") or []:
            for src in rule.get("from") or []:
                source = src.get("source") or {}
                if source.get("principals"):
                    continue
                if set(source.get("namespaces") or []) & peers:
                    found.append(f"AuthorizationPolicy {policy['metadata']['name']} {source}")
    return found


if __name__ == "__main__":
    main()
