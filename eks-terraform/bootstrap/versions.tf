terraform {
  required_version = ">= 1.10, < 1.17"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.59, < 7.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project   = "eks-lab"
      ManagedBy = "Terraform"
    }
  }
}
