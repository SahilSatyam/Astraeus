{{- define "astraeus-workers.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "astraeus-workers.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "astraeus-workers.labels" -}}
helm.sh/chart: {{ include "astraeus-workers.name" . }}-{{ .Chart.Version }}
{{ include "astraeus-workers.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "astraeus-workers.selectorLabels" -}}
app.kubernetes.io/name: {{ include "astraeus-workers.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "astraeus-workers.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "astraeus-workers.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
