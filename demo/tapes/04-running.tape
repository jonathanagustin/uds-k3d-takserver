# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 4: running, clustered, and healthy.
Output "demo/out/04-running.mp4"
Source "demo/settings.tape"

Hide
Type "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type "# Clustered TAK: config, messaging, API, plugins, Ignite, Postgres, NATS"
Enter
Sleep 600ms
Type "kubectl get pods -n takserver"
Enter
Sleep 4s
Type "# Ignite cluster membership, straight from the logs"
Enter
Sleep 600ms
Type "kubectl logs sts/takserver-ignite -n takserver | grep -o 'Topology snapshot.*' | tail -1"
Enter
Sleep 3s
Type "# Anonymous web request: TAK hands off to Keycloak"
Enter
Sleep 600ms
Type "curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}' https://takserver.uds.dev/; echo"
Enter
Sleep 3500ms
