import {
  to = module.cloudflare_zones["morrowwallet.com"].cloudflare_zone.this
  id = local.zone_id
}

import {
  for_each = local.zone_setting_ids
  to       = module.cloudflare_zones["morrowwallet.com"].cloudflare_zone_setting.this[each.value]
  id       = "${local.zone_id}/${each.value}"
}

import {
  to = module.cloudflare_zones["morrowwallet.com"].cloudflare_zone_setting.security_header
  id = "${local.zone_id}/security_header"
}

import {
  for_each = local.existing_dns_record_ids.a
  to       = module.cloudflare_zones["morrowwallet.com"].cloudflare_dns_record.a[each.key]
  id       = "${local.zone_id}/${each.value}"
}

import {
  for_each = local.existing_dns_record_ids.cname
  to       = module.cloudflare_zones["morrowwallet.com"].cloudflare_dns_record.cname[each.key]
  id       = "${local.zone_id}/${each.value}"
}

import {
  for_each = local.existing_dns_record_ids.mx
  to       = module.cloudflare_zones["morrowwallet.com"].cloudflare_dns_record.mx[each.key]
  id       = "${local.zone_id}/${each.value}"
}

import {
  for_each = local.existing_dns_record_ids.txt
  to       = module.cloudflare_zones["morrowwallet.com"].cloudflare_dns_record.txt[each.key]
  id       = "${local.zone_id}/${each.value}"
}
