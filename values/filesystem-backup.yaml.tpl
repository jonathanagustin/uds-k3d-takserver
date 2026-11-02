{{- if eq .Variables.FILESYSTEM_BACKUP "true" }}
# Bitnami PostgreSQL 12.1.6 names the data volume "data".
# Velero backs that volume up only when the node-agent is running.
postgresql:
  primary:
    podAnnotations:
      backup.velero.io/backup-volumes: data
{{- else }}
{}
{{- end }}
