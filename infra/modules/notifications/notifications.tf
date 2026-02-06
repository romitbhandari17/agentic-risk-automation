variable "sf_trigger_lambda_arn" { type = string }
variable "bucket_id" { type = string }
variable "bucket_arn" { type = string }

locals {
  s3_notify = (var.sf_trigger_lambda_arn != "" && var.bucket_arn != "" && var.bucket_id != "") ? {
    invoke = var.sf_trigger_lambda_arn
  } : {}
}

# Allow S3 to invoke the trigger Lambda
resource "aws_lambda_permission" "allow_s3_invoke" {
  for_each      = local.s3_notify
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = each.value
  principal     = "s3.amazonaws.com"
  source_arn    = var.bucket_arn
}

# Configure S3 bucket notification to call the sf trigger Lambda on object created
resource "aws_s3_bucket_notification" "notify_trigger_lambda" {
  for_each = local.s3_notify
  bucket   = var.bucket_id

  lambda_function {
    lambda_function_arn = each.value
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke]
}

