# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 1: the upstream app, packaged for UDS.
Output "demo/out/01-package.mp4"
Source "demo/settings.tape"

Hide
Type "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type "# Upstream TAK Helm chart, cloned by git tag. Not forked, not vendored."
Enter
Sleep 600ms
Type "yq '.components[0].charts[] | [.name, .url // .localPath, .version] | @tsv' common/zarf.yaml"
Enter
Sleep 3s
Type "# Platform settings live in values files, not chart patches"
Enter
Sleep 600ms
Type "ls values/"
Enter
Sleep 2s
Type "# The UDS bundle: UDS Core plus the TAK Zarf package"
Enter
Sleep 600ms
Type "yq '.packages[] | [.name, .ref] | @tsv' bundle/uds-bundle.yaml"
Enter
Sleep 2500ms
Type "uds zarf package list"
Enter
Sleep 4s
