# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 3: secure by default.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/03-secure.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# Ambient mesh: mTLS, no sidecars"
Sleep 500ms
Enter
Sleep 400ms
# caption: Namespace enrolled in the Istio ambient mesh
Type@85ms "kubectl get ns takserver -L istio.io/dataplane-mode"
Sleep 350ms
Enter
Sleep 2500ms
Type@65ms "# Policies generated from the Package CR"
Sleep 700ms
Enter
Sleep 400ms
# caption: Network and authorization policies generated from the CR
Type@90ms "kubectl get netpol,authorizationpolicy -n takserver | tail -8"
Sleep 450ms
Enter
Sleep 4s
Type@75ms "# SSO secret and TAK certs are made at deploy time"
Sleep 600ms
Enter
Sleep 400ms
# caption: SSO client secret and TAK certs created at deploy time
Type@80ms "kubectl get secrets,jobs -n takserver | grep -Ei 'NAME|sso|cert'"
Sleep 400ms
Enter
Sleep 3500ms
# caption: CI workflows include CodeQL, dependency review, scan, cosign, Scorecard
Type@70ms "ls .github/workflows"
Sleep 500ms
Enter
Sleep 3s
