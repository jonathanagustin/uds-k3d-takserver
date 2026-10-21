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
