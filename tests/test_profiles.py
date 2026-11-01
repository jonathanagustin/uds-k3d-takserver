# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Profiles are overlays. These checks do not measure a running cluster."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UNITS = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30}


def load(relative):
    with open(ROOT / relative, encoding="utf-8") as handle:
        body = yaml.safe_load(handle)
    if not isinstance(body, dict):
        raise AssertionError(f"{relative} is not a mapping")
    return body


def quantity(value):
    for suffix, factor in UNITS.items():
        if str(value).endswith(suffix):
            return int(float(str(value)[: -len(suffix)]) * factor)
    return int(value)


def replicas(node, path=""):
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = f"{path}{key}"
        if key in ("replicas", "replicaCount"):
            yield here, value
        else:
            yield from replicas(value, here + ".")


class ProfileTests(unittest.TestCase):
    def test_every_replica_count_is_one(self):
        for name in ("small.yaml", "production.yaml"):
            found = list(replicas(load(f"values/profiles/{name}")))
            self.assertGreaterEqual(len(found), 5)
            for path, count in found:
                self.assertEqual(count, 1, path)

    def test_postgres_limit_stays_512mi(self):
        for name in ("small.yaml", "production.yaml"):
            body = load(f"values/profiles/{name}")
            limit = body["postgresql"]["primary"]["resources"]["limits"]["memory"]
            self.assertEqual(quantity(limit), 512 * UNITS["Mi"])

    def test_production_memory_limits_are_at_least_small(self):
        small = load("values/profiles/small.yaml")
        prod = load("values/profiles/production.yaml")
        pairs = (
            (small["takserver"]["api"], prod["takserver"]["api"]),
            (small["takserver"]["config"], prod["takserver"]["config"]),
            (small["ignite"], prod["ignite"]),
            (small["postgresql"]["primary"], prod["postgresql"]["primary"]),
        )
        for left, right in pairs:
            self.assertGreaterEqual(
                quantity(right["resources"]["limits"]["memory"]),
                quantity(left["resources"]["limits"]["memory"]),
            )
        small_ct = load("values/profiles/small-cloudtak.yaml")["resources"]
        prod_ct = load("values/profiles/production-cloudtak.yaml")["resources"]
        for name in ("cloudtak", "sso", "bootstrap", "postgis"):
            self.assertGreaterEqual(
                quantity(prod_ct[name]["limits"]["memory"]),
                quantity(small_ct[name]["limits"]["memory"]),
            )

    def test_small_requests_cover_the_steady_set(self):
        # Run 40174810574, higher arch, working set in MiB.
        steady = {"api": 911, "messaging": 888, "config": 750}
        small = load("values/profiles/small.yaml")["takserver"]
        for name, used in steady.items():
            request = quantity(small[name]["resources"]["requests"]["memory"])
            self.assertGreaterEqual(request, used * UNITS["Mi"])
        ignite = quantity(load("values/profiles/small.yaml")["ignite"]["resources"]["requests"]["memory"])
        self.assertGreaterEqual(ignite, 488 * UNITS["Mi"])

    def test_documented_limit_sums(self):
        # Plugin patch on the package is 384Mi. NATS limits are 128Mi + 32Mi.
        small_tak = 1280 + 1536 + 1536 + 512 + 1536 + 384
        small_cloud = 768 + 512 + 128 + 512
        nats = 128 + 32
        self.assertEqual(small_tak + small_cloud + nats, 8864)
        prod_tak = 2048 + 2048 + 1536 + 512 + 1536 + 384
        prod_cloud = 1024 + 512 + 128 + 1024
        self.assertEqual(prod_tak + prod_cloud + nats, 10912)

    def test_harness_memory_matches_the_overlay(self):
        small = load("bench/configs/small.yaml")
        prod = load("bench/configs/production.yaml")
        self.assertEqual(small["name"], "small")
        self.assertEqual(prod["name"], "production")
        self.assertTrue(small["restart"])
        self.assertTrue(prod["restart"])
        for config in (small, prod):
            self.assertNotIn("postgres", config)
            seen = set()
            for item in config["resources"]:
                seen.add((item["workload"], item["container"]))
                self.assertIn("memory_request", item)
                self.assertIn("memory_limit", item)
            self.assertIn(("statefulset/takserver-ignite", "ignite"), seen)
            self.assertIn(("statefulset/takserver-postgresql", "postgresql"), seen)
            self.assertEqual(
                next(item["memory_limit"] for item in config["resources"] if item["container"] == "takserver-api"),
                "1536Mi" if config["name"] == "small" else "2Gi",
            )


if __name__ == "__main__":
    unittest.main()
