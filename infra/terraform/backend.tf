# Remote state configuration — S3 + DynamoDB lock.
# Each environment uses its own state file via workspace or key prefix.
terraform {
  backend "s3" {
    bucket         = "astraeus-terraform-state"
    key            = "global/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "astraeus-terraform-locks"
  }
}
