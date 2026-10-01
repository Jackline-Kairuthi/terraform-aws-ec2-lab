# Run bash run.sh setup once. It fills this block with real backend settings.
# Do not enter invented bucket names at terraform init.
terraform {
  backend "s3" {}
}
