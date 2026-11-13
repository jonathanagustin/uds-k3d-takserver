# Draft control evidence

This is a proposed set of package evidence for fourteen base controls from the
National Institute of Standards and Technology (NIST) Special Publication
800-53, Revision 5. It is not a complete NIST catalog, a deployment assessment,
certification, or authorization. Every control is **Partially Implemented**:
the narratives describe package behavior and the gaps that belong to Unified
Defense Stack (UDS) Core, upstream applications, the deployment, or
organizational policy. Linked tests
are procedures to rerun, not claims that a new live assessment passed.

Issue [#37](https://github.com/jonathanagustin/uds-takserver/issues/37) tracks
the mappings and automated comment workflow. The workflow uses published Lula
version 0.9.5 with the project's declared safety changes. Live acceptance of a
comment from a changed mapped block remains pending.

All source associations have mapping status `planned` pending review; their
presence does not turn the parent control into an implemented control.

## Inspect the evidence

Use the pinned command-line program from the repository root:

```bash
npx --yes lula2@0.9.5 ui --dir compliance --port 3000 --no-open-browser
```

Open `http://localhost:3000` locally. The user interface is an editor with no application
authentication; use it on a trusted local machine and do not publish it.
The pinned program was opened locally with all fourteen controls and mappings,
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

The checker rejects missing files, unsafe paths, unknown or duplicate universally
unique identifiers (UUIDs), unknown control identifiers, undeclared source
locations, incomplete marker pairs, and crossed markers. It scans tracked and untracked source files while respecting
Git ignore rules, so a new marker cannot silently bypass local validation.
Multiple distinct blocks may share a UUID when all locations are declared.

## What the workflow can prove

The read-only Lula workflow validates mappings for every pull request, including
forks. A separate comment workflow uses the safety variant for eligible
`pull_request_target` events and manual requests with comment posting enabled.

Both paths require an open, non-draft, same-repository pull request targeting
`main`, with the existing mapped CoreConfig base marker pair. They check out only
immutable `github.sha`: the trusted base commit for the automatic event or the
guarded main run commit for manual dispatch. They never check out or execute
pull-request code. Both paths share one queue per pull request.

The comment workflow verifies the npm archive before installation, disables
installation scripts, and checks the exact original bundled source before
patching. Only preflight and posting steps receive a GitHub application
programming interface (API) token. Preflight binds the source commit hashes and
file count; the crawler checks them again before posting. The variant refuses
partial file analysis, creates a replacement first, and removes only older
exact-header comments by the authenticated GitHub Actions bot. With no findings,
prior comments remain and may be stale.

Two verified limits in the pinned official command still apply:

- `crawl` calls `octokit.pulls.listFiles` without pagination or `per_page`, so
  GitHub returns at most 30 changed files. A valid automatic request over that
  limit skips with fixed reason `unsupported_changed_file_count`, before Node
  installation or comment changes. Manual requests over the limit fail.
  Malformed responses, invalid source bindings and other guard errors remain
  failures; there is no blanket error suppression.
- `getChangedBlocks` skips a mapping identifier when the base file has no
  corresponding marked block. Introducing markers does not prove later edits
  will produce a comment. The marker foundation is already merged; a separate
  small pull request must change an existing mapped block and demonstrate its
  expected UUID in an actual comment. Retain the run, workflow source and
  pull-request source identities with that evidence.

These observations come from the published `lula2@0.9.5` bundle's
`cli/commands/crawl.ts` code in `dist/index.js`. Unmodified cleanup selects the
signature substring without checking the author, even with no findings. The
comment workflow therefore uses the explicitly
[declared project safety variant](../.github/lula/README.md), preserving official
analysis and accurate version/license provenance. Local simulated-API tests do
not establish live comment acceptance. Issue #37 remains open until the actual
comment and its source identities have been recorded.

## Evidence boundaries

- The single sign-on (SSO) mappings cover configured gates, not multifactor
  authentication (MFA) or identity proofing.
- The network and Transport Layer Security (TLS) mappings cover named paths,
  not every internal transport.
- Android 9 compatibility with Public-Key Cryptography Standards #12 (PKCS12)
  uses Secure Hash Algorithm 1 (SHA-1) and Triple Data Encryption Standard
  (3DES). No Federal Information Processing Standards (FIPS) claim is made.
- Certificate authority (CA) key custody, rotation, Secret encryption at rest,
  and recovery are partly deployment responsibilities. Team Awareness Kit (TAK)
  signed client revocation uses the certificate table without restarting TAK;
  legacy certificates retain a certificate revocation list (CRL) reload
  fallback. Live disconnect timing still needs assessment in the deployed
  environment.
- The logging checks cover selected standard-output and Loki events. File-only
  access, database audit, and Enterprise Security API (ESAPI) logs are not
  collected by those queries; retention and audit integrity need separate
  assessment.
- Cosign signing is optional, and provenance jobs do not establish mandatory
  verification for every runtime image pull.

The source mappings deliberately point at local call sites or verification
logic when the implementation is upstream-owned. In particular,
`publish-cert-configmap.sh` is supplied by the TAK image; the mapped cert-init
Job invokes it but this repository does not vendor that script.

The shared preflight requires the API response for the exact mapped CoreConfig
path and complete, ordered Extensible Markup Language (XML) comment marker
pairs. Marker text inside a value, reversed pairs, and unfinished or nested blocks do not establish the existing
baseline. These checks do not replace the outstanding live comment acceptance.
