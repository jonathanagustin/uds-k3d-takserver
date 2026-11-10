# CI agent availability barrier

The upgrade test deploys this gate once after restoring the old checkpoint and
again between the released Core package and the application. It retains the
bounded Deployment/ready-Endpoints/port metadata waits, then performs a live
HTTPS availability request. Restored readiness objects alone can describe old
state; the port assertion only checks metadata and does not send HTTP.

`live-health.py` reads only `zarf/agent-hook` Service and Endpoints, resolves the
ready Pod references, and checks their namespace, name, UID, IP, Service labels,
Running/Ready state and target port 8443. It checks every ready target (at most
eight), ignores `notReadyAddresses`, and rereads Pod identity after each request.
It sends a GET through the existing authenticated kubectl connection:

```text
/api/v1/namespaces/zarf/pods/https:<validated-pod>:8443/proxy/healthz
```

The command must succeed and its body must be exactly `ok`. `kubectl get --raw`
reports successful HTTP responses rather than exposing a separate numeric status;
this gate therefore checks successful-response/exact-body semantics. The pinned
agent 0.88.0 handler explicitly returns HTTP 200 and `ok`. Missing permissions,
errors, timeouts, changed identities and unexpected responses fail closed. No raw
API response or stderr is printed. Retries share a 30-second deadline; requests
have a three-second kubectl timeout and at most four seconds of subprocess time.
The package action adds a 40-second outer bound. There is no recovery mutation.

The caller needs existing `get` permissions for Services, Endpoints, Pods and
`pods/proxy` in `zarf`. This package grants no permissions. Pod proxy is a powerful
API capability; it is used here only for the fixed namespace, port and health
path derived from validated agent targets. No Secret, key or kubeconfig content
is read by the helper, and no port-forward, restart or admission configuration
change is performed.

## TLS and scope

The kubectl-to-API connection uses the caller's existing kubeconfig authentication
and TLS settings. No insecure client flags are added. Kubernetes' built-in Pod
proxy transport uses `InsecureSkipVerify` for its IP-based backend connection;
therefore this test **does not authenticate the agent certificate**. It proves a
live response through that API proxy at that moment, not webhook certificate
trust, Service routing, admission mutation behavior or continued health during
the following deployment. It does not fix or explain later health loss; liveness
termination alone does not prove a panic.

## Packaging and evidence

The helper is included as a package file and copied to
`.cache/upgrade-agent-gate/live-health.py` in the deployment working directory.
The live command is in `onDeploy.after`, after Zarf copies component files;
the earlier native waits remain in `onDeploy.before`. Both standalone and bundle
invocations receive their own packaged helper and do not need the repository's
source path to exist. No images or cluster workloads are added.

Source references reviewed:

- Kubernetes 1.37.0, commit `f54c212e3a2f75d674b717a9b29052b20b60aefc`:
  [Pod proxy GET handler](https://github.com/kubernetes/kubernetes/blob/f54c212e3a2f75d674b717a9b29052b20b60aefc/pkg/registry/core/pod/rest/subresources.go#L43),
  [scheme/name/port resolution and Pod IP checks](https://github.com/kubernetes/kubernetes/blob/f54c212e3a2f75d674b717a9b29052b20b60aefc/pkg/registry/core/pod/strategy.go#L584),
  [GET verb and subresource authorization attributes](https://github.com/kubernetes/kubernetes/blob/f54c212e3a2f75d674b717a9b29052b20b60aefc/staging/src/k8s.io/apiserver/pkg/endpoints/request/requestinfo.go#L175),
  [backend proxy TLS transport](https://github.com/kubernetes/kubernetes/blob/f54c212e3a2f75d674b717a9b29052b20b60aefc/pkg/controlplane/apiserver/config.go#L432).
- Zarf agent 0.88.0, commit `a2dd0bbf96514212a6192f391d2f171ad1d88498`:
  [`/healthz` and HTTPS listener](https://github.com/zarf-dev/zarf/blob/a2dd0bbf96514212a6192f391d2f171ad1d88498/src/internal/agent/start.go#L71).
- Zarf 0.89.0 embedded by UDS CLI 0.41.0, commit
  `6da2a6d7867f355af281e5a33a9d849174c4c2d2`:
  [before/files/after ordering](https://github.com/zarf-dev/zarf/blob/6da2a6d7867f355af281e5a33a9d849174c4c2d2/src/pkg/packager/deploy.go#L562).

Offline validation:

```sh
python3 -B -m unittest tests.test_upgrade_agent_health tests.test_agent_gate -v
```

This exercises live-request selection, stale identities,
wrong namespaces/ports/labels/IPs, readiness, exact bodies, API failures,
timeouts, total retry bounds and original bundle insertion contracts. Unit CI
already discovers `test_upgrade_*.py`. Package creation and archived-helper bytes
can be checked without a cluster. These fixtures are not a live-cluster proof.
