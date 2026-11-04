output "cloudflare_zone_ids" {
  description = "Cloudflare zone IDs indexed by domain."
  value       = { for name, zone in module.cloudflare_zones : name => zone.zone_id }

}
