provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      Project     = var.cluster_name
      Environment = "lab"
      ManagedBy   = "Terraform"
    }
  }
}
