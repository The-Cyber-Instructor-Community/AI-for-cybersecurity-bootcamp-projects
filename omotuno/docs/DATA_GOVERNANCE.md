# Data Governance & Safety Notes

## Scope
This capstone is intentionally scoped to synthetic SSH-authentication alert data for safe local experimentation.

## Data Handling Principles
- No PHI/PII should be committed to this repository.
- No credentials, tokens, or secrets should be stored in code or logs.
- Real-world logs must be authorized, minimized, and redacted before ingestion.
- Any exported artifacts for demos should avoid sensitive infrastructure identifiers.

## Recommended Redactions for Real Logs
- Usernames (or hash/pseudonymize)
- Source IPs (mask octets when sharing publicly)
- Hostnames, tenant IDs, internal URLs
- Ticket references and internal incident IDs

## Storage & Transmission
- Local-only processing is preferred for capstone demos.
- Avoid uploading raw security logs to third-party tools unless explicitly approved.
- Keep suppression/review artifacts scoped to local dev storage.

## Repository Hygiene
- Run secrets scan before commit:
  `git diff --cached | grep -iE "api_key|secret|password|token="`
- Avoid checking in `.env` files or private key material.
- Keep evidence screenshots free of sensitive data.
