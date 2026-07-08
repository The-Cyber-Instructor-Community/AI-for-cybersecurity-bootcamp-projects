# Setup — accounts and manual steps

These steps can't be done by Claude (account creation, payment, device auth all
require you directly). Everything else in this repo is already written — this
is what unlocks running it. Checked off as we go.

**Cloud provider chosen: Hetzner** (`infra/hetzner/`). DigitalOcean instructions
kept below for reference / in case of a future switch — see `infra/README.md`.

## 1. SSH key (if you don't already have one) — done

```bash
ssh-keygen -t ed25519 -C "ai-soc-copilot"
cat ~/.ssh/id_ed25519.pub
```
Keep this handy — it goes into `infra/hetzner/terraform.tfvars`.

## 2. Anthropic API key — done

1. Go to console.anthropic.com → Settings → API Keys → Create Key.
2. Save the value — you'll store it in 1Password in step 5, item `anthropic`, field `api_key`.

## 3. Cloud provider account — done (Hetzner)

1. Signed up at hetzner.com/cloud.
2. Console → Security → API Tokens → Generate (Read & Write). Token copied.

<details>
<summary>DigitalOcean instructions (not used, kept for reference)</summary>

1. Sign up at digitalocean.com.
2. API → Tokens → Generate New Token (Read and Write). Save the token.

</details>

## 4. Slack app (Socket Mode — no public webhook needed) — pending

Built from a manifest (`infra/slack/manifest.yaml`) so the app config is
version-controlled and reproducible rather than hand-clicked — useful if this
repo gets forked. Two ways to apply it — pick one:

**Option A — manual paste (fastest for just yourself):**
1. api.slack.com/apps → **Create New App** → **From an app manifest** → pick
   your workspace → paste the contents of `infra/slack/manifest.yaml` → **Create**.
   This sets scopes, Socket Mode, and interactivity all at once.

**Option B — Terraform (what a fork should use):** see `infra/slack/README.md`
— `terraform apply` in `infra/slack/` creates the app from the same manifest
via Slack's API. Either way, the next two steps (app-level token, install to
workspace) are manual regardless — Slack doesn't expose an API for those.
2. **Basic Information** → **App-Level Tokens** → **Generate Token and Scopes**
   → name it, add scope `connections:write` → Generate. Copy the token (`xapp-...`)
   — save it (`slack` item, field `app_token`). The manifest can't generate this
   one for you; it always requires this manual step.
3. **Install App** (left sidebar) → **Install to Workspace** → Allow. Copy the
   **Bot User OAuth Token** (`xoxb-...`) — save it (`slack` item, field `bot_token`).
4. **Basic Information** → **App Credentials** → copy the **Signing Secret** —
   save it (`slack` item, field `signing_secret`).

## 5. 1Password CLI — pending

1. Install: `brew install --cask 1password-cli` (or see developer.1password.com/docs/cli).
2. `op signin` — authenticates with your own 1Password account. Claude can't do
   this step; it's your device/credential.
3. Create a vault (or reuse an existing one and adjust the `op://` paths in
   `.env` to match):
   ```bash
   op vault create ai-soc-copilot
   ```
4. Create the items — run locally with your real values, never paste real
   secrets into chat with Claude. Field names must match what `.env.example`
   expects (default field type is `password`/concealed, which is correct here):
   ```bash
   op item create --category "API Credential" --title "slack" --vault "ai-soc-copilot" \
     'bot_token=xoxb-your-real-token' \
     'app_token=xapp-your-real-token' \
     'signing_secret=your-real-signing-secret'

   op item create --category "API Credential" --title "anthropic" --vault "ai-soc-copilot" \
     'api_key=sk-ant-your-real-key'
   ```
   Skip `wazuh` for now — its fields (`api_url`, `api_user`, `api_password`,
   `indexer_url`, `indexer_user`, `indexer_password`) don't have real values
   until the VM is deployed in Phase 1. Add that item the same way once it is.

   Note: command-line arguments are briefly visible to other processes on your
   machine (`ps`) while the command runs — low risk on a personal machine, but
   if you want to avoid it, prefix the command with a space (most shells with
   `HISTCONTROL=ignorespace` — the macOS zsh default — skip logging
   space-prefixed commands to history).
5. Test it — run from inside `ai-soc-copilot/`:
   ```bash
   op run --env-file=.env -- env | grep -E "ANTHROPIC|SLACK"
   ```
   Should print your real values, proving the references resolve.

## 6. (Later, stretch goal) RunPod or Colab account for fine-tuning — not yet needed

Only needed when we get to the Foundation-Sec-8B comparison. RunPod (runpod.io)
for a rented A100 (~$0.59/hr, this dataset size should cost a few dollars total),
or try Unsloth's free Colab notebook first — the dataset is small enough it may
just work on the free tier. No need to set this up now.

---

Once steps 1–5 are done, tell me your cloud pick and I'll walk through
`terraform apply` for that provider next (Phase 1).
