#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Run an argv in an explicitly owned working directory."""
import os
import sys
os.chdir(sys.argv[1])
os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
