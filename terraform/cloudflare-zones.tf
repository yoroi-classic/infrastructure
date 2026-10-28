module "cloudflare_zones" {
  source   = "git::https://github.com/blinklabs-io/terraform-modules.git//cloudflare_zone?ref=eea3064e2a77cb0797843dce29d7cbeaa309ba70"
  for_each = local.zones

  depends_on = [terraform_data.configuration]

  account_id = local.config.cloudflare.account_id
  zone_name  = each.key
  plan       = each.value.plan

  a_records     = each.value.a_records
  cname_records = each.value.cname_records
  mx_records    = each.value.mx_records
  txt_records   = each.value.txt_records
}
