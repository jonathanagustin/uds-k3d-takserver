# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""cacheConfig=false has to keep a node's own CoreConfig.

Upstream DistributedConfiguration.init() in 5.7-RELEASE-14 loads the Ignite
cache only when cacheConfig is true, then registers the continuous-query
listener either way. IgniteReconnectEventHandler.registerListener runs that
callback immediately. The callback calls setConfiguration and saveChanges, so
the cached file replaces the local one. The reported failure was an OIDC
client secret of 25 characters on the config pod and 86 in the cluster.

The image patch moves the listener inside the isCacheConfig check.
"""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / ".github" / "container-and-chart" / "docker" / "cacheconfig-listener.patch"
FIXTURE = ROOT / "tests" / "fixtures" / "distributed-configuration-init.java"
CORECONFIG = ROOT / "charts" / "takserver" / "files" / "config" / "CoreConfig.xml"


def hunk_sides(patch):
    old = []
    new = []
    in_hunk = False
    for line in patch.splitlines(keepends=True):
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        elif line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
        else:
            break
    if not old or not new:
        raise ValueError("the patch has no hunk")
    return "".join(old), "".join(new)


def listener_is_guarded(java):
    """True when registerListener sits inside the isCacheConfig if."""
    cache = java.index("isCacheConfig()")
    open_brace = java.index("{", cache)
    depth = 0
    close = None
    for index in range(open_brace, len(java)):
        char = java[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                close = index
                break
    if close is None:
        raise ValueError("the isCacheConfig if has no closing brace")
    listener = java.index("registerListener")
    return open_brace < listener < close


def kept_secret(cache_config, local_secret, cached_secret, patched):
    """What this node saves after another node publishes cached_secret.

    Startup adoption is the loadConfigFromCache path and runs only when
    cacheConfig is true. The listener is the runtime path. Upstream registers
    it even when cacheConfig is false.
    """
    secret = local_secret
    if cache_config:
        secret = cached_secret
    registers_listener = cache_config if patched else True
    if registers_listener:
        secret = cached_secret
    return secret


class CacheConfigPatchTests(unittest.TestCase):
    def test_upstream_init_registers_the_listener_when_cacheconfig_is_false(self):
        upstream = FIXTURE.read_text(encoding="utf-8")
        self.assertIn("loadConfigFromCache()", upstream)
        self.assertFalse(listener_is_guarded(upstream))

    def test_the_patch_moves_the_listener_inside_the_check(self):
        old, new = hunk_sides(PATCH.read_text(encoding="utf-8"))
        self.assertTrue(FIXTURE.read_text(encoding="utf-8").startswith(old))
        self.assertFalse(listener_is_guarded(old))
        self.assertTrue(listener_is_guarded(new))
        self.assertIn("loadConfigFromCache();", new)
        self.assertEqual(new.count("registerListener"), 1)

    def test_a_shorter_secret_from_another_node_does_not_replace_the_local_one(self):
        # Lengths from the report: the config pod had saved 25, the cluster held 86.
        local = "a" * 86
        cached = "b" * 25
        self.assertEqual(kept_secret(False, local, cached, patched=False), cached)
        self.assertEqual(kept_secret(False, local, cached, patched=True), local)
        self.assertEqual(kept_secret(True, local, cached, patched=True), cached)

    def test_the_shipped_coreconfig_turns_the_cache_off(self):
        text = CORECONFIG.read_text(encoding="utf-8")
        self.assertIn('cacheConfig="false"', text)
        self.assertIn('enabled="true"', text)


if __name__ == "__main__":
    unittest.main()
