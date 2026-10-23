{{/*
Copyright 2026 uds-k3d-takserver authors
SPDX-License-Identifier: GPL-3.0-only
*/}}

{{/*
One openIdDiscoveryConfiguration. TAK picks an entry at random when more
than one is present, and authServer.issuer is a key file path, not a URL.
The secret stays ${TAK_OIDC_CLIENT_SECRET} so an init container can envsubst
it from Secret takserver-sso. envsubst does not treat the group regex as a
variable: the only substitution is the braced secret name.
groupprefix is stored lowercased (OAuthAuthenticator) and
LdapAuthenticator.applyGroupPrefixFilter lowercases the claim before
startsWith, so /tak/ matches /TAK/... The regex is compiled
CASE_INSENSITIVE, so ^/TAK/(.+)$ captures the original segment.
*/}}
{{- define "takserver.oauth" -}}
<oauth oauthUseGroupCache="false" useTakServerLoginPage="false" usernameClaim="preferred_username" groupsClaim="groups" groupprefix="/tak/" groupNameExtractorRegex="^/TAK/(.+)$" readGroupSuffix="_READ" writeGroupSuffix="_WRITE" adminTokenClaimName="groups" adminTokenClaimValue="{{ .Values.sso.adminGroup }}">
            <openIdDiscoveryConfiguration name="UDS SSO" clientId="{{ .Values.sso.clientId }}" secret="${TAK_OIDC_CLIENT_SECRET}" redirectUri="https://takserver.{{ .Values.domain }}/login/redirect" configurationUri="https://sso.{{ .Values.domain }}/realms/uds/.well-known/openid-configuration" trustAllCerts="false"/>
        </oauth>
{{- end -}}

{{- define "takserver.redirectUri" -}}
https://takserver.{{ .Values.domain }}/login/redirect
{{- end -}}

{{/*
The 8447 browser connector. With backendTLS it serves TLS from its own
keystore, issued at deploy time for the in-cluster Service name, and the
tenant gateway verifies it. TAK reports any tls="false" connector as a
non-secure port, so the plaintext form is only for backendTLS.enabled=false.
*/}}
{{- define "takserver.webConnector" -}}
{{- if .Values.api.web.backendTLS.enabled -}}
		<connector port="{{ .Values.api.web.port }}" clientAuth="false" keystore="JKS" keystoreFile="certs/files/{{ .Values.api.web.backendTLS.keystore }}" keystorePass="atakatak" enableAdminUI="true" enableWebtak="true" enableNonAdminUI="true" _name="web_https"/>
{{- else -}}
		<connector port="{{ .Values.api.web.port }}" tls="false" clientAuth="false" enableAdminUI="true" enableWebtak="true" enableNonAdminUI="true" _name="web_http"/>
{{- end -}}
{{- end -}}

{{/*
remoteServiceAccount line for an Ingress rule from a TAK workload, looked up
by its app label in workloadServiceAccounts. Fails the render for a client
with no entry, so a new flow cannot drop the identity check.
Usage: include "takserver.remoteServiceAccount" (list $ "takserver-api")
*/}}
{{- define "takserver.remoteServiceAccount" -}}
{{- $root := index . 0 -}}
{{- $app := index . 1 -}}
{{- $sa := index $root.Values.workloadServiceAccounts $app | default "" -}}
{{- if not $sa -}}
{{- fail (printf "workloadServiceAccounts has no entry for %s" $app) -}}
{{- end -}}
remoteServiceAccount: {{ $sa | quote }}
{{- end -}}
