variable "name_prefix" {
  type = string
}

resource "aws_s3_bucket" "this" {
  bucket = "${var.name_prefix}-artifacts"

  tags = {
    # Use substring() (preferred) instead of the deprecated substr().
    Project     = var.name_prefix
  }
}

# Use the separate resource for bucket versioning instead of the deprecated nested block.
resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.bucket

  versioning_configuration {
    status = "Enabled"
  }
}

# Use the dedicated lifecycle configuration resource instead of the deprecated nested lifecycle_rule.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.bucket

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    # Empty filter applies to the whole bucket. Add prefix/tag filters here when needed.
    filter {
      prefix = ""
    }
  }
}
