# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 2: platform integration through the UDS Package custom resource.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/02-package-cr.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# One Package CR asks UDS Core for SSO, ingress and policy"
Sleep 500ms
Enter
Sleep 400ms
# caption: Package CR reconciled by the UDS Operator
# zoom: 0,0,1.6
Type@85ms "kubectl get packages -A -o custom-columns=NAME:.metadata.name,PHASE:.status.phase"
Sleep 350ms
Enter
Sleep 2600ms
# caption: Operator status for the takserver Package
Type@65ms "kubectl get package takserver -n takserver -o yaml | yq '.status | del(.conditions)'"
Sleep 700ms
Enter
Sleep 3200ms
