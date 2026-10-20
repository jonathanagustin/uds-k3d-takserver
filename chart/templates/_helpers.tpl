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
