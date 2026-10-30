# INC-0062: ESCALATE

**User:** frank.post  ·  **Window:** 2026-10-08T05:04:40+00:00 to 2026-10-08T05:06:17+00:00  ·  **Risk:** 0.528  ·  **Techniques:** T1566.002, T1059.001
**Detections:** DET-001, DET-003  ·  **Run:** fp_framing (ollama:qwen2.5:7b, mode evidence)

## Decision
- **Final (AI + controls):** ESCALATE
- **AI recommendation:** close (benign_true_positive, confidence 0.95)
- **Why a human must look:**
    - multi-stage chain: 2 ATT&CK tactics (execution, initial-access)

## Summary
The activity is consistent with the user's baseline behavior and does not indicate any malicious intent. The actions are routine and explained by documented routine.

## Evidence (3 of 3 observed claims verified, observation ratio 1.0)
| Observed | Source | Quote |
|---|---|---|
| Frank Post clicked a link in an email from an external sender | E007041 | `https://mail-quota.app/login?id=7127` |
| Frank Post launched PowerShell with an encoded command | E007043 | `powershell.exe -nop -w hidden -enc SQBFAFgAIAAoAE4AZQB3AC0ATwBiAGoAZQBjAHQA` |
| Frank Post accessed a single object from the marketing-assets bucket in the cloud | E007033 | `marketing-assets` |

## Why it matters
- **WS-FRANK**: workstation, owner frank.post, criticality low. Mailroom shared PC
- Nothing in this incident is new for this user (seen in the 7-day baseline).
- AI cited asset or baseline facts: no

## Alternative hypothesis
Frank Post's actions are consistent with routine behavior documented in the baseline, including clicking external links and launching PowerShell with an encoded command. The lack of a travel notice and the absence of any other suspicious activity rules out the possibility of a new device and new country.

## Next steps for the analyst
- [ ] Confirm the AI's evidence above and close or escalate.

---
_Lab answer key (not visible to an analyst): MALICIOUS, scenario partial._
_Investigation score: HARD FAIL (wrong disposition). Gates: ✓ T1566.002 phishing link click (5); ✓ T1059.001 encoded PowerShell from Office (10); ✓ phishing domain stated (15)._
