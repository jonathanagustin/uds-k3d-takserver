# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

# Header-only Khronos EGL and OpenGL API headers from the atak-civ tree.
from conans import ConanFile


class KhronosConan(ConanFile):
    name = "khronos"
    version = "1.0"
    no_copy_source = True

    def package(self):
        self.copy("*.h", dst="EGL/api", src="EGL/api")
        self.copy("*.h", dst="OpenGL/api", src="OpenGL/api")

    def package_info(self):
        self.cpp_info.includedirs = ["EGL/api", "OpenGL/api"]
