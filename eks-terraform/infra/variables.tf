variable "aws_region" {
  description = "AWS region for VPC and EKS."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster and VPC naming prefix."
  type        = string
  default     = "eks-lab"
}

variable "kubernetes_version" {
  description = "EKS version; confirm regional availability before applying."
  type        = string
  default     = "1.35"
}

variable "admin_cidr" {
  description = "Your public IPv4 address with /32, permitted to reach the Kubernetes API."
  type        = string
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && can(regex("/32$", var.admin_cidr))
    error_message = "Provide your public IPv4 address followed by /32."
  }
}

variable "admin_principal_arn" {
  description = "Permanent IAM role or user ARN for kubectl administration; never an STS assumed-role session ARN."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(role|user)/.+$", var.admin_principal_arn))
    error_message = "Provide an IAM role or user ARN (arn:aws:iam::ACCOUNT:role/NAME), not an STS or root ARN."
  }
}

variable "node_instance_type" {
  description = "EC2 worker type."
  type        = string
  default     = "t3.medium"
}
