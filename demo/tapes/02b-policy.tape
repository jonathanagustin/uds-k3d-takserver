# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Policy at work: what UDS admission changed on a TAK pod, and the one
# narrowly scoped exemption.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/02b-policy.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# UDS policy at admission: what it changed on a TAK pod"
Sleep 500ms
Enter
Sleep 400ms
# caption: UDS policies mutate every TAK pod at admission and record what they changed
# fast
Type@75ms "kubectl get pods -n takserver -l app=takserver-messaging -o yaml | yq '.items[0].metadata.annotations' | grep -i pepr"
Sleep 400ms
Enter
Sleep 3200ms
# caption: Narrow, documented policy exemption: one policy, one hook pod
Type@80ms "kubectl get exemptions -A"
Sleep 400ms
Enter
Sleep 2200ms
# fast
Type@70ms "kubectl get exemption takserver-db-setup -n uds-policy-exemptions -o yaml | yq '.spec.exemptions[0]'"
Sleep 400ms
Enter
Sleep 3600ms
