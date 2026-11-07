data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  name       = "${var.project_name}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = slice(data.aws_availability_zones.available.names, 0, 2)

  https_enabled = var.acm_certificate_arn != ""
  public_host   = var.public_hostname != "" ? var.public_hostname : aws_lb.main.dns_name
  public_url    = "${local.https_enabled ? "https" : "http"}://${local.public_host}"

  services_count = var.enable_services ? 1 : 0

  # Names are fixed here because deploys need them even while enable_services is false.
  api_service_name    = "${local.name}-api"
  worker_service_name = "${local.name}-worker"
  api_family          = "${local.name}-api"
  worker_family       = "${local.name}-worker"
  migrate_family      = "${local.name}-migrate"
}
