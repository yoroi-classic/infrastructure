module "cloudflare_zones" {
  # cloudflare_zone/v0.1.2
  source   = "git::https://github.com/blinklabs-io/terraform-modules.git?ref=90a75cfeb21d2cddd6c30d8ff50ef45911b56550"
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
