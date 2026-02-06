variable "name_prefix" { type = string }
variable "ingestion_lambda_role_name" { type = string }
variable "risk_analysis_lambda_role_name" { type = string }
variable "sfn_role_name" {
  type    = string
  default = ""
}
variable "sf_trigger_lambda_role_name" {
  type    = string
  default = ""
}
variable "state_machine_arn" {
  type    = string
  default = ""
}

# Inline policy for Ingestion Lambda - S3, Textract, Bedrock access
resource "aws_iam_role_policy" "ingestion_lambda_policy" {
  name = "${var.name_prefix}-ingestion-lambda-policy"
  role = var.ingestion_lambda_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:PutObject"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          # Support both synchronous and asynchronous Textract APIs used by the ingestion lambda
          "textract:DetectDocumentText",
          "textract:AnalyzeDocument",
          "textract:StartDocumentTextDetection",
          "textract:GetDocumentTextDetection",
          "textract:StartDocumentAnalysis",
          "textract:GetDocumentAnalysis"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          "bedrock:InvokeModel"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

# Inline policy for Risk Analysis Lambda - S3 read, Bedrock access
resource "aws_iam_role_policy" "risk_analysis_lambda_policy" {
  name = "${var.name_prefix}-risk-analysis-lambda-policy"
  role = var.risk_analysis_lambda_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:GetObject"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          "bedrock:InvokeModel"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

# Ensure Lambda role has permission to start Step Functions
resource "aws_iam_role_policy" "lambda_trigger_sfn_policy" {
  name = "${var.name_prefix}-trigger-sf-lambda-policy"
  role = var.sf_trigger_lambda_role_name  # <\-- replace with your lambda exec role resource

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution"
        ]
        Resource = var.state_machine_arn  # <\-- replace with your state machine
      },
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}


# Inline policy attached to the Step Functions role
# - Purpose: allows Step Functions to invoke Lambda functions and write logs
# - NOTE: This example uses Resource = "*" for simplicity; replace with specific ARNs for least privilege
resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name = "${var.name_prefix}-sfn-invoke-lambda"
  role = var.sfn_role_name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "lambda:InvokeFunction"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}