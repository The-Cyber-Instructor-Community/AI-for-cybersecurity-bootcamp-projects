# Deploying Wazuh (Phase 1)

Assumes Phase 0 (`docs/SETUP.md`) is done — cloud account, SSH key, and
1Password vault already exist.

## 1. Provision the VM

```bash
cd infra/hetzner   # or infra/digitalocean

MY_IP=$(curl -s ifconfig.me)
cat > terraform.tfvars <<EOF
ssh_public_key = "$(cat ~/.ssh/id_ed25519.pub)"
admin_cidr     = "${MY_IP}/32"
EOF

terraform init
op run --env-file=../../.env -- terraform plan     # review: 1 SSH key, 1 firewall, 1 server
op run --env-file=../../.env -- terraform apply
terraform output wazuh_server_ip
```

Wait ~5 minutes after `apply` completes — cloud-init installs Docker,
generates Wazuh's certs, and starts the stack in the background.

## 2. Harden it — rotate default credentials, remove unused demo accounts

Wazuh ships with known, publicly-documented default credentials
(`admin`/`SecretPassword`, `kibanaserver`/`kibanaserver`, plus four unused
demo accounts). Rotate them immediately — `scripts/harden-wazuh.sh`
automates the process documented in Wazuh's own docs
(changing-default-password.html) plus removing the unused accounts:

```bash
ssh deploy@<wazuh_server_ip>
sudo curl -o harden-wazuh.sh https://raw.githubusercontent.com/<your-fork>/ai-soc-copilot/main/scripts/harden-wazuh.sh
# or scp it from your machine instead of curl, if the repo isn't pushed yet:
#   scp scripts/harden-wazuh.sh deploy@<ip>:~/

chmod +x harden-wazuh.sh
sudo OP_VAULT=ai-soc-copilot ./harden-wazuh.sh
```

Set `OP_VAULT` to your 1Password vault name and the script pushes the new
credentials straight into a `wazuh` item — nothing gets printed to the
terminal. Omit `OP_VAULT` and it prints the generated passwords once instead
(save them somewhere before closing the terminal).

If you already rotated credentials manually before this script existed, you
don't need to re-run it — it's here for the next environment, not to redo
work already done.

## 3. Confirm

Visit `https://<wazuh_server_ip>` — self-signed cert warning is expected,
proceed past it — and log in with the `admin` credentials from step 2.

## 4. Add remaining secrets to 1Password (skip if the script already did this)

```bash
op item create --category "API Credential" --title "wazuh" --vault "ai-soc-copilot" \
  'api_url=https://<wazuh_server_ip>:55000' \
  'api_user=wazuh-wui' \
  'api_password=<from docker-compose.yml API_PASSWORD>' \
  'indexer_url=https://<wazuh_server_ip>:9200' \
  'indexer_user=admin' \
  'indexer_password=<your rotated admin password>'
```

## 5. Enroll your Mac as a Wazuh agent

```bash
WAZUH_MANAGER_IP=<wazuh_server_ip> ./scripts/install-macos-agent.sh
```

Auto-detects Intel vs. Apple Silicon, downloads the matching signed `.pkg`,
writes the enrollment variables, installs, and starts the agent — one
command instead of the multi-step manual version. Needs `sudo` (you'll be
prompted). This can't be run silently/unattended by design — a security
tool installer prompting for `sudo` rather than running invisibly is a
feature, not a gap.

Verify from the manager:
```bash
ssh deploy@<wazuh_server_ip> \
  "docker exec single-node-wazuh.manager-1 /var/ossec/bin/agent_control -l"
```
should list your Mac's hostname as `Active`.

Next (stretch goal): enroll a Linux VM the same way Wazuh's Linux agent
packages work — see the main project plan for that scope.
