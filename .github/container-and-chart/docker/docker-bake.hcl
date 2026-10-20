# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# One builder stage, then the six runtime targets together.
# build.sh sets REPO, TAG, PLATFORMS, and GRADLE_SEED.

variable "REPO" {
  default = "ghcr.io/jonathanagustin/uds-k3d-takserver"
}

variable "TAG" {
  default = "5.7-RELEASE-14"
}

variable "PLATFORMS" {
  default = "linux/amd64"
}

variable "GRADLE_SEED" {
  default = "gradle-seed"
}

function "platform_list" {
  params = [csv]
  result = split(",", csv)
}

group "default" {
  targets = [
    "takserver-config",
    "takserver-messaging",
    "takserver-api",
    "takserver-plugins",
    "takserver-database-setup",
    "takserver-ignite",
  ]
}

target "_image" {
  # build.sh overrides context with this directory. A bare "." is the
  # process working directory, which is the repository root in CI.
  dockerfile = "Dockerfile"
  context    = "."
  contexts = {
    gradle-seed = GRADLE_SEED
  }
  platforms = platform_list(PLATFORMS)
}

target "takserver-config" {
  inherits = ["_image"]
  target   = "takserver-config"
  tags     = ["${REPO}/takserver-config:${TAG}"]
}

target "takserver-messaging" {
  inherits = ["_image"]
  target   = "takserver-messaging"
  tags     = ["${REPO}/takserver-messaging:${TAG}"]
}

target "takserver-api" {
  inherits = ["_image"]
  target   = "takserver-api"
  tags     = ["${REPO}/takserver-api:${TAG}"]
}

target "takserver-plugins" {
  inherits = ["_image"]
  target   = "takserver-plugins"
  tags     = ["${REPO}/takserver-plugins:${TAG}"]
}

target "takserver-database-setup" {
  inherits = ["_image"]
  target   = "takserver-database-setup"
  tags     = ["${REPO}/takserver-database-setup:${TAG}"]
}

target "takserver-ignite" {
  inherits = ["_image"]
  target   = "takserver-ignite"
  tags     = ["${REPO}/takserver-ignite:${TAG}"]
}

target "gradle-export" {
  inherits = ["_image"]
  target   = "gradle-export"
  output   = ["type=local,dest=/tmp/tak-gradle-export"]
}
