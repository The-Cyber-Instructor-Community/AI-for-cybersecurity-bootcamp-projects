# Infra

Portable Terraform: the Wazuh deployment logic (Docker, cert generation, hardening,
firewall rules) lives once in `modules/wazuh-vm/cloud-init.yaml.tftpl`. Each cloud
provider gets a thin directory that just provisions a VM + firewall and hands it
that same cloud-init script. Swapping clouds means switching directories, not
rewriting the deployment.

```
infra/
├── modules/wazuh-vm/    shared cloud-init (Docker, Wazuh, hardening) — provider-agnostic
├── hetzner/             cheapest option (~$9.50/mo for cpx22)
├── digitalocean/        more beginner-friendly / widely recognized
└── slack/               Terraform-managed Slack app creation from manifest.yaml
```

## Usage (either provider)

```bash
cd infra/hetzner   # or infra/digitalocean

cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: ssh_public_key, admin_cidr (your IP, run `curl ifconfig.me`)

terraform init
terraform plan
terraform apply
```

API token via `TF_VAR_hcloud_token` (or `TF_VAR_do_token`) env var, not a file.
Resolved from 1Password — the root `.env` already has
`TF_VAR_hcloud_token=op://ai-soc-copilot/hetzner/api_token` — so run `plan`/
`apply` through `op run`, pointing at the root `.env` since these commands run
one directory deeper:

```bash
op run --env-file=../../.env -- terraform plan
op run --env-file=../../.env -- terraform apply
```

`terraform apply` requires your cloud provider account/API token — that step has
to be run by you, not something Claude can do on your behalf.

## Security defaults

- SSH (22), Wazuh dashboard (443), and agent ports (1514/1515) are restricted to
  `admin_cidr` only — nothing is open to `0.0.0.0/0`.
- Password SSH auth and root login are disabled at the OS level (cloud-init).
- `ufw` runs locally as a second layer behind the cloud firewall.
- Unattended security updates and fail2ban are enabled by default.

If your monitored endpoint (Mac, or the stretch-goal Linux VM) has a different
public IP than the machine you administer from, add its `/32` CIDR to the
`source_ips` / `source_addresses` lists in `main.tf` for ports 1514/1515.

## Adding a third provider

Copy `hetzner/` as a starting point, swap the Terraform provider block and the
VM/firewall resource types for your target cloud's equivalents, and point
`user_data` at the same `modules/wazuh-vm/cloud-init.yaml.tftpl` file. Nothing
about the Wazuh deployment itself needs to change.
