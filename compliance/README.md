# Draft control evidence

This is a proposed set of package evidence for fourteen NIST SP 800-53 Rev. 5
base controls. It is not a complete NIST catalog, a deployment assessment,
certification, or authorization. Every control is **Partially Implemented**:
the narratives describe package behavior and the gaps that belong to Core,
upstream applications, the deployment, or organizational policy. Linked tests
are procedures to rerun, not claims that a new live assessment passed.

Issue [#37](https://github.com/jonathanagustin/uds-takserver/issues/37) was
explicitly deferred until Lula releases again or compliance becomes a priority.
The latest npm version is still 0.9.5, with registry activity last modified on
2026-03-12. The foundational mappings are separate from activating the deferred automated crawler.
All source associations have mapping status `planned` pending review; their
presence does not turn the parent control into an implemented control.

## Inspect the evidence

Use the pinned CLI from the repository root:

```bash
npx --yes lula2@0.9.5 ui --dir compliance --port 3000 --no-open-browser
```

Open `http://localhost:3000` locally. The UI is an editor with no application
authentication; use it on a trusted local machine and do not publish it.
The pinned CLI was opened locally with all fourteen controls and mappings,
and the implementation view was inspected:

![Lula 0.9.5 displaying the draft SC-8 implementation](evidence/lula-0.9.5.png)

Controls are under `controls/<family>/`, and proposed associations are under
`mappings/<family>/*-mappings.yaml`. Source locations are relative to the
repository root. The actual 0.9.5 `SourceEntry` schema uses `location`; the
README's older `source:` example is not used here.

```bash
uv run --no-project --with pyyaml==6.0.3 python -B .github/scripts/check-compliance.py
uv run --no-project --with pyyaml==6.0.3 python -B -m unittest tests.test_compliance_mappings -v
```

The checker rejects missing files, unsafe paths, unknown/duplicate UUIDs,
unknown control IDs, undeclared source locations, incomplete marker pairs, and
crossed markers. It scans tracked and untracked source files while respecting
Git ignore rules, so a new marker cannot silently bypass local validation.
Multiple distinct blocks may share a UUID when all locations are declared.

## What the workflow can prove

The automatic Lula workflow validates mappings for every pull request, including
forks. It does not crawl PRs or post comments. Automated live crawler activation
remains deferred under issue #37; the foundational marker set can be reviewed
separately from that activation decision.

A separate **Lula manual crawl** workflow runs only from `main`, after a user
supplies a PR number and explicitly enables `post_comments`. That input authorizes
the pinned CLI to delete its previous signed comments and post current findings.
The workflow checks out only trusted workflow source and never executes PR code.
It rejects forks, drafts, closed PRs, more than 30 changed files, and a base commit
without the existing mapped CoreConfig marker pair. Thus this foundational PR
cannot serve as proof of a successful later crawl. A later small PR must modify
an already mapped block and demonstrate the expected UUID in the comment.

Two verified limits in the pinned 0.9.5 CLI prevent claiming complete crawl
acceptance today:

- `crawl` calls `octokit.pulls.listFiles` without pagination or `per_page`.
  GitHub therefore returns at most the first 30 changed files. The workflow
  fails its preflight for larger pull requests instead of silently reporting
  no compliance impact. This draft itself adds more than 30 files.
- Its `getChangedBlocks` skips a UUID when the base file has no corresponding
  marked block. A pull request introducing markers does not demonstrate that
  later edits will produce the expected comment. After the marker set is
  merged by a maintainer, a separate small pull request must change an
  existing mapped block and verify the comment contains that UUID.

These observations come from the published `lula2@0.9.5` bundle's
`cli/commands/crawl.ts` code in `dist/index.js`. The tool is intentionally
pinned; this draft does not patch or silently replace its crawler.

## Evidence boundaries

- The SSO mappings cover configured gates, not MFA or identity proofing.
- The network/TLS mappings cover named paths, not every internal transport.
- Android 9 PKCS12 compatibility uses SHA-1/3DES. No FIPS claim is made.
- CA key custody, rotation, Secret encryption at rest, and recovery are partly
  deployment responsibilities. TAK-signed client revocation uses the certificate table without rolling TAK;
  legacy certificates retain a CRL reload fallback. Live disconnect timing
  still needs assessment in the deployed environment.
- The logging checks cover selected stdout/Loki events. File-only access,
  database audit, and ESAPI logs are not collected by those queries; retention
  and audit integrity need separate assessment.
- Cosign signing is optional, and provenance jobs do not establish mandatory
  verification for every runtime image pull.

The source mappings deliberately point at local call sites or verification
logic when the implementation is upstream-owned. In particular,
`publish-cert-configmap.sh` is supplied by the TAK image; the mapped cert-init
Job invokes it but this repository does not vendor that script.

The manual preflight requires the API response for the exact mapped CoreConfig
path and complete, ordered XML-comment marker pairs. Marker substrings in a
value, reversed pairs, and unfinished or nested blocks do not establish the
existing baseline. These checks do not replace the outstanding live comment
acceptance or activate automatic posting.
