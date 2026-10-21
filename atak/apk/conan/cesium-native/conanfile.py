# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Static cesium-native (and its vcpkg dependencies) from build-android.sh.
import os
from conans import ConanFile

ABI = {"armv8": "arm64-v8a", "armv7": "armeabi-v7a", "x86": "x86", "x86_64": "x86_64"}


class CesiumNativeConan(ConanFile):
    name = "cesium-native"
    version = "0.40.1"
    settings = "os", "compiler", "build_type", "arch"

    def package(self):
        b = os.path.join("build", "android-" + ABI[str(self.settings.arch)])
        self.copy("*", dst="include", src=os.path.join(b, "include"))
        self.copy("*.a", dst="lib", src=os.path.join(b, "lib"), keep_path=False)
        self.copy("*.a", dst="lib", src=os.path.join(b, "lib64"), keep_path=False)

    def package_info(self):
        self.cpp_info.libdirs = ["lib"]
        self.cpp_info.includedirs = ["include"]
