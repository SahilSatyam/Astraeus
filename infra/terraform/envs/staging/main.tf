# Staging environment — mirrors prod topology at smaller scale.

terraform {
  backend "s3" {
    bucket         = "astraeus-terraform-state"
    key            = "envs/staging/terraform.tfstate"
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
      Environment = "staging"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  environment  = "staging"
  cluster_name = "astraeus-staging"

  node_groups = {
    general = {
      instance_types = ["t3.medium", "t3a.medium"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      capacity_type  = "ON_DEMAND"
      labels         = { "astraeus.io/pool" = "general" }
      taints         = []
    }
    trading = {
      instance_types = ["t3.medium"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
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
  cidr        = "10.25.0.0/16"
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
  identifier          = "astraeus-staging-control"
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_subnet_ids
  environment         = local.environment
  multi_az            = true
  backup_retention    = 14
  deletion_protection = false
}

module "kms" {
  source      = "../../modules/kms"
  environment = local.environment
}

module "s3_data_lake" {
  source      = "../../modules/s3"
  bucket_name = "astraeus-staging-data-lake"
  environment = local.environment
}
