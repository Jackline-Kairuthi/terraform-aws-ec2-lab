terraform {
  required_version = ">= 1.10, < 1.17"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.59, < 7.0"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = var.cluster_name
      Environment = "lab"
      ManagedBy   = "Terraform"
    }
  }
}
