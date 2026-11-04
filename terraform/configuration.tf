resource "terraform_data" "configuration" {
  lifecycle {
    precondition {
      condition     = length(local.zones) == 1 && contains(keys(local.zones), "morrowwallet.com")
      error_message = "Only the existing morrowwallet.com zone is supported by the adoption imports."
    }
  }
}
