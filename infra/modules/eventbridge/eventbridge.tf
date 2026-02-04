# EventBridge module for triggering Step Functions from S3 uploads

variable "name_prefix" { type = string }
variable "s3_bucket_name" { type = string }
variable "s3_bucket_arn" { type = string }
variable "state_machine_arn" { type = string }
variable "eventbridge_role_arn" { type = string }

# EventBridge rule to capture S3 object created events
resource "aws_cloudwatch_event_rule" "s3_contract_upload" {
  name        = "${var.name_prefix}-s3-contract-upload"
  description = "Trigger Step Functions when contract is uploaded to S3"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = {
        name = [var.s3_bucket_name]
      }
      object = {
        key = [{
          prefix = "contracts/"
        }]
      }
    }
  })
}

# EventBridge target to invoke Step Functions
resource "aws_cloudwatch_event_target" "step_functions" {
  rule      = aws_cloudwatch_event_rule.s3_contract_upload.name
  target_id = "StepFunctionsTarget"
  arn       = var.state_machine_arn
  role_arn  = var.eventbridge_role_arn

  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
      time   = "$.time"
    }

    input_template = <<EOF
{
  "s3": {
    "bucket": <bucket>,
    "key": <key>
  },
  "vendor_metadata": {
    "region": "us-east-1",
    "contract_type": "MSA",
    "upload_time": <time>
  },
  "contract_id": null
}
EOF
  }
}

# Enable EventBridge notifications on S3 bucket
resource "aws_s3_bucket_notification" "contract_upload" {
  bucket      = var.s3_bucket_name
  eventbridge = true
}
