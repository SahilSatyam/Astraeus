# S3 module — Data lake, backups, and MLflow artifact storage.

variable "bucket_name" {
  description = "S3 bucket name"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "enable_replication" {
  description = "Enable cross-region replication"
  type        = bool
  default     = false
}

variable "replication_destination_bucket_arn" {
  description = "Destination bucket ARN for replication"
  type        = string
  default     = ""
}

resource "aws_kms_key" "s3" {
  description             = "S3 encryption key for ${var.bucket_name}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_s3_bucket" "main" {
  bucket = var.bucket_name

  tags = {
    Name        = var.bucket_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "main" {
  bucket = aws_s3_bucket.main.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    id     = "raw-ticks-to-glacier"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    transition {
      days          = 180
      storage_class = "GLACIER"
    }
  }

  rule {
    id     = "backups-to-glacier"
    status = "Enabled"

    filter {
      prefix = "backups/"
    }

    transition {
      days          = 30
      storage_class = "GLACIER"
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {
      prefix = ""
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

output "bucket_arn" {
  value = aws_s3_bucket.main.arn
}

output "bucket_name" {
  value = aws_s3_bucket.main.id
}

output "kms_key_arn" {
  value = aws_kms_key.s3.arn
}
