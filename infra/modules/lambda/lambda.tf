# Module: Lambda function (agent) - creates an AWS Lambda for the agent; expects a zip_path or S3 deployment.

# name_prefix - prefix used to construct the Lambda function name
variable "name_prefix" { type = string }

# lambda_role_arn - IAM role ARN that the Lambda will assume
variable "lambda_role_arn" { type = string }

# s3_bucket - S3 bucket name provided to the Lambda via env var
variable "s3_bucket" { type = string }

# aws_lambda_function.agent - Lambda resource; uses local zip_path (or switch to S3-based deployment)
resource "aws_lambda_function" "agent" {
  filename         = var.zip_path != "" ? var.zip_path : ""
  function_name    = "${var.name_prefix}-agent"
  role             = var.lambda_role_arn
  handler          = var.handler
  runtime          = var.runtime
  source_code_hash = filebase64sha256(var.zip_path)
  timeout          = 30

  environment {
    variables = {
      S3_BUCKET = var.s3_bucket
    }
  }
}

# zip_path - path to local zip package (leave empty if using S3 deployment)
variable "zip_path" {
  type    = string
}

# handler - entrypoint inside the package (e.g., "main.handler")
variable "handler" {
  type    = string
  default = "main.handler"
}

# runtime - Lambda runtime (e.g., python3.10)
variable "runtime" {
  type    = string
  default = "python3.10"
}
