output "ingestion_lambda_arn" {
  description = "ARN of the Ingestion Lambda function"
  value       = aws_lambda_function.ingestion.arn
}

output "risk_analysis_lambda_arn" {
  description = "ARN of the Risk Analysis Lambda function"
  value       = aws_lambda_function.risk_analysis.arn
}


output "sf_trigger_lambda_arn" {
  description = "ARN of the SF Trigger Lambda function"
  value       = aws_lambda_function.sf_trigger.arn
}


output "sf_trigger_lambda_name" {
  description = "Name of the SF Trigger Lambda function"
  value       = aws_lambda_function.sf_trigger.function_name
}
