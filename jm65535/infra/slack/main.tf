terraform {
  required_providers {
    slackapp = {
      source  = "yumemi-inc/slackapp"
      version = "~> 0.2.4"
    }
  }
}

# app_configuration_token / refresh_token can also come from
# SLACK_APP_CONFIGURATION_TOKEN / SLACK_REFRESH_TOKEN env vars instead of
# being declared here — see README.md in this directory.
provider "slackapp" {}

# Single source of truth: the same manifest.yaml a contributor could also
# paste manually via "Create New App -> From an app manifest". Terraform just
# automates that same call via apps.manifest.create.
resource "slackapp_application" "soc_copilot" {
  manifest = jsonencode(yamldecode(file("${path.module}/manifest.yaml")))
}

output "app_id" {
  value = slackapp_application.soc_copilot.id
}
