# file: modules/iam/outputs.tf
output "ingestion_lambda_role_arn" {
  description = "ARN of the Ingestion Lambda execution role"
  value       = aws_iam_role.ingestion_lambda_role.arn
}

output "risk_analysis_lambda_role_arn" {
  description = "ARN of the Risk Analysis Lambda execution role"
  value       = aws_iam_role.risk_analysis_lambda_role.arn
}

output "sfn_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = aws_iam_role.sfn_role.arn
}

output "sf_trigger_lambda_role_arn" {
  description = "ARN of the trigger lambda execution role"
  value       = aws_iam_role.sf_trigger_lambda_role.arn
}


output "ingestion_lambda_role_name" {
  description = "Name of the Ingestion Lambda execution role"
  value       = aws_iam_role.ingestion_lambda_role.name
}

output "risk_analysis_lambda_role_name" {
  description = "Name of the Risk Analysis Lambda execution role"
  value       = aws_iam_role.risk_analysis_lambda_role.name
}

output "sfn_role_name" {
  description = "Name of the Step Functions execution role"
  value       = aws_iam_role.sfn_role.name
}

output "sf_trigger_lambda_role_name" {
  description = "Name of the trigger lambda execution role"
  value       = aws_iam_role.sf_trigger_lambda_role.name
}