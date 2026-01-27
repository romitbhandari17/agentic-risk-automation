variable "region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "dev"
}

variable "project" {
  type    = string
  default = "agentic-risk-automation"
}

variable "lambda_zip_path" {
  type    = string
  default = ""
}
