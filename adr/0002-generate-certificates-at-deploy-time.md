# 2. Generate certificates at deploy time

Date: 2026-10-18

## Status

Accepted

## Context

`chart/files/certs` held a TAK CA, server, admin, and user material, including `ca-do-not-share.key`, `root-ca-do-not-share.key`, PKCS#12 files, and JKS keystores. The config chart packaged that directory into ConfigMap `cert-migration`. The repository is going public. Those files must not stay in the tree.

TAK Server 5.7-RELEASE-14 ships `generateClusterCerts.sh`, `makeRootCa.sh`, and `makeCert.sh`. The upstream chart mounts a ConfigMap named by `certConfigMapName` and does not generate it. Zarf `sensitive: true` variables are strings. They do not carry a directory of keystores cleanly.

## Decision

A Helm pre-install and pre-upgrade Job in the config chart runs those TAK scripts inside the `takserver-config` image. The image installs openssl and copies the scripts from the upstream checkout. The Job writes ConfigMap `cert-migration` through the Kubernetes API when that ConfigMap is absent, and does nothing when it is already there. CI does not create the ConfigMap first, so the install generates the certificates. Operators who bring their own material create the ConfigMap before install.

The keystore password stays `atakatak`, matching `CoreConfig.xml` and the upstream script default. `/opt/tak/UserAuthenticationFile.xml` in the image is empty, so the old admin fingerprint is not an administrator. `certmod -A` enrolls the generated admin certificate after the server starts.

`.gitignore` ignores `*.key`, `*.p12`, `*.jks`, and `*.crl`. `hk` runs gitleaks with a path rule for `*.key`, `*.p12`, and `*.jks`, and a `find` so an empty file of those types also fails. The gitleaks invocation is `--no-git`. It does not scan older commits.

## Consequences

Install now depends on the cert Job finishing before the TAK chart mounts the ConfigMap. The generated private keys live in a ConfigMap because that is what the upstream chart mounts. A public publish of this repository still needs a history that never contained `chart/files/certs`. This branch does not rewrite that history.
