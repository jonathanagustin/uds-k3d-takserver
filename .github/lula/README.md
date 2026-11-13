# Lula 0.9.5 safety variant

The comment workflow uses this variant for manual requests and eligible pull
requests targeting `main`. The separate mapping validator remains read-only.
Local tests cover the posting safeguards; a live comment from a changed mapped
block is still required to complete acceptance.

The official `lula2@0.9.5` command has only `review` and `comment` posting modes;
neither produces findings without posting. Its cleanup selects comments by the
`LULA_SIGNATURE` substring without checking the author. It also deletes matching
comments when there are no findings and continues after individual file-read
errors. Unmodified automatic use could delete a human comment quoting a finding.

`source.lock.json` records the published npm archive integrity and original file
hashes. The unchanged official crawl module is retained for tests that run its
actual analysis against a simulated GitHub application programming interface
(API). It retains its Apache-2.0 license. The patch helper is project
GPL-3.0-only tooling; generated JavaScript retains the upstream license.
Distribute the included upstream license and this modification notice with it.
This is an explicit project variant, not a new upstream Lula release.

The variant keeps official block analysis and comment formatting, with these
posting safeguards:

- Support comment mode only. Stop on modified or deleted file-read errors before
  changing any comment.
- With no findings, neither create nor delete comments. Prior comments may become
  stale; their presence does not establish a current assessment.
- Create the replacement first. Its API response identifies the token's actual
  author. Cleanup requires GitHub.com Actions bot identifier `41898282`, login
  `github-actions[bot]`, and type `Bot`. Other token authors are unsupported.
  An unexpected author stops cleanup after creation.
- Finish listing comments before deleting anything. Delete only comments older
  than the replacement, with that same bot identity and exact opening Lula
  signature/header. Human quotations, other bots and newer comments survive.
  Creation failure leaves old findings intact; cleanup failure leaves duplicates
  and fails the command.

Both official `dist/index.js` (the bundled command-line entry point) and
`dist/cli/commands/crawl.js` are supported by exact original hashes. For an
installed official package, create a new sibling file:

```sh
python3 .github/lula/patch_crawl.py --archive /verified/lula2-0.9.5.tgz \
  /installed/lula2/dist/index.js /installed/lula2/dist/index.safe.mjs
```

The helper verifies Secure Hash Algorithm (SHA) checksums: SHA-512 for the archive
and SHA-256 for original source. It rejects changed source and existing output.
It makes no network requests, installs no dependencies and executes no generated
code. Pinning the package version does not freeze every indirect dependency.

Manual and `pull_request_target` runs share one queue per pull request. Checkout
is the immutable trusted `github.sha`: the base commit for the automatic event and the guarded main run commit for manual dispatch. The workflow
never checks out or executes pull-request code or inserts its metadata into shell
code. Write permission is limited to the comment job.

Both paths use the same preflight checks for an open, non-draft, same-repository
pull request targeting `main`, with existing base markers for control SC-8
(Transmission Confidentiality and Integrity). A valid automatic request
exceeding 30 changed files skips with fixed reason
`unsupported_changed_file_count`, before Node installation or comment changes.
Manual requests over that limit fail. Malformed responses, invalid source
bindings and other guard errors remain failures.

Archive integrity is checked before npm installation, installation scripts are
disabled, and that step receives no API credential. The crawler binds base/head
commit hashes and file count to preflight, requires a complete file list, and
checks current pull-request state again immediately before posting. A later
change cannot be made atomic with GitHub comment creation; these comments are
observations, not approval or merge checks.

Local simulated-API tests verify the safeguards above. Live acceptance remains
pending: change an existing mapped block in a small pull request and confirm
that the workflow posts its expected mapping identifier. Retain the workflow
run, workflow source commit, pull-request source commit and comment link with
that evidence. A passing local test does not establish that GitHub posted a
comment.
