# Runbook — Rotating Wazuh credentials

Use this when credentials have been exposed or are still at Wazuh defaults. It
covers two credential items:

1. **Indexer `admin` (`INDEXER_PASSWORD`)** — treat as compromised (previously
   exposed during setup).
2. **Manager API `wazuh-wui` (`API_PASSWORD`)** — never rotated from Wazuh's
   public default `MyS3cr37P450r.*-`.

> **Run every command yourself.** These touch live infra, the SSH key passphrase,
> and 1Password — none of that should flow through an assistant. New passwords
> are only ever printed on the box (where you run the script) or written straight
> to 1Password; they never leave your control.

Box: `WAZUH_HOST` · SSH user: `deploy` · firewall allow-list: your admin IP
(`YOUR_ADMIN_IP/32` — confirm you are on it with `curl -s https://api.ipify.org`).

---

## 0. Prep (on your Mac)

```bash
ssh-add ~/.ssh/id_ed25519          # unlock the passphrase-protected key once
eval "$(op signin)"                # start a 1Password session for step 5
cd ~/Claude/Projects/AI_For_cyber/ai-soc-copilot
```

Copy the two scripts up to the box (repo may not be pushed yet):

```bash
scp scripts/harden-wazuh.sh scripts/rotate-api-password.sh deploy@WAZUH_HOST:~/
```

---

## 1. Rotate the INDEXER credentials  (⚠️ ~2–5 min stack downtime)

`harden-wazuh.sh` does `docker compose down/up`, so the dashboard/indexer are
briefly offline. It is now safe to **re-run** on an already-rotated box (it
matches the current password generically, not the Wazuh default).

```bash
ssh deploy@WAZUH_HOST
sudo ~/harden-wazuh.sh                 # generates + prints new admin/kibanaserver passwords
```

It waits for the indexer to accept the new `admin` password and re-applies the
security config. **Save the two printed passwords** — you'll store them in step 5.

Verify before moving on:

```bash
# from the box — new admin password must return the cluster root document
docker exec single-node-wazuh.indexer-1 \
  curl -sk -u "admin:<NEW_ADMIN_PW>" https://localhost:9200 -o /dev/null -w '%{http_code}\n'   # expect 200
```

---

## 2. Rotate the MANAGER API password (`wazuh-wui`)  (no downtime)

Find the current API password first (still the default unless changed):

```bash
grep -n "API_PASSWORD" /opt/wazuh-docker/single-node/docker-compose.yml
```

Then rotate online:

```bash
sudo API_OLD_PASSWORD='MyS3cr37P450r.*-' ~/rotate-api-password.sh
```

The script authenticates, changes the password via `PUT /security/users/{id}`,
**verifies** the new password authenticates, and prints which file(s) still
contain the old password (the dashboard's stored copy). **Save the printed new
API password.**

---

## 3. Update the dashboard's stored API password

The dashboard authenticates to the manager API as `wazuh-wui`; its stored copy
must match the new password or the dashboard loses its manager connection.
Confirmed on this box, the dashboard's client credential is the `password:` field
in **`config/wazuh_dashboard/wazuh.yml`** (root-owned, edit with `sudo`). Also
update `API_PASSWORD` in `docker-compose.yml` for consistency on future rebuilds
(the running manager keeps the password in its RBAC db, so the API change from
step 2 already persists — this is for the next `docker compose up`). Replace the
old password with the new one in both, then:

```bash
cd /opt/wazuh-docker/single-node
sudo docker compose restart wazuh.dashboard
```

Verify the manager API accepts the new password:

```bash
docker exec single-node-wazuh.manager-1 \
  curl -sk -u "wazuh-wui:<NEW_API_PW>" -X POST \
  "https://localhost:55000/security/user/authenticate?raw=true" | head -c 40; echo   # expect a JWT
```

Exit the box (`exit`).

---

## 4. (Same pass) clean up the leftover FIM test file

While on the box is unrelated — this is on your **Mac**:

```bash
rm ~/Library/LaunchAgents/test2.plist
# wait for the next syscheck scan (<=5 min) and confirm a "file deleted" alert
# (rule 553) fires, then this open item is closed.
```

---

## 5. Store the new secrets in 1Password (on your Mac)

```bash
op item edit "wazuh" --vault "ai-soc-copilot" \
  "indexer_password=<NEW_ADMIN_PW>" \
  "kibanaserver_password=<NEW_KIBANASERVER_PW>" \
  "api_password=<NEW_API_PW>"
```

(`op signin` from step 0 must still be active. The rotation scripts can do this
for you *on the box* only if `op` is installed and signed in there — it isn't, so
do it here.)

---

## 6. Final verification — the pipeline's secret references still resolve

The Python pipeline reads everything through `op://` references in `.env`. Confirm
they resolve to the new values and the endpoints accept them:

```bash
cd ~/Claude/Projects/AI_For_cyber/ai-soc-copilot

# indexer (9200) with the rotated admin password
op run --env-file=.env -- bash -c '
  curl -sk -u "$WAZUH_INDEXER_USER:$WAZUH_INDEXER_PASSWORD" \
    "$WAZUH_INDEXER_URL" -o /dev/null -w "indexer: %{http_code}\n"'

# manager API (55000) with the rotated wazuh-wui password
op run --env-file=.env -- bash -c '
  curl -sk -u "$WAZUH_API_USER:$WAZUH_API_PASSWORD" -X POST \
    "$WAZUH_API_URL/security/user/authenticate?raw=true" -o /dev/null -w "api: %{http_code}\n"'
```

Both should return `200`. Also confirm the Mac agent is still connected in the
dashboard (Agents view) — rotation does not touch agent enrollment keys, so it
should remain `active`.

---

## Verify

Both credential items rotated: indexer + API passwords updated, new values in
1Password, `op run` resolves them, agent still active.
