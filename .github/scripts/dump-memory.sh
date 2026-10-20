#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Print memory evidence after a failed test. The slim cluster has no
# metrics.k8s.io service, so kubectl top may fail; the node allocatable
# and each container lastState still print.
set -u

k() {
  if command -v kubectl >/dev/null 2>&1; then
    kubectl "$@"
    return
  fi
  if [ -x ./zarf ]; then
    ./zarf tools kubectl "$@"
    return
  fi
  echo "kubectl is not available" >&2
  return 1
}

echo "::group::kubectl top pods"
k top pods -A || echo "kubectl top failed. metrics.k8s.io is not installed on this cluster."
echo "::endgroup::"

echo "::group::node allocatable"
k get nodes -o custom-columns='NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory,PODS:.status.allocatable.pods' || true
k describe nodes | sed -n '/Allocated resources:/,/Events:/p' || true
echo "::endgroup::"

echo "::group::container lastState"
if k get pods -A -o json > /tmp/tak-pods.json; then
  python3 - << 'PY'
import json
doc = json.load(open("/tmp/tak-pods.json"))
for pod in doc.get("items", []):
    meta = pod.get("metadata", {})
    ns = meta.get("namespace", "")
    name = meta.get("name", "")
    statuses = pod.get("status", {}).get("containerStatuses", []) or []
    statuses += pod.get("status", {}).get("initContainerStatuses", []) or []
    for status in statuses:
        last = status.get("lastState", {}).get("terminated")
        state = status.get("state", {})
        term = state.get("terminated")
        waiting = state.get("waiting")
        interesting = ns == "takserver" or last or term
        if not interesting:
            continue
        bits = [f"{ns}/{name}", status.get("name", ""), f"restarts={status.get('restartCount', 0)}"]
        if last:
            bits.append(f"lastState reason={last.get('reason')} exit={last.get('exitCode')}")
        if term:
            bits.append(f"state reason={term.get('reason')} exit={term.get('exitCode')}")
        if waiting:
            bits.append(f"waiting reason={waiting.get('reason')}")
        print(" ".join(bits))
PY
else
  echo "Could not read pod status."
fi
echo "::endgroup::"

# The restarted Ignite server's own log says why it exited. lastState only
# shows an exit code. Drop the thread dump so the cause above it stays visible.
echo "::group::takserver-ignite previous container log (thread dump removed)"
k logs takserver-ignite-0 -n takserver --previous --tail=4000 2>/dev/null |
  grep -Ev '^[[:space:]]+(at |Lock \[)|^Thread \[|^$' | tail -120 ||
  echo "No previous Ignite container log."
echo "::endgroup::"

echo "::group::takserver-api Ignite and exception lines"
k logs deploy/takserver-api -n takserver -c takserver-api --tail=2000 2>/dev/null |
  grep -E 'Ignite|disconnect|Exception|protocol_version' | grep -v 'ExceptionTranslationFilter' | tail -60 || true
echo "::endgroup::"

# The API reached Keycloak with "Received fatal alert: protocol_version".
echo "::group::takserver-api JVM command line and TLS settings"
k exec deploy/takserver-api -n takserver -c takserver-api -- sh -c \
  'tr "\0" " " < /proc/1/cmdline; echo; env | grep -iE "java|jvm|tls|ssl" | sed "s/=.*PASS.*/=<redacted>/"' 2>&1 | tail -20 || true
echo "::endgroup::"

echo "::group::istio gateway minimum TLS versions"
k get gateways.networking.istio.io -A -o yaml 2>/dev/null |
  grep -nE '^    name:|minProtocolVersion|maxProtocolVersion|mode:' | head -40 || true
echo "::endgroup::"

# protocol_version from the gateway: which TLS versions the API's JVM offers,
# and which the tenant gateway accepts from a client in the same namespace.
echo "::group::takserver-api JVM TLS protocols and security properties"
k exec deploy/takserver-api -n takserver -c takserver-api -- sh -c \
  'java -XshowSettings:security:tls -version 2>&1 | grep -iE "protocols|TLSv1|jdk.tls" | head -20; echo ---; grep -rhE "^(jdk\.tls|crypto\.policy|security\.useSystemPropertiesFile)" /usr/lib/jvm/java-17/conf/security/java.security /etc/crypto-policies/back-ends/java.config 2>/dev/null | head -20' 2>&1 | tail -40 || true
echo "::endgroup::"

echo "::group::takserver-api JVM TLS probe to Keycloak (same host, TLS stack and trust store)"
k exec deploy/takserver-api -n takserver -c takserver-api -- sh -c 'cat > /tmp/Probe.java <<"JAVA"
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
public class Probe {
  public static void main(String[] args) throws Exception {
    for (String protocol : new String[] {"TLSv1.3", "TLSv1.2", "TLS"}) {
      try {
        SSLContext context = SSLContext.getInstance(protocol);
        context.init(null, null, null);
        try (SSLSocket socket = (SSLSocket) context.getSocketFactory().createSocket("sso.uds.dev", 443)) {
          socket.startHandshake();
          System.out.println("context " + protocol + " ok: " + socket.getSession().getProtocol()
              + " " + socket.getSession().getCipherSuite());
        }
      } catch (Exception e) {
        System.out.println("context " + protocol + " FAILED: " + e);
      }
    }
    try {
      HttpsURLConnection c = (HttpsURLConnection) new URL("https://sso.uds.dev/realms/uds/.well-known/openid-configuration").openConnection();
      System.out.println("default HttpsURLConnection: HTTP " + c.getResponseCode());
    } catch (Exception e) {
      System.out.println("default HttpsURLConnection FAILED: " + e);
    }
  }
}
JAVA
java /tmp/Probe.java 2>&1 | tail -12' 2>&1 | tail -20 || true
echo "::endgroup::"
