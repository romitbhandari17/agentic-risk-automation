# Module: Lambda functions - creates AWS Lambda functions for ingestion and risk analysis agents

# name_prefix - prefix used to construct the Lambda function names
variable "name_prefix" { type = string }

# ingestion_lambda_role_arn - IAM role ARN for ingestion Lambda
variable "ingestion_lambda_role_arn" { type = string }

# risk_analysis_lambda_role_arn - IAM role ARN for risk analysis Lambda
variable "risk_analysis_lambda_role_arn" { type = string }

# s3_bucket - S3 bucket name provided to the Lambda via env var
variable "s3_bucket" { type = string }

# ingestion_zip_path - path to ingestion Lambda zip package
variable "ingestion_zip_path" {
  type    = string
  default = ""
}

# Optional: precomputed base64-encoded sha256 of ingestion zip (useful for remote/TFE runs)
variable "ingestion_zip_hash" {
  type    = string
  default = ""
  description = "Base64-encoded SHA256 hash of the ingestion zip. If set, used for source_code_hash so remote runs detect changes."
}

# risk_analysis_zip_path - path to risk analysis Lambda zip package
variable "risk_analysis_zip_path" {
  type    = string
  default = ""
}

# Optional: precomputed base64-encoded sha256 of risk analysis zip
variable "risk_analysis_zip_hash" {
  type    = string
  default = ""
  description = "Base64-encoded SHA256 hash of the risk analysis zip. If set, used for source_code_hash."
}

# runtime - Lambda runtime (e.g., python3.10)
variable "runtime" {
  type    = string
  default = "python3.10"
}

# Ingestion Lambda function
resource "aws_lambda_function" "ingestion" {
  filename         = var.ingestion_zip_path != "" ? var.ingestion_zip_path : null
  function_name    = "${var.name_prefix}-ingestion"
  role             = var.ingestion_lambda_role_arn
  handler          = "main.handler"
  runtime          = var.runtime
  # Use provided hash if set (CI/TFE), otherwise compute from local file if available
  source_code_hash = var.ingestion_zip_hash != "" ? var.ingestion_zip_hash : (var.ingestion_zip_path != "" ? filebase64sha256(var.ingestion_zip_path) : null)
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      S3_BUCKET = var.s3_bucket
    }
  }
}

# Risk Analysis Lambda function
resource "aws_lambda_function" "risk_analysis" {
  filename         = var.risk_analysis_zip_path != "" ? var.risk_analysis_zip_path : null
  function_name    = "${var.name_prefix}-risk-analysis"
  role             = var.risk_analysis_lambda_role_arn
  handler          = "main.handler"
  runtime          = var.runtime
  source_code_hash = var.risk_analysis_zip_hash != "" ? var.risk_analysis_zip_hash : (var.risk_analysis_zip_path != "" ? filebase64sha256(var.risk_analysis_zip_path) : null)
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      S3_BUCKET = var.s3_bucket
    }
  }
}
