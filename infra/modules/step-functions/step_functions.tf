variable "name_prefix" { type = string }
variable "state_machine_role_arn" { type = string }
variable "definition" { type = string }

resource "aws_sfn_state_machine" "this" {
  name     = "${var.name_prefix}-contract-review"
  role_arn = var.state_machine_role_arn
  definition = var.definition
}
