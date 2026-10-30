# INC-0088: ESCALATE

**User:** bob.smith  ·  **Window:** 2026-10-11T01:04:35+00:00 to 2026-10-11T01:38:23+00:00  ·  **Risk:** 0.956  ·  **Techniques:** T1566.002, T1078.004, T1069.002, T1530, T1059.001
**Detections:** BEH-001, DET-001, DET-002, DET-003, DET-004, DET-005  ·  **Run:** agentic (ollama:qwen2.5:7b, mode agentic)

## Decision
- **Final (AI + controls):** ESCALATE
- **AI recommendation:** escalate (true_positive, confidence 0.9)

## Summary
The evidence points to a sequence of activities that align with multiple attack techniques, including spearphishing, lateral movement, and data exfiltration. The new device and country sign-in, combined with the bulk read of critical financial data, strongly suggest an attack. While the long-registered sender domains and lack of follow-on activity from the same user after the click are weak signals, the overall pattern is concerning and requires further investigation.

## Evidence (6 of 6 observed claims verified, observation ratio 1.0)
| Observed | Source | Quote |
|---|---|---|
| Bob Smith clicked a link in an email from invoice-portal.co | D000048 | `invoice-portal.co` |
| Bob Smith clicked a link in an email from vendor-weekly.com | D000051 | `vendor-weekly.com` |
| Bob Smith signed in from a new device in a new country (NG) | D000054 | `NG` |
| Bob Smith ran PowerShell with an encoded command | D000049 | `powershell.exe -nop -w hidden -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA` |
| Bob Smith enumerated domain groups with net.exe | D000058 | `net group "Domain Admins" /domain` |
| Bob Smith read 260 objects from the finance-reports bucket | D000067 | `finance-reports` |

## Why it matters
- **WS-BOB**: workstation, owner bob.smith, criticality low. Sales laptop
- **finance-reports** **(crown jewel)**: cloud_bucket, owner Finance, criticality critical. Quarterly financials, board packs; exports require a change ticket
- **New for this user:** sign-in country + device = `NG / DEV-11679`
- AI cited asset or baseline facts: no

## What the agent checked
1. `search_events(source=endpoint, event_type=process_create, limit=10, minutes_after=30, minutes_before=30, user=bob.smith, host=WS-BOB)`
2. `lookup_user(user=bob.smith)`
3. `lookup_asset(name=finance-reports)`
4. `user_baseline(user=bob.smith)`
5. `search_knowledge(query=T1566.002)`
6. `log_health(source=email)`

## Alternative hypothesis
The activity could be explained by a legitimate user conducting routine tasks, but the new device and country sign-in, combined with the bulk read of sensitive data, are suspicious. The long-registered sender domains and lack of follow-on activity from the same user after the click do not rule out malicious intent.

## Next steps for the analyst
- [ ] What specific actions were taken during the bulk read of objects from the finance-reports bucket

---
_Lab answer key (not visible to an analyst): MALICIOUS, scenario with_decoy._
_Investigation score: 78.3/100. Gates: ✓ T1566.002 phishing link click (5); ✓ T1059.001 encoded PowerShell from Office (10); ✓ T1078.004 sign-in from new device / attacker IP (15); ✓ T1069.002 privileged group discovery (20); ✓ T1530 bulk read of cloud data (25); ✗ attacker IP stated (10); ✓ phishing domain stated (15); ✗ legitimate activity kept out of the attack narrative (15)._
_Misattributed (legitimate activity presented as the attack): D000051 (decoy)._
