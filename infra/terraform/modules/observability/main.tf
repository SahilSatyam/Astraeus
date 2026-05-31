# Observability module — managed Grafana workspace (optional) and log retention.

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

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 90
}

variable "audit_log_retention_days" {
  description = "Audit log retention in days (trading events)"
  type        = number
  default     = 2555  # ~7 years
}

# CloudWatch log groups for EKS
resource "aws_cloudwatch_log_group" "eks_cluster" {
  name              = "/aws/eks/${var.project}-${var.environment}/cluster"
  retention_in_days = var.log_retention_days

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_log_group" "audit" {
  name              = "/astraeus/${var.environment}/audit"
  retention_in_days = var.audit_log_retention_days

  tags = {
    Environment = var.environment
    DataClass   = "audit-trading"
    ManagedBy   = "terraform"
  }
}

# S3 bucket for long-term log archival (immutable for audit compliance)
resource "aws_kms_key" "audit_logs" {
  description             = "Encryption key for ${var.project}-${var.environment} audit logs"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_s3_bucket" "audit_logs" {
  bucket = "${var.project}-${var.environment}-audit-logs"

  tags = {
    Environment = var.environment
    DataClass   = "audit-trading"
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.audit_logs.arn
    }
    bucket_key_enabled = true
  }
}

# Object Lock for immutability (compliance mode — cannot be deleted even by root)
resource "aws_s3_bucket_object_lock_configuration" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.audit_log_retention_days
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit_logs" {
  bucket = aws_s3_bucket.audit_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

output "audit_log_bucket_arn" {
  value = aws_s3_bucket.audit_logs.arn
}

output "eks_log_group_name" {
  value = aws_cloudwatch_log_group.eks_cluster.name
}
