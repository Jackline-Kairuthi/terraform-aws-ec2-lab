output "state_bucket_name" {
  value = aws_s3_bucket.state.id
}

output "lock_table_name" {
  value = aws_dynamodb_table.locks.name
}

# These strings generate backend configuration files without manual copying.
output "infra_backend_config" {
  value = <<-EOT
bucket         = "${aws_s3_bucket.state.id}"
key            = "eks-lab/infra/terraform.tfstate"
region         = "${var.aws_region}"
encrypt        = true
dynamodb_table = "${aws_dynamodb_table.locks.name}"
EOT
}

output "bootstrap_backend_config" {
  value = <<-EOT
bucket         = "${aws_s3_bucket.state.id}"
key            = "eks-lab/bootstrap/terraform.tfstate"
region         = "${var.aws_region}"
encrypt        = true
dynamodb_table = "${aws_dynamodb_table.locks.name}"
EOT
}
