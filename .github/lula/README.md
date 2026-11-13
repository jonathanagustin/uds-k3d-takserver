# Lula 0.9.5 safety variant (not activated)

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

No workflow uses this variant yet. The existing read-only mapping workflow and
explicitly authorized manual workflow are unchanged. Before automatic activation,
retain trusted default-branch workflow/code only, same-repository open non-draft
PR guards, the 30-file bound, existing base SC-8 markers, and job-only PR write
permission. Never check out or execute PR code or interpolate PR metadata into
shell code. Serialize runs for one PR to avoid overlapping replacements.

The existing deferral until a new Lula release or explicit compliance priority
still applies. Local mocked API tests establish these safety behaviors, not live
comment acceptance. A later authorized small PR changing an existing mapped block
must produce an actual comment with the expected UUID and preserved run/source
and PR identities. No crawl, comment, or GitHub write was performed here.
