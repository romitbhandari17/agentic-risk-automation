# API Gateway module for triggering Step Functions via REST API

variable "name_prefix" { type = string }
variable "state_machine_arn" { type = string }
variable "api_gateway_role_arn" { type = string }

# REST API Gateway
resource "aws_api_gateway_rest_api" "contract_api" {
  name        = "${var.name_prefix}-contract-api"
  description = "API Gateway to trigger contract review workflow"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# Resource: /trigger-review
resource "aws_api_gateway_resource" "trigger_review" {
  rest_api_id = aws_api_gateway_rest_api.contract_api.id
  parent_id   = aws_api_gateway_rest_api.contract_api.root_resource_id
  path_part   = "trigger-review"
}

# Method: POST /trigger-review
resource "aws_api_gateway_method" "trigger_review_post" {
  rest_api_id   = aws_api_gateway_rest_api.contract_api.id
  resource_id   = aws_api_gateway_resource.trigger_review.id
  http_method   = "POST"
  authorization = "AWS_IAM"  # Use IAM for authentication
}

# Integration with Step Functions
resource "aws_api_gateway_integration" "step_functions" {
  rest_api_id             = aws_api_gateway_rest_api.contract_api.id
  resource_id             = aws_api_gateway_resource.trigger_review.id
  http_method             = aws_api_gateway_method.trigger_review_post.http_method
  integration_http_method = "POST"
  type                    = "AWS"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.name}:states:action/StartExecution"
  credentials             = var.api_gateway_role_arn

  request_templates = {
    "application/json" = <<EOF
{
  "input": "$util.escapeJavaScript($input.json('$'))",
  "stateMachineArn": "${var.state_machine_arn}"
}
EOF
  }
}

# Method response
resource "aws_api_gateway_method_response" "trigger_review_200" {
  rest_api_id = aws_api_gateway_rest_api.contract_api.id
  resource_id = aws_api_gateway_resource.trigger_review.id
  http_method = aws_api_gateway_method.trigger_review_post.http_method
  status_code = "200"

  response_models = {
    "application/json" = "Empty"
  }
}

# Integration response
resource "aws_api_gateway_integration_response" "trigger_review_200" {
  rest_api_id = aws_api_gateway_rest_api.contract_api.id
  resource_id = aws_api_gateway_resource.trigger_review.id
  http_method = aws_api_gateway_method.trigger_review_post.http_method
  status_code = aws_api_gateway_method_response.trigger_review_200.status_code

  depends_on = [aws_api_gateway_integration.step_functions]
}

# Deploy API
resource "aws_api_gateway_deployment" "contract_api" {
  rest_api_id = aws_api_gateway_rest_api.contract_api.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.trigger_review.id,
      aws_api_gateway_method.trigger_review_post.id,
      aws_api_gateway_integration.step_functions.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.step_functions
  ]
}

# Stage
resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.contract_api.id
  rest_api_id   = aws_api_gateway_rest_api.contract_api.id
  stage_name    = "prod"

  xray_tracing_enabled = true
}

# Usage plan (optional rate limiting)
resource "aws_api_gateway_usage_plan" "contract_api" {
  name = "${var.name_prefix}-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.contract_api.id
    stage  = aws_api_gateway_stage.prod.stage_name
  }

  throttle_settings {
    burst_limit = 100
    rate_limit  = 50
  }

  quota_settings {
    limit  = 1000
    period = "DAY"
  }
}

data "aws_region" "current" {}
