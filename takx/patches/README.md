# Upstream patches

There are currently no source patches: the CommonCommo foundation builds the pinned official 1.17.2 source without Java/C++ API changes.

Future changes belong here as small, ordered diffs against a recorded upstream revision. Each patch must state the concrete incompatibility, intended behavior, applicable version and tests. Apply patches deterministically and include their hashes in build inputs before enabling them. Keep substantial upstream code in its upstream checkout rather than copying it into an untracked compatibility SDK.

A repository-local adapter is appropriate only when it implements real, tested behavior at an integration boundary. Do not add placeholder SDK classes, rename an old artifact to satisfy a newer dependency, treat a fixed-UDP endpoint as a TLS streaming route, or silently remove features. Unsupported capabilities must be visible and covered by tests; upstream fixes should remain easy to review and retire when a matching source release becomes available.
