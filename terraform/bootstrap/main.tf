locals {
  config = yamldecode(file("${path.module}/../../config.yaml"))
}

provider "cloudflare" {}

module "state_bucket" {
  # cloudflare_r2/v0.1.0 (module-scoped releases contain the module at the root).
  source = "git::https://github.com/blinklabs-io/terraform-modules.git?ref=74897dce8cee28409702dc86a8e4f187679e160d"

  account_id    = local.config.cloudflare.account_id
  name          = local.config.terraform.backend.bucket
  location      = local.config.terraform.bootstrap.location
  jurisdiction  = local.config.terraform.bootstrap.jurisdiction
  storage_class = local.config.terraform.bootstrap.storage_class
}

# Explicitly keep the r2.dev endpoint disabled. No custom domain is configured.
resource "cloudflare_r2_managed_domain" "state_bucket" {
  account_id   = local.config.cloudflare.account_id
  bucket_name  = module.state_bucket.name
  enabled      = false
  jurisdiction = local.config.terraform.bootstrap.jurisdiction
}

output "state_bucket" {
  value = module.state_bucket.name
}
