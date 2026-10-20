# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 1: the upstream app, packaged for UDS.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/01-package.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# Upstream TAK chart, cloned by git tag. Not forked."
Sleep 500ms
Enter
Sleep 400ms
# caption: Upstream Helm chart pulled by git tag, not forked
Type@85ms "yq '.components[0].charts[] | [.name, .url // .localPath, .version] | @tsv' common/zarf.yaml"
Sleep 350ms
Enter
Sleep 3500ms
Type@65ms "# Deployed as one UDS bundle with UDS Core"
Sleep 700ms
Enter
Sleep 400ms
# caption: Zarf packages deployed by the UDS bundle
Type@90ms "uds zarf package list -l warn"
Sleep 450ms
Enter
Sleep 4s
