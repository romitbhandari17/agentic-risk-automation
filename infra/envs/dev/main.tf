// Environment wrapper for dev
// This file makes `infra/envs/dev` a Terraform root that reuses the infra/ module.

variable "region" {
  type    = string
}

variable "env" {
  type    = string
}

variable "project" {
  type    = string
}

variable "ingestion_zip_path" {
  type    = string
  default = ""
}

variable "risk_analysis_zip_path" {
  type    = string
  default = ""
}

variable "ingestion_lambda_arn" {
  type    = string
  default = ""
}

variable "risk_analysis_lambda_arn" {
  type    = string
  default = ""
}

variable "state_machine_arn" {
  type    = string
  default = ""
}

module "infra_root" {
  source = "../.."

  region = var.region
  env    = var.env
  project = var.project
  ingestion_zip_path = var.ingestion_zip_path
  risk_analysis_zip_path = var.risk_analysis_zip_path
  ingestion_lambda_arn = var.ingestion_lambda_arn
  risk_analysis_lambda_arn = var.risk_analysis_lambda_arn
  state_machine_arn = var.state_machine_arn
}
