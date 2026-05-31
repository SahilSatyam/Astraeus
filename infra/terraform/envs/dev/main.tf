# Dev environment — minimal footprint for ephemeral testing.
# Uses smaller instances, single-AZ, no multi-AZ RDS.

terraform {
  backend "s3" {
    bucket         = "astraeus-terraform-state"
    key            = "envs/dev/terraform.tfstate"
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
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  environment  = "dev"
  cluster_name = "astraeus-dev"

  node_groups = {
    general = {
      instance_types = ["t3.medium"]
      min_size       = 1
      max_size       = 3
      desired_size   = 2
      capacity_type  = "SPOT"
      labels         = { "astraeus.io/pool" = "general" }
      taints         = []
    }
  }
}

module "network" {
  source      = "../../modules/network"
  cidr        = "10.30.0.0/16"
  azs         = ["us-east-1a", "us-east-1b"]
  environment = local.environment
}

module "eks" {
  source             = "../../modules/eks"
  cluster_name       = local.cluster_name
  vpc_id             = module.network.vpc_id
  subnet_ids         = module.network.private_subnet_ids
  environment        = local.environment
  kubernetes_version = "1.29"
  node_groups        = local.node_groups
}

module "rds_control" {
  source              = "../../modules/rds"
  identifier          = "astraeus-dev-control"
  vpc_id              = module.network.vpc_id
  subnet_ids          = module.network.private_subnet_ids
  environment         = local.environment
  instance_class      = "db.t4g.small"
  allocated_storage   = 20
  multi_az            = false
  backup_retention    = 7
  deletion_protection = false
}

module "s3_data_lake" {
  source      = "../../modules/s3"
  bucket_name = "astraeus-dev-data-lake"
  environment = local.environment
}
