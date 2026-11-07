#!/usr/bin/env bash
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Print memory evidence after a failed test. The slim cluster has no
# metrics.k8s.io service, so kubectl top may fail; the node allocatable
# and each container lastState still print.
set -u

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Failure logs are copied and printed later. Anything this script writes to
# the job log has to go through the redactor, and CoreConfig is summarized
# instead of printed: the rendered file holds the Keycloak client secret.
redact() { python3 "${here}/redact-logs.py" -; }

# On a wedged runner (#300) docker, kubectl and dmesg can block. Each call
# gets its own bound so the later log steps keep their wall clock.

k() {
  if command -v kubectl >/dev/null 2>&1; then
    timeout 30 kubectl "$@"
    return
  fi
  if [[ -x ./zarf ]]; then
    timeout 30 ./zarf tools kubectl "$@"
    return
  fi
  echo "kubectl is not available" >&2
  return 1
}

# A k3d node container that restarts takes the API server and every pod with
# it (all containers then show exit 255). Kubelet sees no memory or disk
# pressure in that case, so the evidence is on the runner: the kernel OOM
# killer, the container's restart count, and k3s's last log lines.
echo "::group::runner memory, OOM kills, and k3d node restarts"
free -m || true
df -h / || true
sudo timeout 30 dmesg -T 2>/dev/null | grep -iE 'out of memory|oom-kill|killed process' | tail -20 ||
  echo "No OOM kill in dmesg."
for node in $(timeout 30 docker ps -a --filter name=k3d- --format '{{.Names}}' 2>/dev/null); do
  timeout 30 docker inspect "${node}" --format \
    '{{.Name}} restarts={{.RestartCount}} oomkilled={{.State.OOMKilled}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' || true
done
timeout 30 docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.MemPerc}}' 2>/dev/null || true
for node in $(timeout 30 docker ps -a --filter name=k3d- --filter name=server --format '{{.Names}}' 2>/dev/null); do
  # The API server's 502/503 proxy lines while the kubelet is down would
  # push the fatal out of the tail, so they are left out.
  echo "--- ${node}: k3s starts, errors, and shutdown lines"
  timeout 30 docker logs "${node}" 2>&1 |
    grep -iE 'Starting k3s|level=fatal|level=error|panic|signal|shutting down|killed' |
    grep -v 'Sending HTTP/1.1 50[23] response' | tail -40 || true
done
echo "::endgroup::"

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
  grep -Ev '^[[:space:]]+(at |Lock \[)|^Thread \[|^$' | tail -120 | redact ||
  echo "No previous Ignite container log."
echo "::endgroup::"

echo "::group::takserver-api Ignite and exception lines"
k logs deploy/takserver-api -n takserver -c takserver-api --tail=2000 2>/dev/null |
  grep -E 'Ignite|disconnect|Exception|protocol_version' | grep -v 'ExceptionTranslationFilter' | tail -60 | redact || true
echo "::endgroup::"

# The process command line and environment are not printed. They carry
# unquoted passwords and client secrets that a value regex can miss.

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

# The rendered CoreConfig holds the Keycloak client secret and the keystore
# password. Print only which TLS context is set and whether those attributes
# are present. Do not cat or grep the file onto the job log.
echo "::group::takserver-api CoreConfig summary"
k exec deploy/takserver-api -n takserver -c takserver-api -- cat /conf/CoreConfig.xml 2>/dev/null |
  python3 "${here}/summarize-coreconfig.py" || echo "takserver-api: CoreConfig unreadable"
echo "::endgroup::"

echo "::group::takserver-api stack of the protocol_version failure"
k logs deploy/takserver-api -n takserver -c takserver-api --tail=4000 2>/dev/null |
  grep -B2 -A45 'protocol_version' | grep -vE 'ExceptionTranslationFilter|FilterChainProxy|OncePerRequestFilter|org.apache.(catalina|coyote|tomcat)|java.base/(java.lang|sun.nio)' |
  head -70 | redact || true
echo "::endgroup::"

# Say whether the cluster Secret and each rendered file have a client secret.
# The values are not printed. Keycloak is not called with the secret.
echo "::group::takserver OIDC client secret versus the rendered file"
k get secret takserver-sso -n takserver \
  -o jsonpath='secret created={.metadata.creationTimestamp} resourceVersion={.metadata.resourceVersion}{"\n"}' 2>&1 || true
k get pods -n takserver -o custom-columns=NAME:.metadata.name,STARTED:.status.startTime --no-headers 2>&1 || true
k get secret takserver-sso -n takserver -o jsonpath='{.data.TAK_OIDC_CLIENT_SECRET}' 2>/dev/null |
  python3 "${here}/summarize-coreconfig.py" --b64 || echo "cluster-secret: unreadable"
for d in config messaging api; do
  echo "takserver-${d}:"
  k exec "deploy/takserver-${d}" -n takserver -c "takserver-${d}" -- cat /conf/CoreConfig.xml 2>/dev/null |
    python3 "${here}/summarize-coreconfig.py" || echo "takserver-${d}: CoreConfig unreadable"
done
echo "::endgroup::"
