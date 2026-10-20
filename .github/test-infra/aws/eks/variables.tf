# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

variable "name" {
  description = "Cluster name. Unused until cluster resources are added."
  type        = string
  default     = "takserver"
}

variable "region" {
  description = "AWS region. Unused until cluster resources are added."
  type        = string
  default     = "us-gov-west-1"
}
