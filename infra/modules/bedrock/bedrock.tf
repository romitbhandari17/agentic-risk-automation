variable "name_prefix" { type = string }

# Placeholder resource for Bedrock integration; implement actual resources when ready.
resource "null_resource" "bedrock_placeholder" {
  triggers = {
    name = var.name_prefix
  }
}
