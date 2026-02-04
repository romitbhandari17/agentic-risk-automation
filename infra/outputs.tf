output "s3_bucket" {
  value = module.s3.bucket
}

output "ingestion_lambda_role_arn" {
  value = module.iam.ingestion_lambda_role_arn
}

output "risk_analysis_lambda_role_arn" {
  value = module.iam.risk_analysis_lambda_role_arn
}

output "sfn_role_arn" {
  value = module.iam.sfn_role_arn
}

output "ingestion_lambda_arn" {
  value       = module.lambda.ingestion_lambda_arn
  description = "Ingestion Lambda ARN"
}

output "risk_analysis_lambda_arn" {
  value       = module.lambda.risk_analysis_lambda_arn
  description = "Risk Analysis Lambda ARN"
}

output "state_machine_arn" {
  value = module.step_functions.state_machine_arn
}

output "bedrock_ssm_parameter" {
  value = module.bedrock.bedrock_ssm_parameter
}
