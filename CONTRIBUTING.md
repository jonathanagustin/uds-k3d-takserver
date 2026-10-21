# Contributing

Thanks for your interest in uds-k3d-takserver. Bug reports, feature requests, and pull requests are all welcome.

## Reporting bugs and requesting features

Open an issue at <https://github.com/jonathanagustin/uds-k3d-takserver/issues>. Search the existing issues first, since yours may already be there.

For a bug, include:

- the commit or package version you deployed
- the cluster (for example the `k3d-core-slim-dev` bundle) and its architecture
- what you ran, what you expected, and what happened
- relevant logs, for example from `uds run actions:debug-output` or `uds zarf tools kubectl logs -n takserver <pod>`

For a feature request, describe the problem you want solved and how you would use the result.

Do not report security vulnerabilities in a public issue. Follow [SECURITY.md](SECURITY.md) instead.

## Contribution process

1. Fork the repository and create a branch from `main`.
2. Make your change, with tests and documentation (see below).
3. Run the lint checks and the tests that cover your change.
4. Open a pull request against `main` and fill in the template.
5. CI runs lint, CodeQL, dependency review, and the k3d install test. All required checks must pass.
6. The maintainer reviews the pull request. When it is approved and green, it is squash-merged, so the pull request title becomes the commit message on `main`.

Release Please builds the changelog and release pull requests from the merged titles, so you don't edit `CHANGELOG.md` or version numbers yourself.

## Requirements for a pull request

- **Title.** Use [Conventional Commits](https://www.conventionalcommits.org/), for example `feat: ...`, `fix: ...`, `docs: ...`, `ci: ...`, or `chore: ...`. The Commitlint workflow checks it.
- **Lint.** `hk check --all` must pass. It runs yamllint, shellcheck, hadolint, actionlint, codespell, Helm lint and template checks, Zarf lint, gitleaks, and the key-material check (see [`hk.pkl`](hk.pkl)). `uds run lint:all` runs the shared YAML, shell, Zarf, Helm, and license-header checks. All tools are pinned in [`mise.toml`](mise.toml); `mise install` installs them.
- **License headers.** New source files carry the SPDX header used across the repository:

  ```text
  Copyright 2026 uds-k3d-takserver authors
  SPDX-License-Identifier: GPL-3.0-only
  ```

- **No secrets.** Never commit private keys, keystores, passwords, or enrolled certificates. Certificates are generated at deploy time ([ADR 2](adr/0002-generate-certificates-at-deploy-time.md)).
- **Pinned dependencies.** Pin images and GitHub Actions by digest or full commit SHA, with the version in a comment. Renovate keeps them current.
- **Documentation.** Update the README, `docs/`, or an ADR in `adr/` when behavior, configuration, or a design decision changes.

## Coding standards

- Shell scripts use strict mode (`set -euo pipefail`) and pass shellcheck.
- YAML passes yamllint with [`.yamllint`](.yamllint).
- Dockerfiles pass hadolint with [`.hadolint.yaml`](.hadolint.yaml).
- The Pepr module in `pepr/` is TypeScript with `strict` mode on.
- Helm charts pass `helm lint` and render with `helm template`.
- Keep UDS policy exemptions and NetworkPolicy allow rules as narrow as possible, and explain any new one in the pull request.

## Tests

**Policy: new functionality comes with automated tests.** A pull request that adds a feature or fixes a bug adds or updates a test that would fail without the change. If a change can't reasonably be tested, say why in the pull request.

Where tests live:

| Kind | Location | How to run |
| --- | --- | --- |
| Pepr module unit tests | `pepr/capabilities/*.test.ts` | `cd pepr && npm ci && npm test` |
| Deployment checks (pods, mesh, policy, gateways) | [`tasks/test.yaml`](tasks/test.yaml) | `uds run test-install` |
| Marti API smoke tests | [`tests/api-smoke.sh`](tests/api-smoke.sh) | part of `uds run test-install` |
| Browser and SSO tests (Playwright) | `tests/*.spec.ts` | part of `uds run test-install` |
| Upgrade tests | `tests/upgrade*.py`, `tests/upgrade.sh` | `uds run test-upgrade` |

`uds run test-install` builds the package, deploys `k3d-core-slim-dev` and the test bundle, and runs the whole suite. The same suite runs in the Test workflow on every pull request that changes code.

## License

By contributing, you agree that your contributions are licensed under the [GPL-3.0-only](LICENSE) license of this repository.
