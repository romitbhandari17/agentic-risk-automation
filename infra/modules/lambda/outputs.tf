output "ingestion_lambda_arn" {
  description = "ARN of the Ingestion Lambda function"
  value       = aws_lambda_function.ingestion.arn
}

output "risk_analysis_lambda_arn" {
  description = "ARN of the Risk Analysis Lambda function"
  value       = aws_lambda_function.risk_analysis.arn
}
