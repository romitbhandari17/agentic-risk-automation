output "s3_bucket" {
  value = module.s3.bucket
}

output "lambda_role_arn" {
  value = module.iam.lambda_role_arn
}

output "sfn_role_arn" {
  value = module.iam.sfn_role_arn
}

output "lambda_arn" {
  value = module.lambda.lambda_arn
}

output "state_machine_arn" {
  value = module.step_functions.state_machine_arn
}

output "bedrock_ssm_parameter" {
  value = module.bedrock.bedrock_ssm_parameter
}
