{{- define "daleel.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "daleel.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Selector labels for one component: (dict "ctx" $ "component" "api") */}}
{{- define "daleel.selector" -}}
app.kubernetes.io/name: {{ .ctx.Chart.Name }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "daleel.image" -}}
{{ .ctx.Values.image.registry }}/daleel-{{ .component }}:{{ .ctx.Values.image.tag | default .ctx.Chart.AppVersion }}
{{- end -}}

{{- define "daleel.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- .Values.serviceAccount.name | default (include "daleel.fullname" .) -}}
{{- else -}}
{{- .Values.serviceAccount.name | default "default" -}}
{{- end -}}
{{- end -}}

{{- define "daleel.secretName" -}}
{{- .Values.existingSecret | default (printf "%s-env" (include "daleel.fullname" .)) -}}
{{- end -}}

{{/* Host names of the dev dependencies. */}}
{{- define "daleel.devHost" -}}
{{ include "daleel.fullname" .ctx }}-{{ .name }}
{{- end -}}

{{/* Secret values, with the dev dependencies' connection strings filled in when dev.enabled. */}}
{{- define "daleel.secretEnv" -}}
{{- $env := deepCopy .Values.secretEnv -}}
{{- if .Values.dev.enabled -}}
{{- $pg := include "daleel.devHost" (dict "ctx" . "name" "postgres") -}}
{{- $_ := set $env "DATABASE_URL" (printf "postgresql+asyncpg://%s:%s@%s:5432/daleel" .Values.env.APP_DB_USER .Values.dev.postgres.appPassword $pg) -}}
{{- $_ := set $env "MIGRATIONS_DATABASE_URL" (printf "postgresql+asyncpg://daleel:%s@%s:5432/daleel" .Values.dev.postgres.password $pg) -}}
{{- $_ := set $env "REDIS_URL" (printf "redis://%s:6379/0" (include "daleel.devHost" (dict "ctx" . "name" "redis"))) -}}
{{- $_ := set $env "S3_ACCESS_KEY" .Values.dev.minio.accessKey -}}
{{- $_ := set $env "S3_SECRET_KEY" .Values.dev.minio.secretKey -}}
{{- end -}}
{{- toYaml $env -}}
{{- end -}}

{{- define "daleel.env" -}}
{{- $env := deepCopy .Values.env -}}
{{- if .Values.dev.enabled -}}
{{- $_ := set $env "S3_ENDPOINT" (printf "%s:9000" (include "daleel.devHost" (dict "ctx" . "name" "minio"))) -}}
{{- $_ := set $env "S3_SECURE" "false" -}}
{{- end -}}
{{- toYaml $env -}}
{{- end -}}

{{/* envFrom for the API and worker. */}}
{{- define "daleel.envFrom" -}}
- configMapRef:
    name: {{ include "daleel.fullname" . }}-env
- secretRef:
    name: {{ include "daleel.secretName" . }}
{{- end -}}

{{/* Restarts pods when the configuration changes. */}}
{{- define "daleel.configChecksum" -}}
checksum/env: {{ printf "%s%s" (include "daleel.env" .) (include "daleel.secretEnv" .) | sha256sum }}
{{- end -}}
