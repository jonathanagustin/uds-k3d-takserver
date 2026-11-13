# Lula 0.9.5 safety variant (local activation preparation)

The official `lula2@0.9.5` command has only `review` and `comment` posting modes;
neither is a render-only mode. In comment mode its cleanup selects comments by
the `LULA_SIGNATURE` substring without author checks. It also cleans up when
there are no findings, and catches individual file-fetch errors. Automatic use
of that unmodified command could delete a human comment quoting its signature.

This directory contains a narrow, explicit project variant, not a new upstream
release or a replacement compliance crawler. `source.lock.json` records the
published npm archive integrity and exact original file hashes. The unchanged
official crawl module is retained for actual-source mocked API tests under its
original Apache-2.0 license. The patch helper is project GPL-3.0-only tooling;
generated upstream-derived JavaScript retains the upstream license. Distribute
the included upstream license and this modification notice with that output.

The patch changes only posting safety and fatal propagation of file-read errors:

- Support comment mode only; retain official block analysis and comment format.
- Stop on modified/deleted file-read errors before any comment mutation.
- With no findings, neither create nor delete comments. Prior findings therefore
  remain historical and may become stale; no clean/current assessment is implied.
- Create the new finding first. Its API response identifies the actual author
  used by the token. Cleanup requires the exact GitHub.com Actions bot ID
  `41898282`, login `github-actions[bot]`, and type `Bot`. Other token authors
  are unsupported. Unexpected identity stops cleanup after creation.
- Enumerate comments before deleting anything. Delete only older comments with
  that same author identity and the exact opening Lula signature/header. Human
  quotations, other bots, a copied marker elsewhere, and the new comment survive.
  A failed create cannot remove the old finding; cleanup failure leaves duplicates
  and fails the command rather than claiming replacement succeeded.

Both official `dist/index.js` (the actual bundled CLI entry) and the standalone
`dist/cli/commands/crawl.js` are supported by exact pre-patch hashes. For an
already installed official package, prepare an exclusive new sibling file:

```sh
python3 .github/lula/patch_crawl.py --archive /verified/lula2-0.9.5.tgz \
  /installed/lula2/dist/index.js /installed/lula2/dist/index.safe.mjs
```

The helper verifies archive SHA-512 and original source SHA-256, rejects source
drift and existing output, and performs no network requests or execution. It
does not install npm dependencies, fetch credentials, or invoke the generated
CLI. Version pinning of the package does not freeze every transitive dependency.

The local workflow preparation uses this variant for both manual and automatic
`pull_request_target` entry points, with immutable trusted `github.sha` checkout only (base commit for PR-target,
guarded main run commit for manual), same-repository
open non-draft main-target PR guards, the 30-file bound, existing base SC-8 markers,
and job-only PR write permission. It does not check out or execute PR code or
interpolate PR metadata into shell code. Both entry points serialize the same PR.
Archive integrity is verified before npm installation; install scripts are disabled,
and the installation step receives no API credential. The crawler binds live
base/head SHAs and file count to preflight, checks complete file-list length, and
reads current PR state again immediately before posting. A changed/unsupported PR
fails before mutation. A change after that final API read cannot be made atomic
with GitHub comment creation; comments are observations, not an approval or merge
check. This local branch has not been published or activated. The read-only
mapping workflow remains separate and never posts.

The existing deferral until a new Lula release or explicit compliance priority
still applies. Local mocked API tests establish these safety behaviors, not live
comment acceptance. A later authorized small PR changing an existing mapped block
must produce an actual comment with the expected UUID and preserved run/source
and PR identities. No crawl, comment, or GitHub write was performed here.

In the local activation preparation, a valid automatic PR exceeding the pinned
30-file limit skips with fixed reason `unsupported_changed_file_count`; no Node
installation, crawler execution, binding file or comment mutation follows.
Manual requests over that limit still fail. Malformed API/JSON responses,
invalid source bindings and other guard errors remain failures; there is no
blanket error suppression. Checkout uses the workflow run's immutable trusted
commit rather than a mutable main ref.
