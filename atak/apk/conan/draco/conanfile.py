# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Static draco built by prebuild.sh for one Android ABI.
import os
from conans import ConanFile

ABI = {"armv8": "arm64-v8a", "armv7": "armeabi-v7a", "x86": "x86", "x86_64": "x86_64"}


class DracoConan(ConanFile):
    name = "draco"
    version = "1.5.7"
    settings = "os", "compiler", "build_type", "arch"

    def package(self):
        b = "build-android-" + ABI[str(self.settings.arch)]
        self.copy("*.h", dst="include/draco", src="src/draco")
        self.copy("draco_features.h", dst="include/draco", src=os.path.join(b, "draco"))
        self.copy("*.a", dst="lib", src=b, keep_path=False)

    def package_info(self):
        self.cpp_info.libs = ["draco"]
