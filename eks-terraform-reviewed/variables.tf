# Every input has a default, so Terraform never asks for a variable interactively.
# Setup replaces sentinel defaults through generated.auto.tfvars.json.
variable "aws_region" {
  description = "Deployment region."
  type        = string
  default     = "us-east-1"
}

variable "expected_account_id" {
  description = "Account captured by setup; prevents accidental account changes."
  type        = string
  default     = "SETUP_REQUIRED"
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Run bash run.sh setup to generate the expected AWS account ID."
  }
}

variable "cluster_name" {
  type    = string
  default = "eks-lab"
  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$", var.cluster_name))
    error_message = "Use 1-50 letters, digits, hyphens or underscores, starting with a letter or digit."
  }
}

variable "kubernetes_version" {
  type    = string
  default = "1.35"
  validation {
    condition     = can(regex("^1[.][0-9]+$", var.kubernetes_version))
    error_message = "Use an EKS minor version such as 1.35."
  }
}

variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "admin_cidr" {
  description = "Public IPv4 of the kubectl machine; detected by setup unless overridden."
  type        = string
  default     = "SETUP_REQUIRED"
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && can(regex("/32$", var.admin_cidr))
    error_message = "Run bash run.sh setup, or set admin_cidr to a real public IPv4/32 in settings.json."
  }
}

variable "admin_principal_arn" {
  description = "Existing IAM role/user ARN, including any IAM role path."
  type        = string
  default     = "SETUP_REQUIRED"
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+$", var.admin_principal_arn))
    error_message = "Run setup or configure a permanent commercial-AWS IAM role/user ARN; never use an STS session or root ARN."
  }
}

variable "availability_zones" {
  description = "Two instance-compatible availability zones selected by setup."
  type        = list(string)
  default     = []
  validation {
    condition     = length(var.availability_zones) == 2 && length(distinct(var.availability_zones)) == 2
    error_message = "Run setup to select two distinct eligible availability zones."
  }
}
