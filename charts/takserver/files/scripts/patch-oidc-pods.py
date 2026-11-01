#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Add the startup and trust init containers the upstream chart cannot express.

The stock Deployments have no initContainer or extra volume values. This
runs after Helm, reads the image names Helm already rendered (including the
Zarf registry rewrite), and patches the wait-deps and import-trust init
containers, the probes, and the rollout strategy onto the TAK Deployments.

It does not render the OIDC client secret. The takserver-oidc admission
module adds that init container to each TAK pod when the pod is created, so
no pod, including one created before this script runs, starts without it.
"""

import json
import re
import shlex
import subprocess
import sys
import tempfile
import time

NAMESPACE = "takserver"


def kubectl_cmd():
    configured = os_env("KUBECTL")
    if configured:
        return shlex.split(configured)
    if shutil_which("kubectl"):
        return ["kubectl"]
    if shutil_which("zarf"):
        return ["zarf", "tools", "kubectl"]
    return ["./zarf", "tools", "kubectl"]


def os_env(name):
    import os

    return os.environ.get(name, "")


def shutil_which(name):
    import shutil

    return shutil.which(name)


def kc(*args, check=True, attempts=5):
    result = None
    for attempt in range(attempts):
        result = subprocess.run(
            kubectl_cmd() + list(args),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode == 0 or not check:
            return result
        transient = (
            "Unable to connect",
            "unexpected EOF",
            "ServiceUnavailable",
            "connection refused",
        )
        if attempt + 1 < attempts and any(part in result.stderr for part in transient):
            time.sleep(3)
            continue
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def scale_deploy(name, replicas):
    print(f"scaling deployment/{name} to {replicas}")
    kc("scale", f"deploy/{name}", "-n", NAMESPACE, f"--replicas={replicas}")


# A slow process that is still starting is not one of these. The rollout
# timeout still applies in that case.
FATAL_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "OOMKilled",
}


# wait-deps fails closed after its bound (wait-deps.sh) and the kubelet restarts
# it, so its restarts and CrashLoopBackOff mean "Config is not Ready yet", not
# a broken pod. A slow runner can need several rounds. Image and OOM faults on
# it are still fatal, and the rollout timeout still applies.
RETRYING_INITS = {"wait-deps"}


def container_fault(status):
    restarts = status.get("restartCount") or 0
    state = status.get("state") or {}
    waiting = state.get("waiting") or {}
    terminated = state.get("terminated") or {}
    last = (status.get("lastState") or {}).get("terminated") or {}
    reason = waiting.get("reason") or terminated.get("reason") or last.get("reason") or ""
    retrying = status.get("name") in RETRYING_INITS
    if reason in FATAL_REASONS and not (retrying and reason == "CrashLoopBackOff"):
        return reason
    if restarts >= 3 and not retrying:
        return f"restartCount={restarts}"
    return ""


def find_faults(pod_list):
    faults = []
    for pod in pod_list.get("items") or []:
        meta = pod.get("metadata") or {}
        if meta.get("deletionTimestamp"):
            continue
        name = meta.get("name") or ""
        app = (meta.get("labels") or {}).get("app") or ""
        if not (name.startswith("takserver-") or str(app).startswith("takserver")):
            continue
        status = pod.get("status") or {}
        containers = []
        containers.extend(status.get("initContainerStatuses") or [])
        containers.extend(status.get("containerStatuses") or [])
        for item in containers:
            fault = container_fault(item)
            if fault:
                faults.append((name, item.get("name") or "", fault))
    return faults


def dump_faults(faults):
    for name, container, fault in faults:
        print(f"fail-fast: pod/{name} container {container}: {fault}", flush=True)
        described = kc("describe", "pod", name, "-n", NAMESPACE, check=False)
        sys.stderr.write(described.stdout[-12000:])
        sys.stderr.write(described.stderr[-2000:])
        logs = kc(
            "logs",
            name,
            "-n",
            NAMESPACE,
            "-c",
            container,
            "--previous",
            "--tail=160",
            check=False,
        )
        if not logs.stdout.strip():
            logs = kc(
                "logs",
                name,
                "-n",
                NAMESPACE,
                "-c",
                container,
                "--tail=160",
                check=False,
            )
        sys.stderr.write(logs.stdout[-12000:])
        sys.stderr.write(logs.stderr[-2000:])


def assert_no_faults():
    result = kc("get", "pods", "-n", NAMESPACE, "-o", "json", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return
    faults = find_faults(json.loads(result.stdout))
    if not faults:
        return
    dump_faults(faults)
    raise SystemExit("a TAK pod failed; not waiting out the rollout timeout")


def wait_gone(app, seconds=180):
    deadline = time.time() + seconds
    while time.time() < deadline:
        result = kc(
            "get",
            "pods",
            "-n",
            NAMESPACE,
            "-l",
            f"app={app}",
            "--field-selector=status.phase!=Succeeded",
            "--no-headers",
            check=False,
        )
        if result.returncode == 0 and not result.stdout.strip():
            print(f"{app} pods are gone", flush=True)
            return
        time.sleep(3)
    raise SystemExit(f"{app} pods did not terminate within {seconds}s")


def dump_wait_deps():
    # wait-deps retries are not faults (container_fault), so a rollout that
    # never finishes has no other record of what the init container waited on.
    result = kc("get", "pods", "-n", NAMESPACE, "-o", "json", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return
    for pod in json.loads(result.stdout).get("items") or []:
        pod_name = (pod.get("metadata") or {}).get("name") or ""
        inits = (pod.get("status") or {}).get("initContainerStatuses") or []
        if not pod_name.startswith("takserver-") or not any(i.get("name") == "wait-deps" for i in inits):
            continue
        for flags in (["--previous"], []):
            logs = kc("logs", pod_name, "-n", NAMESPACE, "-c", "wait-deps", "--tail=60", *flags, check=False)
            if logs.stdout.strip():
                sys.stderr.write(f"wait-deps logs for pod/{pod_name}:\n{logs.stdout[-4000:]}\n")
                break


def wait_rollout(kind, name, timeout):
    deadline = time.time() + timeout
    resource = f"{kind}/{name}"
    print(f"waiting for {resource}", flush=True)
    while time.time() < deadline:
        assert_no_faults()
        result = kc(
            "rollout",
            "status",
            resource,
            "-n",
            NAMESPACE,
            "--timeout=20s",
            check=False,
        )
        if result.returncode == 0:
            assert_no_faults()
            return
        err = result.stderr or ""
        if "exceeded its progress deadline" in err:
            assert_no_faults()
            sys.stderr.write(err)
            raise SystemExit(f"{resource} exceeded its progress deadline")
        if "timed out waiting for the condition" in err:
            continue
        if any(
            part in err
            for part in ("Unable to connect", "unexpected EOF", "ServiceUnavailable", "connection refused")
        ):
            time.sleep(3)
            continue
        if err.strip():
            sys.stderr.write(err)
            raise SystemExit(f"{resource} rollout failed")
    dump_wait_deps()
    raise SystemExit(f"{resource} was not ready within {int(timeout)}s")


def rollout(deploy):
    wait_rollout("deployment", deploy, 1200)


def json_patch(kind, name, ops):
    kc(
        "patch",
        kind,
        name,
        "-n",
        NAMESPACE,
        "--type=json",
        "-p",
        json.dumps(ops),
    )


def set_inits(kind, name, inits):
    current = kc(
        "get",
        kind,
        name,
        "-n",
        NAMESPACE,
        "-o",
        "jsonpath={.spec.template.spec.initContainers}",
    )
    op = "replace" if current.stdout.strip() else "add"
    json_patch(kind, name, [{"op": op, "path": "/spec/template/spec/initContainers", "value": inits}])


def force_automount(kind, name):
    current = kc(
        "get",
        kind,
        name,
        "-n",
        NAMESPACE,
        "-o",
        "jsonpath={.spec.template.spec.automountServiceAccountToken}",
    )
    op = "replace" if current.stdout.strip() else "add"
    json_patch(
        kind,
        name,
        [{"op": op, "path": "/spec/template/spec/automountServiceAccountToken", "value": True}],
    )


def wait_init(image, mode):
    return {
        "name": "wait-deps",
        "image": image,
        "imagePullPolicy": "IfNotPresent",
        "command": ["bash", "/scripts/wait-deps.sh", mode],
        "volumeMounts": [
            {"name": "oidc-script", "mountPath": "/scripts", "readOnly": True},
        ],
        "resources": {
            "requests": {"cpu": "20m", "memory": "64Mi"},
            "limits": {"cpu": "200m", "memory": "128Mi"},
        },
    }


def tcp_probes(port, ready_script):
    # 80 * 10s covers the 180s Ignite wait, the 300s Config wait, and
    # another 300s for the process. startupProbe holds liveness off.
    # The readiness command is repeated so a replace cannot drop it.
    # timeoutSeconds is above the 3s nc in that script.
    return {
        "startupProbe": {
            "tcpSocket": {"port": port},
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 80,
        },
        "livenessProbe": {
            "tcpSocket": {"port": port},
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 6,
        },
        "readinessProbe": {
            "exec": {"command": [ready_script]},
            "timeoutSeconds": 10,
            "periodSeconds": 10,
        },
    }


def exec_startup(script):
    return {
        "startupProbe": {
            "exec": {"command": [script]},
            "periodSeconds": 10,
            "timeoutSeconds": 10,
            "failureThreshold": 80,
        },
        "readinessProbe": {
            "exec": {"command": [script]},
            "timeoutSeconds": 10,
            "periodSeconds": 10,
        },
    }


def container_name(deploy):
    result = kc(
        "get",
        "deploy",
        "-n",
        NAMESPACE,
        deploy,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].name}",
    )
    name = result.stdout
    if not name:
        raise SystemExit(f"{deploy} has no container")
    return name


def container_image(deploy):
    result = kc(
        "get",
        "deploy",
        "-n",
        NAMESPACE,
        deploy,
        "-o",
        "jsonpath={.spec.template.spec.containers[0].image}",
    )
    image = result.stdout.strip()
    if not image:
        raise SystemExit(f"{deploy} has no image")
    return image


def strategic_patch(deploy, body):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(body, handle)
        path = handle.name
    print(f"patching deployment/{deploy}")
    kc("patch", "deploy", deploy, "-n", NAMESPACE, "--type", "strategic", "--patch-file", path)
    images = kc(
        "get",
        "deploy",
        "-n",
        NAMESPACE,
        deploy,
        "-o",
        "jsonpath={.spec.template.spec.containers[*].image}",
    ).stdout.split()
    if len(images) != 1:
        raise SystemExit(f"{deploy} has {len(images)} containers after the patch: {images}")


def script_volumes():
    return [
        {"name": "oidc-script", "configMap": {"name": "takserver-oidc-render"}},
    ]


def pod_meta():
    return {
        "labels": {"uds.dev/oidc-reload": "takserver"},
        "annotations": {"takserver.uds.dev/oidc-render": str(int(time.time()))},
    }


def recreate_strategy():
    # A stored RollingUpdate spec is invalid once type is Recreate.
    return {"type": "Recreate", "rollingUpdate": None}


def trust_container():
    # The JVM reads this store for https://sso.<domain>. import_init fills it.
    return {
        "env": [
            {
                "name": "JAVA_TOOL_OPTIONS",
                "value": "-Djavax.net.ssl.trustStore=/trust/cacerts -Djavax.net.ssl.trustStorePassword=changeit",
            }
        ],
        "volumeMounts": [
            {"name": "jvm-trust", "mountPath": "/trust"},
        ],
    }


def trust_volumes():
    return [
        {"name": "jvm-trust", "emptyDir": {}},
        {
            "name": "uds-trust",
            "configMap": {
                "name": "uds-trust-bundle",
                "optional": True,
            },
        },
    ]


def patch_config_owner(deploy, image, wait_mode, probes, trust_host=None):
    # trust_host set: the JVM also gets the trust store for the issuer.
    scale_deploy(deploy, 1)
    name = container_name(deploy)
    container = {"name": name, **probes}
    volumes = script_volumes()
    inits = [wait_init(image, wait_mode)]
    if trust_host:
        container.update(trust_container())
        volumes = volumes + trust_volumes()
        inits.append(import_init(image, trust_host))
    strategic_patch(
        deploy,
        {
            "spec": {
                # Recreate avoids a surge pod on the small test node.
                # The startup probe budget is 800s. The default progress
                # deadline is 600s and fails the rollout before that.
                "progressDeadlineSeconds": 1200,
                "strategy": recreate_strategy(),
                "template": {
                    "metadata": pod_meta(),
                    "spec": {
                        "containers": [container],
                        "volumes": volumes,
                    },
                }
            }
        },
    )
    # JSON replace keeps wait-deps first. A strategic merge appends it.
    set_inits("deploy", deploy, inits)
    rollout(deploy)


def issuer_host():
    result = kc(
        "get",
        "cm",
        "-n",
        NAMESPACE,
        "core-config",
        "-o",
        r"jsonpath={.data.CoreConfig\.xml}",
    )
    match = re.search(r'configurationUri="https://([^"/]+)', result.stdout)
    if not match:
        raise SystemExit("CoreConfig has no openId configurationUri")
    return match.group(1)


def patch_api(config_image, host):
    scale_deploy("takserver-api", 1)
    name = container_name("takserver-api")
    strategic_patch(
        "takserver-api",
        {
            "spec": {
                # Recreate avoids a surge pod on the small test node.
                # The startup probe budget is 800s. The default progress
                # deadline is 600s and fails the rollout before that.
                "progressDeadlineSeconds": 1200,
                "strategy": recreate_strategy(),
                "template": {
                    "metadata": pod_meta(),
                    "spec": {
                        # Earlier versions pinned the issuer host to the
                        # tenant gateway ClusterIP here. The in-cluster DNS
                        # rewrite (zarf.yaml) answers that name now. null
                        # removes the old alias on upgrade.
                        "hostAliases": None,
                        "containers": [
                            {
                                "name": name,
                                **trust_container(),
                                **tcp_probes(8443, "/api-readiness.sh"),
                            }
                        ],
                        "volumes": script_volumes() + trust_volumes(),
                    },
                }
            }
        },
    )
    set_inits(
        "deploy",
        "takserver-api",
        [
            wait_init(config_image, "config"),
            import_init(config_image, host),
        ],
    )
    rollout("takserver-api")


def import_init(config_image, host):
    return {
        "name": "import-trust",
        # Config image has keytool and openssl. The API image does not have
        # openssl. Slim core does not publish a trust bundle, so this
        # container reads the issuer certificate with openssl.
        "image": config_image,
        "imagePullPolicy": "IfNotPresent",
        "command": ["bash", "/scripts/import-trust.sh"],
        "env": [{"name": "ISSUER_HOST", "value": host}],
        "volumeMounts": [
            {"name": "oidc-script", "mountPath": "/scripts", "readOnly": True},
            {"name": "uds-trust", "mountPath": "/bundle", "readOnly": True},
            {"name": "jvm-trust", "mountPath": "/trust"},
        ],
        "resources": {
            "requests": {"cpu": "20m", "memory": "64Mi"},
            "limits": {"cpu": "200m", "memory": "256Mi"},
        },
    }


def patch_plugins(config_image):
    scale_deploy("takserver-plugins", 1)
    name = container_name("takserver-plugins")
    strategic_patch(
        "takserver-plugins",
        {
            "spec": {
                "progressDeadlineSeconds": 1200,
                "strategy": recreate_strategy(),
                "template": {
                    "metadata": pod_meta(),
                    "spec": {
                        "containers": [
                            {
                                "name": name,
                                # The chart template copies the API CPU limit and
                                # drops memory. 128m is the plugin heap. Steady
                                # working set on run 40174810574 was 263Mi
                                # amd64 and 260Mi arm64, so the request is
                                # 320Mi and the limit is 512Mi.
                                "resources": {
                                    "requests": {"memory": "320Mi"},
                                    "limits": {"memory": "512Mi"},
                                },
                            }
                        ],
                        "volumes": [
                            {
                                "name": "oidc-script",
                                "configMap": {"name": "takserver-oidc-render"},
                            }
                        ],
                    },
                }
            }
        },
    )
    # Plugins need the Ignite services published by config, messaging, and
    # the API. It is rolled after those three so a restart cannot keep a
    # stale Ignite proxy from an earlier generation.
    set_inits("deploy", "takserver-plugins", [wait_init(config_image, "services")])
    rollout("takserver-plugins")


def tune_ignite_server():
    name = "takserver-ignite-configmap"
    result = kc("get", "cm", "-n", NAMESPACE, name, "-o", "json")
    data = json.loads(result.stdout)
    xml = data["data"]["ignite-config.xml"]
    original = xml
    needle = '<bean class="org.apache.ignite.spi.discovery.tcp.TcpDiscoverySpi">'
    # Leave localAddress unset. TcpDiscoverySpi binds every interface when
    # it is unset, and advertises a real address. 0.0.0.0 is resolved as the
    # wildcard and then registered as the node address.
    if 'name="networkTimeout"' not in xml:
        if needle not in xml:
            raise SystemExit("Ignite server config has no TcpDiscoverySpi")
        xml = xml.replace(
            needle,
            needle + '\n                    <property name="networkTimeout" value="15000"/>',
            1,
        )
    if 'name="failureDetectionTimeout"' not in xml:
        marker = '<property name="discoverySpi">'
        if marker not in xml:
            raise SystemExit("Ignite server config has no discoverySpi")
        xml = xml.replace(
            marker,
            '<property name="failureDetectionTimeout" value="30000"/>\n            ' + marker,
            1,
        )
    if xml == original:
        print("Ignite server config already sets the SPI timeouts", flush=True)
        return
    patch = {"data": {"ignite-config.xml": xml}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(patch, handle)
        path = handle.name
    kc("patch", "cm", name, "-n", NAMESPACE, "--type", "merge", "--patch-file", path)
    if 'name="localAddress"' in xml or 'name="enabled"' in xml:
        raise SystemExit("Ignite server config has a property the 2.17 classes do not use")
    print("Ignite server config sets networkTimeout 15000 and failureDetectionTimeout 30000")


def main():
    present = kc("get", "cm", "-n", NAMESPACE, "takserver-oidc-render", check=False)
    if present.returncode != 0:
        print("OIDC render ConfigMap is absent. Skipping.")
        return
    config_image = container_image("takserver-config")
    host = issuer_host()
    print(f"OIDC issuer host {host}. In-cluster DNS sends it to the tenant gateway.")
    # Stop the consumers before Ignite restarts. On the small test node a
    # second Ignite start next to four TAK heaps drops the API server.
    # Plugins is last when they come back, because it uses the others.
    for deploy, app in (
        ("takserver-plugins", "takserver-plugins"),
        ("takserver-api", "takserver-api"),
        ("takserver-messaging", "takserver-messaging"),
        ("takserver-config", "takserver-config"),
    ):
        scale_deploy(deploy, 0)
        wait_gone(app)
    force_automount("statefulset", "takserver-ignite")
    tune_ignite_server()
    kc("rollout", "restart", "statefulset/takserver-ignite", "-n", NAMESPACE)
    # The StatefulSet has no readiness probe, so rollout status returns when
    # the process has been started. Keep polling for a crash after that.
    wait_rollout("statefulset", "takserver-ignite", 600)
    deadline = time.time() + 20
    while time.time() < deadline:
        assert_no_faults()
        time.sleep(2)
    assert_no_faults()
    for deploy in (
        "takserver-config",
        "takserver-messaging",
        "takserver-api",
        "takserver-plugins",
    ):
        force_automount("deploy", deploy)
    patch_config_owner(
        "takserver-config",
        config_image,
        "ignite",
        exec_startup("/config-readiness.sh"),
    )
    patch_config_owner(
        "takserver-messaging",
        config_image,
        "config",
        tcp_probes(8089, "/messaging-readiness.sh"),
        # 8089 checks the bearer token stored with a certificate enrolled on
        # 8446, so messaging fetches the issuer's keys over HTTPS as well.
        trust_host=host,
    )
    patch_api(config_image, host)
    patch_plugins(config_image)


if __name__ == "__main__":
    main()
