# syntax=docker/dockerfile:1
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

#
# Multi-stage build of the six TAK Server images from the public
# TAK-Product-Center/Server tag 5.7-RELEASE-14.
# The source is the git submodule at upstream/takserver. build.sh passes it as
# the takserver-src build context, along with the submodule commit and tree.
# Renovate moves the submodule and the tag below together.
#
# The builder digest is Temurin 17.0.20 on Ubuntu 22.04 (amd64 and arm64).
# Gradle is the upstream wrapper (8.10.2). protoc 3.25.8 and the Node
# versions used by the UI are downloaded by Gradle into the cache mount.
# Runtime stages use the UBI9 OpenJDK 17 manifest list, which also covers
# amd64 and arm64.

ARG BUILDER_IMAGE=eclipse-temurin:17.0.20_8-jdk-jammy@sha256:51d32af96fb8a13ffbc96c719d7b05447a04ca69f314627d64050a64ecd13057
ARG RUNTIME_IMAGE=registry.access.redhat.com/ubi9/openjdk-17:1.24-3.1791779556@sha256:716810ec4ad7805f57b6434da9405188cb98b30042bdb1cff0d833f76ed5b4b0

FROM ${BUILDER_IMAGE} AS builder

USER 0

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        diffutils \
        findutils \
        git \
        patch \
        unzip \
    && rm -rf /var/lib/apt/lists/*

ARG UPSTREAM_REF=5.7-RELEASE-14
# Commit and tree of the upstream/takserver submodule. build.sh reads both
# from git. There is no default, so a stale value cannot hide a bump.
ARG UPSTREAM_SHA
ARG UPSTREAM_TREE

WORKDIR /src

# The build context is the submodule work tree. Its .git is a pointer file to
# the parent repository, so it is dropped here. TAK's src/build.gradle reads
# the version from `git describe` and the branch name (HEAD when detached), so
# the checkout is rebuilt as one commit tagged with the release. The tree id
# has to equal the upstream commit's tree: the files are exactly that commit.
COPY --from=takserver-src . /src
RUN test -n "${UPSTREAM_SHA}" && test -n "${UPSTREAM_TREE}" \
    && rm -rf /src/.git \
    && git init -q /src \
    && git -C /src add -f -A \
    && test "$(git -C /src write-tree)" = "${UPSTREAM_TREE}" \
    && git -C /src -c user.name=build -c user.email=build@localhost \
        commit -q -m "TAK Server ${UPSTREAM_REF} (${UPSTREAM_SHA})" \
    && git -C /src -c user.name=build -c user.email=build@localhost \
        tag -a -m "${UPSTREAM_REF}" "${UPSTREAM_REF}" \
    && git -C /src checkout -q --detach \
    && test "$(git -C /src describe --exact-match HEAD)" = "${UPSTREAM_REF}" \
    && test "$(git -C /src rev-parse --abbrev-ref HEAD)" = "HEAD"

# The tree check above still matches the upstream commit. This patch is applied
# after it. cacheConfig="false" only skipped loadConfigFromCache. The
# continuous-query listener was registered either way, and registerListener runs
# that callback immediately, so another node's save replaced this node's file.
COPY cacheconfig-listener.patch /tmp/cacheconfig-listener.patch
RUN git -C /src -c apply.whitespace=nowarn apply --check /tmp/cacheconfig-listener.patch \
    && git -C /src -c apply.whitespace=nowarn apply /tmp/cacheconfig-listener.patch \
    && test "$(git -C /src diff --name-only)" = "src/takserver-common/src/main/java/com/bbn/marti/remote/config/DistributedConfiguration.java"

WORKDIR /src/src

# The committed gradle.properties asks for 768m. bootWar needs more than that,
# and a private ubuntu-latest runner has 8 GB, so stay under that.
# This edits the disposable checkout inside the image, not a file in this repo.
RUN grep -q '^org.gradle.jvmargs=' gradle.properties \
    && sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1280m -XX:MaxMetaspaceSize=320m -Dorg.gradle.workers.max=1/' gradle.properties

ENV GRADLE_USER_HOME=/gradle \
    DISABLE_ESLINT_PLUGIN=true \
    GRADLE_OPTS="-Dorg.gradle.daemon=false -Dorg.gradle.workers.max=1 -Dorg.gradle.vfs.watch=false" \
    NODE_OPTIONS="--max-old-space-size=768" \
    LANG=C.UTF-8

# react-scripts 5.0.1 still names the jest/globals environment. The installed
# eslint-plugin-jest does not provide it, so the UI build stops before it
# writes the bundle. DISABLE_ESLINT_PLUGIN skips that plugin and still compiles.
# gradle-seed is an extra build context. CI points it at the restored Gradle
# home. An empty directory is a cold cache. The copy at the end is a real
# layer so the gradle-export target can publish it for the next run.
RUN --mount=type=cache,id=tak-gradle,target=/gradle,sharing=locked \
    --mount=type=bind,from=gradle-seed,source=/,target=/gradle-seed,ro \
    if [ -d /gradle-seed/caches ]; then cp -a /gradle-seed/. /gradle/; fi \
    && ./gradlew --no-daemon bootWar bootJar shadowJar \
        :takserver-cluster:pullTakserverCore \
        :takserver-cluster:pullSchemaManager \
        :takserver-cluster:pullUserManager \
        :takserver-cluster:pullPluginManager \
        :takserver-cluster:igniteExtensions \
    && mkdir -p /opt/gradle-export \
    && if [ -d /gradle/caches ]; then cp -a /gradle/caches /opt/gradle-export/caches; fi \
    && if [ -d /gradle/notifications ]; then cp -a /gradle/notifications /opt/gradle-export/notifications; fi

RUN bash -euxo pipefail -c '\
    root=/src/src/takserver-cluster/build; \
    out=/image-root; \
    mkdir -p "$out"; \
    cp "$root"/takserver-core/takserver-core-*.war "$out/takserver.war"; \
    cp "$root/takserver-core/setenv-cluster.sh" "$out/setenv.sh"; \
    cp "$root/takserver-usermanager/UserManager.jar" "$out/UserManager.jar"; \
    cp "$root/takserver-core/CoreConfig.xml" "$out/CoreConfig.xml"; \
    cp "$root/takserver-schemamanager/SchemaManager.jar" "$out/SchemaManager.jar"; \
    cp "$root/takserver-core/logging-restrictsize.xml" "$out/logging-restrictsize.xml"; \
    cp "$root/takserver-core/takserver.sh" "$out/takserver.sh"; \
    cp "$root/takserver-core/config/takserver-config-cluster.sh" "$out/takserver-config-cluster.sh"; \
    cp "$root/takserver-core/API/takserver-api-cluster.sh" "$out/takserver-api-cluster.sh"; \
    cp "$root/takserver-core/messaging/takserver-messaging-cluster.sh" "$out/takserver-messaging-cluster.sh"; \
    cp "$root/takserver-core/plugins/takserver-plugins-cluster.sh" "$out/takserver-plugins-cluster.sh"; \
    cp "$root/takserver-core/UserAuthenticationFile.xml" "$out/UserAuthenticationFile.xml"; \
    cp "$root/takserver-core/enable_admin.sh" "$out/enable_admin.sh"; \
    cp "$root/takserver-core/messaging-readiness.sh" "$out/messaging-readiness.sh"; \
    cp "$root/takserver-core/config-readiness.sh" "$out/config-readiness.sh"; \
    cp "$root/takserver-core/api-readiness.sh" "$out/api-readiness.sh"; \
    cp "$root/takserver-core/takserver-pm.jar" "$out/takserver-pm.jar"; \
    ext="$(find /src/src -name "ignite-extensions*.jar" -path "*/build/*" | head -n 1)"; \
    test -s "$ext"; \
    cp "$ext" "$out/ignite-extensions.jar"; \
    cp /src/src/takserver-cluster/utilities/db-connection-configuration.sh "$out/db-connection-configuration.sh"; \
    cp /src/src/takserver-schemamanager/scripts/generic-cluster-database-configuration.sh "$out/generic-cluster-database-configuration.sh"'

# SchemaManager.jar is not copied here. Only takserver-database-setup runs it,
# and none of the cluster start scripts in the api, messaging, config and
# plugins images call it. Storing it in both cost about 59 MB per architecture.
FROM ${RUNTIME_IMAGE} AS cluster-base

USER 0

RUN microdnf install -y nmap-ncat \
    && microdnf clean all \
    && ln -sf "$(command -v ncat)" /usr/local/bin/nc \
    && mkdir -p /opt/tak/work /opt/tak/logs /certs/files /logs /conf /work \
    && chmod 0777 /opt/tak /opt/tak/work /opt/tak/logs /certs /certs/files /logs /conf /work \
    && chmod 1777 /

WORKDIR /

COPY --from=builder \
    /image-root/takserver.war \
    /image-root/setenv.sh \
    /image-root/UserManager.jar \
    /image-root/CoreConfig.xml \
    /image-root/logging-restrictsize.xml \
    /image-root/takserver.sh \
    /image-root/takserver-config-cluster.sh \
    /image-root/takserver-api-cluster.sh \
    /image-root/takserver-messaging-cluster.sh \
    /image-root/takserver-plugins-cluster.sh \
    /image-root/UserAuthenticationFile.xml \
    /image-root/enable_admin.sh \
    /image-root/messaging-readiness.sh \
    /image-root/config-readiness.sh \
    /image-root/api-readiness.sh \
    /image-root/db-connection-configuration.sh \
    /image-root/takserver-pm.jar \
    /image-root/ignite-extensions.jar \
    /

# setenv.sh sets -Djdk.tls.client.protocols=TLSv1.2, so every default TLS client in
# the TAK JVM offers TLS 1.2 only. TAK's OIDC discovery and token calls use a
# default OkHttp client, and the UDS gateways require TLS 1.3, so they failed with
# a protocol_version alert. Offer 1.3 and keep 1.2 for older peers. The grep fails
# the build if upstream changes that line.
RUN chmod 0755 \
        /setenv.sh \
        /takserver.sh \
        /takserver-config-cluster.sh \
        /takserver-api-cluster.sh \
        /takserver-messaging-cluster.sh \
        /takserver-plugins-cluster.sh \
        /enable_admin.sh \
        /messaging-readiness.sh \
        /config-readiness.sh \
        /api-readiness.sh \
        /db-connection-configuration.sh \
    && ./db-connection-configuration.sh \
    && sed -i 's/-XX:MaxRAMPercentage=/-Xms512m -Xmx512m -XX:MaxRAMPercentage=/' \
        /takserver-api-cluster.sh \
        /takserver-messaging-cluster.sh \
        /takserver-config-cluster.sh \
    && sed -i 's/java -jar UserManager.jar/java -Xmx128m -jar UserManager.jar/' /enable_admin.sh \
    && sed -i 's/-Djdk.tls.client.protocols=TLSv1.2/-Djdk.tls.client.protocols=TLSv1.3,TLSv1.2/' /setenv.sh \
    && grep -q -- '-Djdk.tls.client.protocols=TLSv1.3,TLSv1.2' /setenv.sh \
    && sed -i "s#cat 'UserAuthenticationFile.xml' | grep -q 'ROLE_ADMIN'#grep -qs -e ROLE_ADMIN -e 'adding new file-based user' /opt/tak/UserAuthenticationFile.xml /logs/takserver-messaging.log#" \
        /messaging-readiness.sh \
    && sed -i 's#location="UserAuthenticationFile.xml"#location="/opt/tak/UserAuthenticationFile.xml"#' /CoreConfig.xml \
    && sed -i '2i : > /logs/takserver-api.log' /takserver-api-cluster.sh \
    && sed -i '2i : > /logs/takserver-messaging.log' /takserver-messaging-cluster.sh \
    && sed -i '2i : > /logs/takserver-config.log' /takserver-config-cluster.sh

# FileAuthenticator copies the auth file to a sibling .backup before replacing
# it. The working directory is /, and that directory rejected the backup.
# /opt/tak is created mode 0777 above, and the JVM already uses it for temp files.
COPY UserAuthenticationFile.xml /opt/tak/UserAuthenticationFile.xml
RUN chmod 0666 /opt/tak/UserAuthenticationFile.xml

ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver

# The plugins entrypoint expands PLUGIN_MANAGER_MAX_HEAP into -Xmx. An empty
# value is -Xmxm and the JVM exits.
# The three cluster scripts pass only MaxRAMPercentage. On the test runner that
# followed host RAM (about 7.1GB) because the JVM did not see the cgroup limit,
# and the API was killed inside 1Gi before Tomcat opened 8443. -Xmx wins over
# MaxRAMPercentage. 512m is the floor Ignite prints in its own warning.
# The flags stay on those three java commands. JDK_JAVA_OPTIONS would also
# apply to UserManager, and a second 512m heap in the messaging pod exceeds 1Gi.
ENV PLUGIN_MANAGER_MAX_HEAP=128

FROM cluster-base AS takserver-config
ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver
LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-config"
# Cert generation stays in this image. The pre-install Job runs
# publish-cert-configmap.sh. The other TAK images do not need openssl.
# gettext provides envsubst for the OIDC init container. The stock chart
# cannot add that container, so this image is reused as the init image.
RUN microdnf install -y openssl gettext \
    && microdnf clean all
COPY --from=builder /src/src/takserver-core/scripts/certs /opt/tak/certs
COPY publish-cert-configmap.sh /opt/tak/certs/publish-cert-configmap.sh
# The Job may run as a non-root uid. makeRootCa.sh creates files/ here.
RUN chmod 0755 /opt/tak/certs/*.sh \
    && chmod 0777 /opt/tak/certs
CMD ["sh", "/takserver-config-cluster.sh"]

FROM cluster-base AS takserver-messaging
ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver
LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-messaging"
CMD ["sh", "/takserver-messaging-cluster.sh"]

FROM cluster-base AS takserver-api
ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver
LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-api"
CMD ["sh", "/takserver-api-cluster.sh"]

FROM cluster-base AS takserver-plugins
ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver
LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-plugins"
CMD ["sh", "/takserver-plugins-cluster.sh"]

FROM ${RUNTIME_IMAGE} AS takserver-database-setup

USER 0

# UBI already provides curl via curl-minimal. The curl package conflicts with it.
RUN microdnf install -y nmap-ncat \
    && microdnf clean all \
    && ln -sf "$(command -v ncat)" /usr/local/bin/nc

WORKDIR /

COPY --from=builder \
    /image-root/SchemaManager.jar \
    /image-root/generic-cluster-database-configuration.sh \
    /

ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver

LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-database-setup"

RUN chmod 0755 /generic-cluster-database-configuration.sh

CMD ["./generic-cluster-database-configuration.sh"]

FROM ${RUNTIME_IMAGE} AS takserver-ignite

USER 0

# UBI already provides curl via curl-minimal. The curl package conflicts with it.
RUN microdnf install -y unzip nmap-ncat \
    && microdnf clean all \
    && ln -sf "$(command -v ncat)" /usr/local/bin/nc

ARG IGNITE_VERSION=2.17.0
ARG IGNITE_URL=https://archive.apache.org/dist/ignite/2.17.0/apache-ignite-2.17.0-bin.zip
ARG IGNITE_SHA512=cd14c9344cc91e9d328a4c4478d9686edc9e1065a0b558e345389a6241afcdfc29f927644cecaf1243a0db7e02113e4dd81ba2df44b65c75c8ec08cab3d405a1
ARG UPSTREAM_REF=5.7-RELEASE-14
ARG UPSTREAM_SHA
ARG SOURCE_REPO=https://github.com/jonathanagustin/uds-k3d-takserver

WORKDIR /opt

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -fsSL -o /tmp/ignite.zip "${IGNITE_URL}" \
    && echo "${IGNITE_SHA512}  /tmp/ignite.zip" | sha512sum -c - \
    && unzip -q /tmp/ignite.zip -d /opt \
    && rm /tmp/ignite.zip \
    && mv "/opt/apache-ignite-${IGNITE_VERSION}-bin" /opt/ignite \
    && cp /opt/ignite/libs/optional/ignite-kubernetes/*.jar /opt/ignite/libs/ \
    && mkdir -p /opt/ignite/work \
    && chmod -R a+rwx /opt/ignite

# Upstream's Ignite launcher, from the same submodule commit as the TAK build.
# 0777 matches the chmod -R a+rwx above.
COPY --from=takserver-src --chmod=0777 src/takserver-cluster/docker-files/scripts/takserver-ignite/ignite.sh /opt/ignite/bin/ignite.sh

LABEL org.opencontainers.image.source="${SOURCE_REPO}" \
      org.opencontainers.image.revision="${UPSTREAM_SHA}" \
      org.opencontainers.image.version="${UPSTREAM_REF}" \
      org.opencontainers.image.title="takserver-ignite" \
      org.opencontainers.image.description="Apache Ignite ${IGNITE_VERSION} for TAK Server ${UPSTREAM_REF}"

ENV IGNITE_HOME=/opt/ignite
WORKDIR /opt/ignite

EXPOSE 10800 47100 47500 49112

ENTRYPOINT ["./bin/ignite.sh"]

FROM scratch AS gradle-export
COPY --from=builder /opt/gradle-export/ /
