# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""Capacity fixtures are synthetic, not measurements from a running TAK."""

import copy
import json
import types
import unittest
from unittest.mock import patch

from bench import capacity
from bench.run import quantity
from bench import run


def pod(uid="pod-1", restarts=0, reason=None, limit="1536Mi"):
    return {
        "metadata": {"namespace": "takserver", "name": "takserver-messaging-abc", "uid": uid},
        "spec": {"containers": [{"name": "messaging", "resources": {"limits": {"memory": limit}}}]},
        "status": {"phase": "Running", "containerStatuses": [{
            "name": "messaging", "restartCount": restarts, "ready": True,
            "lastState": {"terminated": {"reason": reason}} if reason else {},
        }]},
    }


def summary(uid="pod-1", memory=100, cpu=10, stamp="2026-11-07T23:00:00Z"):
    return {"pods": [{
        "podRef": {"namespace": "takserver", "name": "takserver-messaging-abc", "uid": uid},
        "containers": [{"name": "messaging", "memory": {"workingSetBytes": memory, "time": stamp},
                        "cpu": {"usageNanoCores": cpu}}],
    }]}


class CapacityTests(unittest.TestCase):
    def test_failed_pod_keeps_its_current_oom_termination_evidence(self):
        errors, samples = [], {}
        before = capacity.inventory([pod()], quantity, errors)
        failed = pod()
        failed["status"]["phase"] = "Failed"
        status = failed["status"]["containerStatuses"][0]
        status["ready"] = False
        status["state"] = {"terminated": {"reason": "OOMKilled"}}
        capacity.observe(summary(), samples, errors)
        after = capacity.inventory([failed], quantity, errors)
        result = capacity.assemble(before, after, samples, errors)
        row = result["containers"][0]
        self.assertEqual(row["after"]["pod_phase"], "Failed")
        self.assertEqual(row["after"]["termination_reason"], "OOMKilled")
        self.assertTrue(any("OOMKilled" in error for error in result["errors"]))
        self.assertTrue(any("not Ready" in error for error in result["errors"]))

    def test_existing_sampler_collects_container_evidence_from_the_same_summary_poll(self):
        class Stop:
            stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, _seconds):
                self.stopped = True

        def kubectl(*args):
            if args[:2] == ("get", "nodes"):
                return types.SimpleNamespace(stdout="node/test\n")
            return types.SimpleNamespace(stdout=json.dumps(summary(memory=123, cpu=45)))

        totals, samples, errors, capacity_errors = [], {}, [], []
        with patch.object(run, "kubectl", kubectl):
            run.kubelet_samples(Stop(), totals, errors, [], samples, capacity_errors)
        self.assertEqual(totals, [{"rss": 123, "cpu": 45}])
        self.assertEqual(next(iter(samples.values()))["peak_working_set_bytes"], 123)
        self.assertEqual(errors, [])
        self.assertEqual(capacity_errors, [])

    def test_sampled_peaks_limits_and_restart_evidence_stay_with_the_container(self):
        errors, samples = [], {}
        before = capacity.inventory([pod()], quantity, errors)
        capacity.observe(summary(memory=100, cpu=10), samples, errors)
        capacity.observe(summary(memory=150, cpu=20, stamp="2026-11-07T23:00:05Z"), samples, errors)
        capacity.observe(summary(memory=0, cpu=0, stamp="2026-11-07T23:00:10Z"), samples, errors)
        after = capacity.inventory([pod(restarts=1, reason="OOMKilled")], quantity, errors)
        result = capacity.assemble(before, after, samples, errors)
        row = result["containers"][0]
        self.assertEqual(row["before"]["memory_limit_bytes"], 1536 * 2**20)
        self.assertEqual(row["before"]["restart_count"], 0)
        self.assertEqual(row["after"]["restart_count"], 1)
        self.assertEqual(row["after"]["last_termination_reason"], "OOMKilled")
        self.assertEqual(row["samples"]["memory_sample_count"], 3)
        self.assertEqual(row["samples"]["peak_working_set_bytes"], 150)
        self.assertEqual(row["samples"]["last_working_set_bytes"], 0)
        self.assertEqual(row["samples"]["peak_cpu_nanocores"], 20)
        self.assertEqual(row["samples"]["last_cpu_nanocores"], 0)
        self.assertEqual(row["samples"]["last_memory_time"], "2026-11-07T23:00:10Z")
        self.assertTrue(any("restart count changed" in error for error in result["errors"]))
        self.assertTrue(any("OOMKilled" in error for error in result["errors"]))

    def test_pod_replacement_is_not_folded_into_one_healthy_identity(self):
        errors, samples = [], {}
        before = capacity.inventory([pod()], quantity, errors)
        after = capacity.inventory([pod(uid="pod-2")], quantity, errors)
        capacity.observe(summary(), samples, errors)
        capacity.observe(summary(uid="pod-2"), samples, errors)
        result = capacity.assemble(before, after, samples, errors)
        self.assertEqual(len(result["containers"]), 2)
        old, new = result["containers"]
        self.assertIsNone(old["after"])
        self.assertIsNone(new["before"])
        self.assertTrue(any("pod replacement" in error for error in result["errors"]))

    def test_missing_stats_limits_and_status_are_null_with_collection_errors(self):
        errors, samples = [], {}
        source = pod(limit=None)
        source["status"]["containerStatuses"] = []
        before = capacity.inventory([source], quantity, errors)
        capacity.observe(summary(memory=None, cpu=None), samples, errors)
        result = capacity.assemble(before, before, samples, errors)
        row = result["containers"][0]
        self.assertIsNone(row["before"]["memory_limit_bytes"])
        self.assertIsNone(row["before"]["restart_count"])
        self.assertIsNone(row["samples"]["peak_working_set_bytes"])
        self.assertIsNone(row["samples"]["peak_cpu_nanocores"])
        self.assertTrue(any("memory limit" in error for error in result["errors"]))
        self.assertTrue(any("restart count" in error for error in result["errors"]))
        self.assertTrue(any("no memory samples" in error for error in result["errors"]))

    def test_aggregation_is_bounded_and_does_not_modify_source_pods(self):
        errors, samples = [], {}
        source = pod()
        original = copy.deepcopy(source)
        capacity.inventory([source], quantity, errors)
        for index in range(capacity.MAX_CONTAINERS + 2):
            capacity.observe(summary(uid=f"pod-{index}"), samples, errors)
        self.assertEqual(len(samples), capacity.MAX_CONTAINERS)
        self.assertEqual(sum("samples exceeded" in error for error in errors), 1)
        self.assertEqual(source, original)
        inventory = capacity.inventory([pod(uid=f"p-{i}") for i in range(capacity.MAX_CONTAINERS + 2)], quantity, errors)
        self.assertEqual(len(inventory), capacity.MAX_CONTAINERS)
        self.assertTrue(any("inventory exceeded" in error for error in errors))

    def test_uid_is_required_and_non_target_namespaces_are_ignored(self):
        errors, samples = [], {}
        capacity.observe(summary(uid=None), samples, errors)
        ignored = summary()
        ignored["pods"][0]["podRef"]["namespace"] = "monitoring"
        capacity.observe(ignored, samples, errors)
        self.assertEqual(samples, {})
        self.assertTrue(any("no pod UID" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
