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
  ingestion_lambda_role_arn = module.iam.ingestion_lambda_role_arn
  risk_analysis_lambda_role_arn = module.iam.risk_analysis_lambda_role_arn
  s3_bucket     = module.s3.bucket
  ingestion_zip_path = var.ingestion_zip_path
  risk_analysis_zip_path = var.risk_analysis_zip_path
  sf_trigger_lambda_role_arn = module.iam.sf_trigger_lambda_role_arn
  sf_trigger_zip_path = var.sf_trigger_zip_path
}


module "step_functions" {
  source            = "./modules/step-functions"
  name_prefix       = "${var.project}-${var.env}"
  state_machine_role_arn = module.iam.sfn_role_arn
  definition        = templatefile("${path.module}/../step_functions/contract_review.asl.json", {
    IngestionLambdaArn = module.lambda.ingestion_lambda_arn
    RiskAnalysisLambdaArn = module.lambda.risk_analysis_lambda_arn
  })
}

module "bedrock" {
  source      = "./modules/bedrock"
  name_prefix = "${var.project}-${var.env}"
}

module "notifications" {
  source                = "./modules/notifications"
  sf_trigger_lambda_arn = module.lambda.sf_trigger_lambda_arn
  bucket_id             = module.s3.bucket
  bucket_arn            = module.s3.bucket_arn

  # ensure this module is applied after lambda and s3
  depends_on = [module.lambda, module.s3]
}

module "iam_bindings" {
  source      = "./modules/iam_bindings"
  name_prefix = "${var.project}-${var.env}"
  risk_analysis_lambda_role_name = module.iam.risk_analysis_lambda_role_name
  ingestion_lambda_role_name = module.iam.ingestion_lambda_role_name
  sfn_role_name = module.iam.sfn_role_name
  state_machine_arn = module.step_functions.state_machine_arn
  sf_trigger_lambda_role_name = module.iam.sf_trigger_lambda_role_name

  depends_on = [module.iam, module.step_functions]
}

# Provide AWS account info for reference; useful for building ARNs or config
data "aws_caller_identity" "current" {}
