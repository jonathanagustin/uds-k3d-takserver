# Mutation testing

Mutation testing changes program behavior and checks whether the tests catch it.
A surviving mutation points to a missing assertion or a change that has no effect
within the supported inputs. Inspect the report before deciding which it is.

Start with the two small suites below. They run on demand and do not start
clusters, build images, or publish packages.

| Suite | Tool | Targets | Gate |
| --- | --- | --- | --- |
| TAKX Java | PIT with JUnit 5 | `android.util.Pair`, `android.util.LruCache` | 100% mutation score and target line coverage |
| Pepr | Stryker with Node's test runner | `scripts/webhook-scope.ts` | 95% mutation score; existing baseline coverage gates also apply |

Java uses a test-only Maven module. JUnit invokes the same compatibility contracts
as the existing local runners, including real file-channel lifetime checks.
Stryker lives in a separate npm project so its dependencies stay out of the
application lockfile and package build. Its command runner executes the selected
`node --test` file for every mutation; it does not collect per-test coverage.

The targets exclude upstream checkouts, SDK JARs, test helpers, and generated
artifacts. Empty mutation scopes fail rather than report a successful dry run. Scores
describe these targets, not the whole TAKX client or repository.

## Run in GitHub Actions

Dispatch **Mutation tests** with `all`, `java`, or `pepr`:

```sh
gh workflow run mutation.yaml --ref main -f suite=all
```

Each job has two workers and a 15-minute limit. New runs on the same branch cancel
older mutation runs. HTML and machine-readable reports are retained for 14 days,
including when a gate fails. There is no schedule or automatic full mutation run
on each pull request. Ordinary unit tests still run normally.

## Run locally

Use the repository's pinned Java and Node versions. For Java:

```sh
cd takx/compat/mutation
mise install java maven
mise exec -- mvn -B -ntp clean test org.pitest:pitest-maven:mutationCoverage
```

Open `target/pit-reports/index.html`; mutation details are in
`target/pit-reports/mutations.xml`.

For Pepr, from the repository root:

```sh
cd pepr
npm ci --no-audit --no-fund
npm --prefix mutation ci --ignore-scripts --no-audit --no-fund
mkdir -p coverage
npm run test:coverage
npm --prefix mutation test
```

Open `mutation/reports/mutation.html`; JSON is beside it. Tool versions and
Java targets are pinned in the test projects. Use your normal Maven proxy and TLS
settings when your environment requires them; workspace credentials and trust
stores do not belong in the repository.

## Initial results

PIT initially found three gaps in the LRU contracts: eviction after `create()`,
replacement return values, and hit-rate reporting with multiple hits. New
assertions kill all 75 mutations across the two Java classes.

Pepr's first run killed 96 of 113 mutations. Additional cases check complete CEL
allowlists, field-like annotation data, malformed values, missing anchors,
webhook-entry fragments, and files without a trailing newline.

Five Stryker survivors remain visible for review. They concern whitespace,
anchor boundaries outside the supported generated-template shape, and an unused
lookup. No mutation operators or individual mutants are suppressed. Revisit these
cases before expanding the supported input format.

Add targets one at a time. Run the unchanged baseline first, inspect survivors,
and add assertions for real observable behavior. Keep the reports and failure
gates when expanding a suite.
