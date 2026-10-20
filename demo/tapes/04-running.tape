# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 4: running, clustered, and healthy.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/04-running.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

# caption: Clustered TAK services and their dependencies
# zoom: 0,0,1.35
Type@70ms "kubectl get pods -n takserver"
Sleep 500ms
Enter
Sleep 3200ms
# typo: cluster
Type@85ms "# Ignite cluster membership, from the logs"
Sleep 350ms
Enter
Sleep 400ms
# caption: Ignite cluster topology from the logs
Type@65ms "kubectl logs sts/takserver-ignite -n takserver | grep -o 'Topology snapshot.*' | tail -1"
Sleep 700ms
Enter
Sleep 2500ms
Type@90ms "# Anonymous request: TAK hands off to Keycloak"
Sleep 450ms
Enter
Sleep 400ms
# caption: Unauthenticated requests redirect to Keycloak
Type@75ms "curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}' https://takserver.uds.dev/; echo"
Sleep 600ms
Enter
Sleep 2500ms
