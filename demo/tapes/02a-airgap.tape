# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Air-gapped install: images come from the Zarf registry in the cluster, and
# the released package carries its SBOMs.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/02a-airgap.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# Every TAK image runs from the Zarf registry inside the cluster"
Sleep 500ms
Enter
Sleep 400ms
# caption: Image references rewritten to the in-cluster Zarf registry: no pulls from the internet
# fast
Type@80ms "kubectl get pods -n takserver -o custom-columns=POD:.metadata.name,IMAGE:.spec.containers[0].image"
Sleep 400ms
Enter
Sleep 3200ms
# caption: The registry holds what the package brought with it
Type@80ms "uds zarf tools registry catalog | head -12"
Sleep 400ms
Enter
Wait@60s /takserver \$\s*$/
Sleep 2600ms
Type@70ms "# The released package carries its SBOMs"
Sleep 500ms
Enter
Sleep 400ms
# caption: SBOMs travel inside the signed release package, readable offline
# fast
Type@35ms "uds zarf package inspect sbom oci://ghcr.io/jonathanagustin/uds-k3d-takserver/takserver:0.3.0-upstream --certificate-identity-regexp $RELEASE_WORKFLOW --certificate-oidc-issuer $RELEASE_ISSUER --output /tmp/sbom && ls /tmp/sbom/takserver | grep json"
Sleep 400ms
Enter
Wait@180s /takserver \$\s*$/
Sleep 3000ms
