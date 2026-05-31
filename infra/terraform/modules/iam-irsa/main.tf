# IAM-IRSA module — Workload identity for Kubernetes pods.
# Creates an IAM role that a specific ServiceAccount in a specific namespace can assume.

variable "cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "oidc_provider_arn" {
  description = "OIDC provider ARN from EKS"
  type        = string
}

variable "oidc_provider_url" {
  description = "OIDC provider URL (without https://)"
  type        = string
}

variable "namespace" {
  description = "Kubernetes namespace"
  type        = string
}

variable "service_account" {
  description = "Kubernetes ServiceAccount name"
  type        = string
}

variable "role_name" {
  description = "IAM role name"
  type        = string
}

variable "policy_arns" {
  description = "List of IAM policy ARNs to attach"
  type        = list(string)
  default     = []
}

variable "inline_policy" {
  description = "Inline policy JSON (optional)"
  type        = string
  default     = ""
}

resource "aws_iam_role" "irsa" {
  name = var.role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = var.oidc_provider_arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${var.oidc_provider_url}:sub" = "system:serviceaccount:${var.namespace}:${var.service_account}"
          "${var.oidc_provider_url}:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = {
    Cluster        = var.cluster_name
    Namespace      = var.namespace
    ServiceAccount = var.service_account
    ManagedBy      = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "policies" {
  for_each   = toset(var.policy_arns)
  role       = aws_iam_role.irsa.name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "inline" {
  count  = var.inline_policy != "" ? 1 : 0
  name   = "${var.role_name}-inline"
  role   = aws_iam_role.irsa.id
  policy = var.inline_policy
}

output "role_arn" {
  value = aws_iam_role.irsa.arn
}

output "role_name" {
  value = aws_iam_role.irsa.name
}
