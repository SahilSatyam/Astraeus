{{- define "astraeus-oms.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "astraeus-oms.fullname" -}}
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

{{- define "astraeus-oms.labels" -}}
helm.sh/chart: {{ include "astraeus-oms.name" . }}-{{ .Chart.Version }}
{{ include "astraeus-oms.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "astraeus-oms.selectorLabels" -}}
app.kubernetes.io/name: {{ include "astraeus-oms.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "astraeus-oms.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "astraeus-oms.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
