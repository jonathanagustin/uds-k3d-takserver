# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 3: secure by default.
Output "demo/out/03-secure.mp4"
Source "demo/settings.tape"

Hide
Type "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type "# Istio ambient mesh: mTLS for every pod, no sidecars"
Enter
Sleep 600ms
Type "kubectl get ns takserver -L istio.io/dataplane-mode"
Enter
Sleep 2500ms
Type "# Default deny. The operator generates each allow rule from the Package CR"
Enter
Sleep 600ms
Type "kubectl get networkpolicies -n takserver --no-headers | wc -l"
Enter
Sleep 2s
Type "kubectl get authorizationpolicies -n takserver"
Enter
Sleep 3500ms
Type "# Keycloak client secret and TAK certificates are created at deploy time"
Enter
Sleep 600ms
Type "kubectl get secrets,jobs -n takserver | grep -Ei 'NAME|sso|cert'"
Enter
Sleep 3500ms
Type "# CI security gates on this repo"
Enter
Sleep 600ms
Type "grep -h '^name:' .github/workflows/{codeql,dependency-review,scan,cosign,scorecard}.yaml"
Enter
Sleep 3s
