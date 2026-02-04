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