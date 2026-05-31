# KMS module — Encryption keys for platform-wide use.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "project" {
  description = "Project name"
  type        = string
  default     = "astraeus"
}

# General-purpose encryption key (EBS, envelope encryption)
resource "aws_kms_key" "general" {
  description             = "${var.project}-${var.environment} general encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  multi_region            = false

  policy = data.aws_iam_policy_document.kms_policy.json

  tags = {
    Name        = "${var.project}-${var.environment}-general"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_kms_alias" "general" {
  name          = "alias/${var.project}-${var.environment}-general"
  target_key_id = aws_kms_key.general.key_id
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "kms_policy" {
  # Allow root account full access
  statement {
    sid    = "EnableRootAccountAccess"
    effect = "Allow"
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
    actions   = ["kms:*"]
    resources = ["*"]
  }

  # Allow EKS service to use the key
  statement {
    sid    = "AllowEKSService"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
  }
}

output "general_key_arn" {
  value = aws_kms_key.general.arn
}

output "general_key_id" {
  value = aws_kms_key.general.key_id
}
