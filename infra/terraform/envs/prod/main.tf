# Production environment — root module.
# Composes all infrastructure modules for the prod cluster.

terraform {
  backend "s3" {
    bucket         = "astraeus-terraform-state"
    key            = "envs/prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "astraeus-terraform-locks"
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "astraeus"
      Environment = "prod"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  environment  = "prod"
  cluster_name = "astraeus-prod"

  node_groups = {
    system = {
      instance_types = ["t3.medium"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      labels         = { "astraeus.io/pool" = "system" }
      taints = [{
        key    = "CriticalAddonsOnly"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
    general = {
      instance_types = ["t3.large", "t3a.large"]
      min_size       = 2
      max_size       = 6
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels         = { "astraeus.io/pool" = "general" }
      taints         = []
    }
    data = {
      instance_types = ["r6g.large"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      labels         = { "astraeus.io/pool" = "data" }
      taints         = []
    }
    compute = {
      instance_types = ["c6i.xlarge", "c6a.xlarge"]
      min_size       = 0
      max_size       = 8
      desired_size   = 1
      capacity_type  = "SPOT"
      labels         = { "astraeus.io/pool" = "compute" }
      taints         = []
    }
    trading = {
      instance_types = ["t3.large"]
      min_size       = 2
      max_size       = 3
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      labels         = { "astraeus.io/pool" = "trading" }
      taints = [{
        key    = "astraeus.io/trading"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }
  }
}

module "network" {
  source      = "../../modules/network"
  cidr        = "10.20.0.0/16"
  azs         = ["us-east-1a", "us-east-1b", "us-east-1c"]
  environment = local.environment
}

module "eks" {
  source             = "../../modules/eks"
  cluster_name       = local.cluster_name
  subnet_ids         = module.network.private_subnet_ids
  environment        = local.environment
  kubernetes_version = "1.29"
  node_groups        = local.node_groups
}

module "rds_control" {
  source              = "../../modules/rds"
  identifier          = "astraeus-prod-control"
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_subnet_ids
  environment         = local.environment
  multi_az            = true
  backup_retention    = 35
  deletion_protection = true
  allowed_security_group_ids = [] # Populated by EKS node SG after creation
}

module "kms" {
  source      = "../../modules/kms"
  environment = local.environment
}

module "s3_data_lake" {
  source      = "../../modules/s3"
  bucket_name = "astraeus-prod-data-lake"
  environment = local.environment
}

module "s3_backups" {
  source      = "../../modules/s3"
  bucket_name = "astraeus-prod-backups"
  environment = local.environment
}

# IRSA roles for workloads
module "irsa_api" {
  source            = "../../modules/iam-irsa"
  cluster_name      = module.eks.cluster_name
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url
  namespace         = "research"
  service_account   = "api"
  role_name         = "astraeus-prod-api"
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [module.s3_data_lake.bucket_arn, "${module.s3_data_lake.bucket_arn}/*"]
    }]
  })
}

module "irsa_oms" {
  source            = "../../modules/iam-irsa"
  cluster_name      = module.eks.cluster_name
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url
  namespace         = "trading"
  service_account   = "oms"
  role_name         = "astraeus-prod-oms"
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = ["arn:aws:secretsmanager:us-east-1:*:secret:astraeus/prod/broker-*"]
    }]
  })
}

module "observability" {
  source                   = "../../modules/observability"
  environment              = local.environment
  log_retention_days       = 90
  audit_log_retention_days = 2555  # ~7 years for trading events
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "vpc_id" {
  value = module.network.vpc_id
}
