# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Chapter 5: other clusters. These are scaffolds and are labeled that way.
# '# caption:' and '# zoom:' lines are read by demo/filters.py, not VHS.
Output "demo/out/05-clusters.mp4"
Source "demo/settings.tape"

Hide
Type@5ms "source demo/shell.sh && clear"
Enter
Sleep 1s
Show

Type@70ms "# EKS, RKE2, AKS: OpenTofu scaffolds, manual, not yet tested"
Sleep 500ms
Enter
Sleep 400ms
# caption: OpenTofu scaffolds for EKS, RKE2 and AKS (not yet tested)
Type@85ms "find .github/test-infra -name main.tf | sort"
Sleep 350ms
Enter
Sleep 2000ms
Type@65ms "sed -n '4,6p' .github/test-infra/aws/rke2/main.tf"
Sleep 700ms
Enter
Sleep 2800ms
