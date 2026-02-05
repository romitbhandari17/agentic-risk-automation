output "bucket" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.this.id
}


output "bucket_arn" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.this.arn
}