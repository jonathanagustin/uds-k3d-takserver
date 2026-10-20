# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 2: platform integration through the UDS Package custom resource.
Output "demo/out/02-package-cr.mp4"
Source "demo/settings.tape"

Hide
Type "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type "# One Package CR asks UDS Core for SSO, ingress and network policy"
Enter
Sleep 600ms
Type "kubectl get packages.uds.dev -A"
Enter
Sleep 3s
Type "kubectl get package takserver -n takserver -o yaml | yq '.spec.network.expose[] | [.gateway, .host, .port] | @tsv'"
Enter
Sleep 3500ms
Type "kubectl get package takserver -n takserver -o yaml | yq '.status | del(.conditions)'"
Enter
Sleep 5s
