variable "hcloud_token" {
  description = "Hetzner Cloud API token. Pass via TF_VAR_hcloud_token env var — never commit this."
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Your SSH public key contents (e.g. contents of ~/.ssh/id_ed25519.pub)."
  type        = string
}

variable "admin_cidr" {
  description = "Your IP address in CIDR form (e.g. 203.0.113.7/32). Only this address can reach SSH/dashboard/agent ports. Find your IP with: curl ifconfig.me"
  type        = string
}

variable "server_name" {
  description = "Name for the Wazuh VM."
  type        = string
  default     = "wazuh-manager"
}

variable "server_type" {
  description = "Hetzner server type. cpx22 (2 vCPU / 4GB) is the smallest that comfortably runs Wazuh single-node."
  type        = string
  default     = "cpx22"
}

variable "location" {
  description = "Hetzner datacenter location."
  type        = string
  default     = "nbg1"
}

variable "wazuh_docker_version" {
  description = "Git tag of wazuh/wazuh-docker to deploy. Check https://github.com/wazuh/wazuh-docker/releases for the current stable tag before applying."
  type        = string
  default     = "v4.14.5"
}
