# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 5: other clusters. These are scaffolds and are labeled that way.
Output "demo/out/05-clusters.mp4"
Source "demo/settings.tape"

Hide
Type "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type "# EKS, RKE2 and AKS: OpenTofu scaffolds, manual and not yet tested"
Enter
Sleep 600ms
Type "find .github/test-infra -name main.tf | sort"
Enter
Sleep 2500ms
Type "sed -n '4,6p' .github/test-infra/aws/rke2/main.tf"
Enter
Sleep 4s
