locals {
  config = yamldecode(file("${path.module}/../config.yaml"))
  zones  = { for zone in local.config.cloudflare.zones : zone.name => zone }

  zone_id = local.zones["morrowwallet.com"].zone_id
  existing_dns_record_ids = {
    a     = { for record in local.zones["morrowwallet.com"].a_records : record.name => record.id if try(record.id, "") != "" }
    cname = { for record in local.zones["morrowwallet.com"].cname_records : record.name => record.id if try(record.id, "") != "" }
    mx    = { for record in local.zones["morrowwallet.com"].mx_records : record.value => record.id if try(record.id, "") != "" }
    txt   = { for record in local.zones["morrowwallet.com"].txt_records : record.name => record.id if try(record.id, "") != "" }
  }

  # Match the settings managed by the pinned zone module for initial adoption.
  zone_setting_ids = toset(concat([
    "always_use_https",
    "automatic_https_rewrites",
    "brotli",
    "browser_cache_ttl",
    "cache_level",
    "early_hints",
    "http3",
    "min_tls_version",
    "opportunistic_encryption",
    "rocket_loader",
    "ssl",
    "tls_1_3",
    "websockets",
  ], local.zones["morrowwallet.com"].plan == "free" ? [] : ["h2_prioritization", "mirage", "webp"]))
}
