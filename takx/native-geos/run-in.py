# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Execute exact argv in the private build directory, without shell interpolation."""
import os
import sys
os.chdir(sys.argv[1])
os.execv(sys.argv[2], sys.argv[2:])
