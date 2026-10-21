# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Header-only tinygltf from depends/, plus the draco headers it includes.
from conans import ConanFile


class TinyGltfConan(ConanFile):
    name = "tinygltf-tak"
    version = "2.4.1"
    license = "MIT"

    def package(self):
        for h in ("json.hpp", "stb_image.h", "stb_image_write.h", "tiny_gltf.h"):
            self.copy(h, dst="include/tinygltf", src=".")
        self.copy("LICENSE", dst=".", src=".")
        self.copy("*.h", dst="include/tinygltf", src="draco-include")
