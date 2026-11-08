# Pinned load-tester contract

These source fixtures come from TAK-Product-Center/Server commit
`5187abd46d827d37cfc5708805eced197a837e49`, the benchmark's pinned load tester:

- `src/testing/load_test/tak_tester.py` (complete source)
- `src/testing/load_test/stats.py` (complete source)
- `print_info_without_sending_to_cloud_watch_process` from
  `src/testing/load_test/cloud_watch.py` (function excerpt)

Tests execute the pinned startup, shared-array and printer contracts with
local process/clock substitutes. They do not connect to a TAK server or claim
that requested clients established real connections.

The complete tester fixture preserves upstream spelling, so codespell excludes
that one file. The fixtures remain source data rather than maintained scripts.
