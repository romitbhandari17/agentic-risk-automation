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

variable "ingestion_zip_path" {
  type    = string
  default = ""
  description = "Path to the ingestion Lambda deployment package"
}

variable "risk_analysis_zip_path" {
  type    = string
  default = ""
  description = "Path to the risk analysis Lambda deployment package"
}

variable "sf_trigger_zip_path" {
  type    = string
  default = ""
}

