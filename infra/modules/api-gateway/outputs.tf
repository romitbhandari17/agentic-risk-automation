output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = "${aws_api_gateway_stage.prod.invoke_url}/trigger-review"
}

output "api_id" {
  description = "API Gateway ID"
  value       = aws_api_gateway_rest_api.contract_api.id
}

output "api_arn" {
  description = "API Gateway execution ARN"
  value       = aws_api_gateway_rest_api.contract_api.execution_arn
}
