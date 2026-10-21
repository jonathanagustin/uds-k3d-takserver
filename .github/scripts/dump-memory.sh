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
  if [[ -x ./zarf ]]; then
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

# TAK's own OIDC discovery call offers only TLS 1.2, although the JVM probe above
# reaches Keycloak at TLS 1.3. Show the effective TLS settings it reads and the
# stack of the failing call, which names the TAK class that builds that client.
echo "::group::takserver-api effective CoreConfig TLS settings"
k exec deploy/takserver-api -n takserver -c takserver-api -- sh -c \
  'grep -n "tls context\|<tls\|openIdDiscovery\|context=" /conf/CoreConfig.xml 2>&1 | head -20' 2>&1 | tail -25 || true
echo "::endgroup::"

echo "::group::takserver-api stack of the protocol_version failure"
k logs deploy/takserver-api -n takserver -c takserver-api --tail=4000 2>/dev/null |
  grep -B2 -A45 'protocol_version' | grep -vE 'ExceptionTranslationFilter|FilterChainProxy|OncePerRequestFilter|org.apache.(catalina|coyote|tomcat)|java.base/(java.lang|sun.nio)' |
  head -70 || true
echo "::endgroup::"

# unauthorized_client from Keycloak's token endpoint means TAK's rendered client
# secret and Keycloak's disagree. Compare without printing the secret: when the
# secret was last written against when each pod rendered it, whether the pod's
# CoreConfig still holds the cluster's value, and how Keycloak answers those
# credentials (invalid_grant for a bogus code means they are accepted).
echo "::group::takserver OIDC client secret versus Keycloak"
k get secret takserver-sso -n takserver \
  -o jsonpath='secret created={.metadata.creationTimestamp} resourceVersion={.metadata.resourceVersion}{"\n"}' 2>&1 || true
k get pods -n takserver -o custom-columns=NAME:.metadata.name,STARTED:.status.startTime --no-headers 2>&1 || true
sso_secret="$(k get secret takserver-sso -n takserver -o jsonpath='{.data.TAK_OIDC_CLIENT_SECRET}' 2>/dev/null | base64 -d || true)"
fingerprint() { printf '%s' "$1" | sha256sum | cut -c1-8; }
echo "cluster secret: length=${#sso_secret} sha=$(fingerprint "${sso_secret}")"
# TAK nodes share CoreConfig through an Ignite cache and the last writer wins,
# so the API can be using another node's copy of the secret. Compare each file.
for d in config messaging api; do
  if conf="$(k exec "deploy/takserver-${d}" -n takserver -c "takserver-${d}" -- cat /conf/CoreConfig.xml 2>&1)"; then
    val="$(printf '%s' "${conf}" | grep -o 'openIdDiscoveryConfiguration[^>]*' | grep -o ' secret="[^"]*"' | head -1 | sed 's/^ secret="//; s/"$//')"
    echo "takserver-${d}: file ${#conf} bytes, secret length=${#val} sha=$(fingerprint "${val}") placeholder=$(printf '%s' "${val}" | grep -c 'TAK_OIDC')"
  else
    echo "takserver-${d}: could not read /conf/CoreConfig.xml: $(printf '%s' "${conf}" | head -c 200)"
  fi
done
curl -ksS --max-time 20 -X POST https://sso.uds.dev/realms/uds/protocol/openid-connect/token \
  --data-urlencode grant_type=authorization_code --data-urlencode code=bogus \
  --data-urlencode client_id=uds-takserver --data-urlencode "client_secret=${sso_secret}" \
  --data-urlencode redirect_uri=https://takserver.uds.dev/login/redirect 2>&1 | head -c 400 || true
echo
echo "::endgroup::"
