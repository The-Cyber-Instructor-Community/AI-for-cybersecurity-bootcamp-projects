# INC-0062: ESCALATE

**User:** frank.post  ·  **Window:** 2026-10-08T05:04:40+00:00 to 2026-10-08T05:06:17+00:00  ·  **Risk:** 0.528  ·  **Techniques:** T1566.002, T1059.001
**Detections:** DET-001, DET-003  ·  **Run:** main_critic (ollama:qwen2.5:7b, mode evidence)

## Decision
- **Final (AI + controls):** ESCALATE
- **AI recommendation:** escalate (true_positive, confidence 0.9)

## Summary
The evidence suggests that Frank Post may have been targeted by a phishing attempt, leading to the execution of a potentially malicious PowerShell script. The access to a cloud bucket from a new IP address adds to the suspicion, warranting further investigation.

## Evidence (3 of 3 observed claims verified, observation ratio 1.0)
| Observed | Source | Quote |
|---|---|---|
| Frank Post clicked a link in an email from an external sender (mail-quota.app) | E007041 | `mail-quota.app` |
| Frank Post launched PowerShell with an encoded command shortly after clicking the external link | E007043 | `powershell.exe -nop -w hidden -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA` |
| Frank Post accessed a cloud bucket (marketing-assets) from a new IP (203.0.113.37) | E007033 | `marketing-assets` |

## Why it matters
- **WS-FRANK**: workstation, owner frank.post, criticality low. Mailroom shared PC
- Nothing in this incident is new for this user (seen in the 7-day baseline).
- AI cited asset or baseline facts: no

## Alternative hypothesis
Frank Post may have been tricked into clicking a malicious link and executing a PowerShell script, possibly for a new task or a new account. However, the new IP accessing a cloud bucket could indicate a new device or a new account, which would need further investigation.

## Next steps for the analyst
- [ ] Whether the PowerShell command is benign or malicious

---
_Lab answer key (not visible to an analyst): MALICIOUS, scenario partial._
_Investigation score: 100.0/100. Gates: ✓ T1566.002 phishing link click (5); ✓ T1059.001 encoded PowerShell from Office (10); ✓ phishing domain stated (15)._
_Misattributed (legitimate activity presented as the attack): E007033._
