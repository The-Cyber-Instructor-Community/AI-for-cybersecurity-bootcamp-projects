terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_ssh_key" "admin" {
  name       = "${var.server_name}-admin-key"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "wazuh" {
  name = "${var.server_name}-firewall"

  # SSH — admin only
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = [var.admin_cidr]
  }

  # Wazuh dashboard — admin only. Never open this to 0.0.0.0/0.
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = [var.admin_cidr]
  }

  # Wazuh agent registration/enrollment — restrict to admin IP for now.
  # If your monitored endpoint(s) have a different public IP than your admin
  # machine, add their /32 CIDRs to this list too.
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "1514"
    source_ips = [var.admin_cidr]
  }
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "1515"
    source_ips = [var.admin_cidr]
  }
}

resource "hcloud_server" "wazuh" {
  name        = var.server_name
  server_type = var.server_type
  image       = "ubuntu-24.04"
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.wazuh.id]

  user_data = templatefile("${path.module}/../modules/wazuh-vm/cloud-init.yaml.tftpl", {
    ssh_public_key       = var.ssh_public_key
    wazuh_docker_version = var.wazuh_docker_version
  })
}

output "wazuh_server_ip" {
  value = hcloud_server.wazuh.ipv4_address
}
