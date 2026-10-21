# 8. TAK Server source as a git submodule

Date: 2026-10-20

## Status

Accepted

## Context

The Dockerfile's builder stage ran `git clone --branch 5.7-RELEASE-14 --depth 1` against the public TAK Server repository, then checked out a SHA that was written in the Dockerfile and in the Gradle cache key. The source was not part of this repository's history. A reviewer could not see which upstream files a build used without reading the Dockerfile, the tag bump and the SHA bump were separate edits, and every build fetched the repository from GitHub inside BuildKit.

## Decision

The TAK Server source is a git submodule at `upstream/takserver`, pinned to the commit of the release tag. `.gitmodules` marks it shallow and sets `branch` to the tag.

`build.sh` reads the commit and tree id from the submodule and passes the work tree to BuildKit as the `takserver-src` named context. The builder stage copies the files, commits them again as one commit tagged with the release, and fails if that commit's tree id differs from the upstream tree id. The tag and the detached `HEAD` keep TAK's own version string (`5.7-RELEASE-14-HEAD`) the same as before.

CI checks out the submodule in the jobs that build images. The container workflow, `docker-inputs-changed.sh`, and the Gradle cache key treat a change of the submodule pin as a change of the Docker inputs.

Renovate's `git-submodules` manager updates the pin to the newest `X.Y-RELEASE-N` tag. The existing regex manager updates the other copies of the tag string in the same grouped pull request.

## Consequences

- The exact upstream commit is part of every commit of this repository, and `git submodule status` shows it.
- The build no longer needs network access to GitHub for the source, only for Gradle and Node dependencies.
- The tree id check means a modified or partial checkout cannot produce images.
- Clones need `--recurse-submodules`, or `build.sh` initializes the submodule on first use.
- Jobs that build images must check out with `submodules: true`. Jobs that only read the published images do not need it.
- `git submodule update --remote` does not work with a tag in `branch`. Update the pin with `git -C upstream/takserver fetch --depth 1 origin <tag> && git -C upstream/takserver checkout FETCH_HEAD`, or let Renovate do it.
