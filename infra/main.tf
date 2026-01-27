// Terraform entrypoint for infra modules
// ...placeholder for Terraform configuration...

terraform {
  # Bump minimum Terraform version to 1.5 to use newer features and provider versions.
  required_version = ">= 1.0"
}

# Add module calls for s3, iam, dynamodb, lambda, step-functions in each environment
# file: infra/main.tf
module "s3" {
  source      = "./modules/s3"
  name_prefix = "${var.project}-${var.env}"
}

module "iam" {
  source      = "./modules/iam"
  name_prefix = "${var.project}-${var.env}"
}

module "lambda" {
  source        = "./modules/lambda"
  name_prefix   = "${var.project}-${var.env}"
  lambda_role_arn = module.iam.lambda_role_arn
  s3_bucket     = module.s3.bucket
  zip_path      = var.lambda_zip_path
}

module "step_functions" {
  source            = "./modules/step-functions"
  name_prefix       = "${var.project}-${var.env}"
  state_machine_role_arn = module.iam.sfn_role_arn
  definition        = file("${path.module}/../step_functions/contract_review.asl.json")
}

module "bedrock" {
  source      = "./modules/bedrock"
  name_prefix = "${var.project}-${var.env}"
}

# Provide AWS account info for reference; useful for building ARNs or config
data "aws_caller_identity" "current" {}
