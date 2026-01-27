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

variable "lambda_zip_path" {
  type    = string
  default = ""
}

module "infra_root" {
  source = "../.."

  region = var.region
  env    = var.env
  project = var.project
  lambda_zip_path = var.lambda_zip_path
}
