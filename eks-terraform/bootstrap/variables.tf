variable "aws_region" {
  description = "Region for the state bucket and locking table."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name; lowercase letters, digits and hyphens."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "Use 3-63 lowercase letters, digits or hyphens, starting and ending with a letter or digit."
  }
}

variable "lock_table_name" {
  description = "DynamoDB table used for Terraform state locking."
  type        = string
  default     = "eks-lab-terraform-locks"
}
