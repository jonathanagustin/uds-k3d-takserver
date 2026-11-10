<!-- Copyright 2026 uds-takserver authors -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Ephemeral cluster identity diagnostics

Staged acceptance still requires the exact `kube-system` namespace UID read
through the selected context to equal the UID read inside the owned local node.
A failed node-side read stops marker creation and acceptance. No alternate
identity, retry or skipped comparison is permitted.

The node-side read invokes `docker exec k3d-uds-server-0 kubectl` directly,
matching the selected
[Core v1.16.0 checkpoint source](https://github.com/defenseunicorns/uds-core/blob/v1.16.0/packages/checkpoint-dev/checkpoint.sh).
Its cleanup and checkpoint preparation consistently invoke the node's direct
`kubectl` binary. This aligns the guard with that release's supported invocation;
it does not prove why the prior `k3s kubectl` invocation failed.

Only failure of that fixed node-side command emits a diagnostic: the constant
stage, exit status (or timeout), stderr byte count and an allowlisted error
classification. Stderr above 64 KiB is omitted; otherwise the existing log
redactor processes the entire stream before classification. Credential-bearing
streams and invalid text are classified as omitted. No stderr text, stdout,
environment, kubeconfig or Docker inspection data is published. Unknown errors
remain `unclassified`; classifications identify signatures, not established
runtime causes. The existing 45-second command deadline is unchanged.

Official [K3s v1.37.1+k3s1 multicall source](https://github.com/k3s-io/k3s/blob/v1.37.1%2Bk3s1/cmd/k3s/main.go)
registers `kubectl`, as does its
[server entry point](https://github.com/k3s-io/k3s/blob/v1.37.1%2Bk3s1/cmd/server/main.go).
The [kubectl entry point](https://github.com/k3s-io/k3s/blob/v1.37.1%2Bk3s1/pkg/kubectl/main.go)
honors explicit kubeconfig arguments or `KUBECONFIG`, otherwise selecting
`server.HomeKubeConfig` when available. These source paths establish supported
upstream invocation and configuration behavior, not the contents or behavior of
the restored checkpoint image. The first staged trial's discarded stderr does
not establish an unavailable subcommand, kubeconfig problem or TLS failure.
