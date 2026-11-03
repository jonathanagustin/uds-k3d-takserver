{{- if .Variables.POSTGRES_STORAGE_CLASS }}
# Bitnami PostgreSQL 12.1.6, the TAK chart's subchart. Set only when
# POSTGRES_STORAGE_CLASS is not empty, so the default render is unchanged.
postgresql:
  primary:
    persistence:
      storageClass: {{ .Variables.POSTGRES_STORAGE_CLASS | quote }}
{{- else }}
{}
{{- end }}
