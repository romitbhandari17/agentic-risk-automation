# Variable: name_prefix
# - Input: short name used to prefix all IAM role/resource names in this module
# - Example: if project-env -> roles will be named "project-env-lambda-role" and "project-env-sfn-role"
variable "name_prefix" {
  type = string
}

# Data: IAM policy document for Lambda assume role
# - Builds the JSON trust policy that lets the lambda.amazonaws.com service assume the role
# - Kept as a data source so it can be referenced cleanly from the role resource
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

# IAM Role: Ingestion Lambda execution role
# - Purpose: role assumed by Ingestion Lambda function
# - Permissions: CloudWatch Logs, S3 read/write, Textract, Bedrock
resource "aws_iam_role" "ingestion_lambda_role" {
  name = "${var.name_prefix}-ingestion-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Attach managed AWS policy for basic Lambda execution
resource "aws_iam_role_policy_attachment" "ingestion_lambda_basic" {
  role       = aws_iam_role.ingestion_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline policy for Ingestion Lambda - S3, Textract, Bedrock access
resource "aws_iam_role_policy" "ingestion_lambda_policy" {
  name = "${var.name_prefix}-ingestion-lambda-policy"
  role = aws_iam_role.ingestion_lambda_role.id

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
          "textract:DetectDocumentText",
          "textract:AnalyzeDocument"
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

# IAM Role: Risk Analysis Lambda execution role
# - Purpose: role assumed by Risk Analysis Lambda function
# - Permissions: CloudWatch Logs, S3 read, Bedrock
resource "aws_iam_role" "risk_analysis_lambda_role" {
  name = "${var.name_prefix}-risk-analysis-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Attach managed AWS policy for basic Lambda execution
resource "aws_iam_role_policy_attachment" "risk_analysis_lambda_basic" {
  role       = aws_iam_role.risk_analysis_lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Inline policy for Risk Analysis Lambda - S3 read, Bedrock access
resource "aws_iam_role_policy" "risk_analysis_lambda_policy" {
  name = "${var.name_prefix}-risk-analysis-lambda-policy"
  role = aws_iam_role.risk_analysis_lambda_role.id

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

# IAM Role: Step Functions execution role
# - Purpose: role assumed by Step Functions state machines when they execute tasks
# - Trust policy below allows the states.amazonaws.com service to assume this role
resource "aws_iam_role" "sfn_role" {
  name = "${var.name_prefix}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

# Data: IAM policy document for Step Functions assume role
# - Allows the Step Functions service principal to assume the role
data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

# Inline policy attached to the Step Functions role
# - Purpose: allows Step Functions to invoke Lambda functions and write logs
# - NOTE: This example uses Resource = "*" for simplicity; replace with specific ARNs for least privilege
resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name = "${var.name_prefix}-sfn-invoke-lambda"
  role = aws_iam_role.sfn_role.id

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
