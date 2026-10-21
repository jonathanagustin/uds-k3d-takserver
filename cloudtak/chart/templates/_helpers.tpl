{{/*
Copyright 2026 uds-k3d-takserver authors
SPDX-License-Identifier: GPL-3.0-only
*/}}

{{- define "cloudtak.url" -}}
https://{{ .Values.host }}.{{ .Values.domain }}
{{- end }}

{{- define "cloudtak.svc" -}}
{{ .name }}.{{ .ns }}.svc.cluster.local
{{- end }}

{{/* Restricted pod security that UDS policies accept. */}}
{{- define "cloudtak.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}

{{/* "true" or "false". Accepts a boolean or a string from a deploy variable. */}}
{{- define "cloudtak.basemap.enabled" -}}
{{- if eq (toString .Values.basemap.enabled) "true" }}true{{ else }}false{{ end }}
{{- end }}

{{/* Host of basemap.url, without the port. */}}
{{- define "cloudtak.basemap.host" -}}
{{- $u := urlParse (.Values.basemap.url | replace "{z}" "0" | replace "{x}" "0" | replace "{y}" "0") }}
{{- if not (has $u.scheme (list "https" "http")) }}{{ fail "basemap.url must be an http or https URL" }}{{ end }}
{{- (split ":" $u.host)._0 }}
{{- end }}

{{/* Egress port for basemap.url. */}}
{{- define "cloudtak.basemap.port" -}}
{{- $u := urlParse (.Values.basemap.url | replace "{z}" "0" | replace "{x}" "0" | replace "{y}" "0") }}
{{- $parts := split ":" $u.host }}
{{- if .Values.basemap.port }}{{ .Values.basemap.port }}
{{- else if $parts._1 }}{{ $parts._1 }}
{{- else if eq $u.scheme "https" }}443
{{- else }}80
{{- end }}
{{- end }}

{{- define "cloudtak.basemap.userAgent" -}}
{{- if .Values.basemap.userAgent }}{{ .Values.basemap.userAgent }}
{{- else -}}
CloudTAK/{{ .Values.image.tag | trimPrefix "v" }} (uds-k3d-takserver; +https://github.com/jonathanagustin/uds-k3d-takserver{{ with .Values.basemap.contact }}; contact: {{ . }}{{ end }})
{{- end }}
{{- end }}

{{/* Basemap settings for the cloudtak and bootstrap containers. */}}
{{- define "cloudtak.basemap.env" -}}
- name: BASEMAP_ENABLED
  value: {{ include "cloudtak.basemap.enabled" . | quote }}
{{- if eq (include "cloudtak.basemap.enabled" .) "true" }}
- name: BASEMAP_URL
  value: {{ .Values.basemap.url | quote }}
- name: BASEMAP_PUBLIC_URL
  value: {{ include "cloudtak.url" . | quote }}
- name: BASEMAP_NAME
  value: {{ .Values.basemap.name | quote }}
- name: BASEMAP_ATTRIBUTION
  value: {{ .Values.basemap.attribution | quote }}
- name: BASEMAP_MINZOOM
  value: {{ .Values.basemap.minzoom | quote }}
- name: BASEMAP_MAXZOOM
  value: {{ .Values.basemap.maxzoom | quote }}
- name: BASEMAP_DEFAULT
  value: {{ toString .Values.basemap.default | quote }}
- name: BASEMAP_USER_AGENT
  value: {{ include "cloudtak.basemap.userAgent" . | quote }}
- name: BASEMAP_CACHE_SIZE
  value: {{ .Values.basemap.cacheSize | quote }}
- name: BASEMAP_RATE
  value: {{ .Values.basemap.rate | quote }}
- name: BASEMAP_BURST
  value: {{ .Values.basemap.burst | quote }}
{{- end }}
{{- end }}
