# Slack app — Terraform-managed creation

`manifest.yaml` is the single source of truth for the app's config (scopes,
Socket Mode, interactivity). It can be used two ways:

**A — Manual (fastest for a one-off setup):** paste `manifest.yaml` into
api.slack.com/apps → Create New App → From an app manifest.

**B — Terraform (what makes this reproducible/forkable):** `main.tf` reads
the same `manifest.yaml` and creates the app via Slack's `apps.manifest.create`
API, so a contributor forking this repo gets the app created with one
`terraform apply` instead of clicking through Slack's UI.

## What Terraform can and can't automate

Can: create the app itself with the right scopes, Socket Mode, and
interactivity settings enabled — all from `manifest.yaml`.

Can't (Slack requires these as manual, one-time clicks — no public API for
either): generating the app-level token (`xapp-...`, needs the
"Generate Token and Scopes" button) and installing the app to a workspace to
get the bot token (`xoxb-...`, needs the OAuth "Install to Workspace" consent
click). Budget for those two clicks either way — this automates the
configuration, not the token issuance.

## Usage

1. Get an app configuration token + refresh token (one-time, per Slack
   account+workspace, not per app): api.slack.com/apps → scroll to
   **Your App Configuration Tokens** → **Generate Token**. This pair lets
   Terraform manage *any* app in that workspace, not just this one.
2. Export them:
   ```bash
   export SLACK_APP_CONFIGURATION_TOKEN="..."
   export SLACK_REFRESH_TOKEN="..."
   ```
   (Or store both in your 1Password vault alongside the other secrets and
   `op run` them in — same pattern as everywhere else in this repo.)
3. ```bash
   cd infra/slack
   terraform init
   terraform apply
   ```
4. Then do the two manual steps above (app-level token, install to workspace)
   to get `xapp-...` and `xoxb-...` — see `docs/SETUP.md` step 4.

Config tokens expire ~12 hours after issue; the refresh token lets Terraform
(and the underlying Slack API) rotate it automatically on subsequent runs.
