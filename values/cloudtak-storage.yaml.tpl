{{- if .Variables.CLOUDTAK_STORAGE_CLASS }}
# CloudTAK PostGIS data volume. Set only when CLOUDTAK_STORAGE_CLASS is not
# empty, so the default render is unchanged.
postgis:
  storageClass: {{ .Variables.CLOUDTAK_STORAGE_CLASS | quote }}
{{- else }}
{}
{{- end }}
