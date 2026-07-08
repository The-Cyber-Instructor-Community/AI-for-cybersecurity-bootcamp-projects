variable "do_token" {
  description = "DigitalOcean API token. Pass via TF_VAR_do_token env var — never commit this."
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

variable "droplet_name" {
  description = "Name for the Wazuh droplet."
  type        = string
  default     = "wazuh-manager"
}

variable "droplet_size" {
  description = "DigitalOcean droplet size. s-2vcpu-4gb is the smallest that comfortably runs Wazuh single-node."
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "region" {
  description = "DigitalOcean region."
  type        = string
  default     = "nyc3"
}

variable "wazuh_docker_version" {
  description = "Git tag of wazuh/wazuh-docker to deploy. Check https://github.com/wazuh/wazuh-docker/releases for the current stable tag before applying."
  type        = string
  default     = "v4.14.5"
}
