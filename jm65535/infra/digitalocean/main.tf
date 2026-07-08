terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.42"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

resource "digitalocean_ssh_key" "admin" {
  name       = "${var.droplet_name}-admin-key"
  public_key = var.ssh_public_key
}

resource "digitalocean_droplet" "wazuh" {
  name     = var.droplet_name
  size     = var.droplet_size
  image    = "ubuntu-24-04-x64"
  region   = var.region
  ssh_keys = [digitalocean_ssh_key.admin.fingerprint]

  user_data = templatefile("${path.module}/../modules/wazuh-vm/cloud-init.yaml.tftpl", {
    ssh_public_key       = var.ssh_public_key
    wazuh_docker_version = var.wazuh_docker_version
  })
}

resource "digitalocean_firewall" "wazuh" {
  name        = "${var.droplet_name}-firewall"
  droplet_ids = [digitalocean_droplet.wazuh.id]

  # SSH — admin only
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = [var.admin_cidr]
  }

  # Wazuh dashboard — admin only. Never open this to 0.0.0.0/0.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = [var.admin_cidr]
  }

  # Wazuh agent registration/enrollment — restrict to admin IP for now.
  # Add your monitored endpoints' /32 CIDRs here if they differ from admin_cidr.
  inbound_rule {
    protocol         = "tcp"
    port_range       = "1514"
    source_addresses = [var.admin_cidr]
  }
  inbound_rule {
    protocol         = "tcp"
    port_range       = "1515"
    source_addresses = [var.admin_cidr]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

output "wazuh_server_ip" {
  value = digitalocean_droplet.wazuh.ipv4_address
}
