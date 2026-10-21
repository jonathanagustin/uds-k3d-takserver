# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# CloudTAK image. build.sh sets the variables from the upstream/cloudtak
# submodule. `docker buildx bake -f docker-bake.hcl cloudtak` from this
# directory.

variable "REGISTRY" {
  default = "ghcr.io/jonathanagustin/uds-k3d-takserver"
}

variable "CLOUDTAK_VERSION" {
  default = "v13.111.3" # cloudtak-version
}

variable "CLOUDTAK_SRC" {
  default = "../../../upstream/cloudtak"
}

variable "UPSTREAM_SHA" {
  default = ""
}

variable "INPUTS" {
  default = ""
}

# CloudTAK's own Dockerfile, unchanged. Its first stage downloads the
# CloudTAK-Data release zip that upstream pins in that Dockerfile.
target "cloudtak-upstream" {
  context    = CLOUDTAK_SRC
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
}

target "cloudtak" {
  context    = "."
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64"]
  contexts = {
    cloudtak-upstream = "target:cloudtak-upstream"
  }
  args = {
    CLOUDTAK_VERSION = CLOUDTAK_VERSION
    UPSTREAM_SHA     = UPSTREAM_SHA
  }
  labels = {
    "dev.uds-k3d-takserver.inputs" = INPUTS
  }
  tags = ["${REGISTRY}/cloudtak:${CLOUDTAK_VERSION}"]
}
