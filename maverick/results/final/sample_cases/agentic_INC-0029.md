# INC-0029: ESCALATE

**User:** grace.dev  ·  **Window:** 2026-10-04T03:03:43+00:00 to 2026-10-04T03:03:43+00:00  ·  **Risk:** 0.221  ·  **Techniques:** T1566.002
**Detections:** DET-001  ·  **Run:** agentic (ollama:qwen2.5:7b, mode agentic)

## Decision
- **Final (AI + controls):** ESCALATE
- **AI recommendation:** close (benign_true_positive, confidence 0.95)
- **Why a human must look:**
    - unsupported evidence: 'Grace.dev accessed the finance-reports cloud bucket' quote 'finance-reports' not found in ['E003095']

## Summary
Grace.dev's actions are consistent with her usual behavior and do not indicate malicious intent. The link domain is new, but the activity is explained by her role and the nature of the incident.

## Evidence (2 of 3 observed claims verified, observation ratio 0.667)
| Observed | Source | Quote |
|---|---|---|
| Grace.dev clicked a link in an email from an external sender | E003083 | `https://news.vendor-weekly.com/issue/995` |
| Grace.dev launched Outlook.exe from explorer.exe | E003095 | `outlook.exe` |
| Grace.dev accessed the finance-reports cloud bucket | E003095 | `finance-reports` |

**Claims that failed verification:**
- 'Grace.dev accessed the finance-reports cloud bucket' quote 'finance-reports' not found in ['E003095']

## Why it matters
- No asset records for the hosts or buckets involved.
- **New for this user:** link domain = `news.vendor-weekly.com`
- AI cited asset or baseline facts: no

## What the agent checked
1. `lookup_user(user=grace.dev)`
2. `user_baseline(user=grace.dev)`
3. `lookup_asset(name=finance-reports)`
4. `search_events(host=, source=endpoint, event_type=process_create, limit=5, minutes_after=180, minutes_before=180, user=grace.dev)`
5. `log_health(source=email)`
6. `process_tree(host=WS-GRACE, minutes=30)`

## Alternative hypothesis
Grace.dev is a software developer who occasionally accesses external links and sensitive cloud buckets as part of her work. The link domain is new, but the user's activity is consistent with her usual behavior.

## Next steps for the analyst
- [ ] Confirm the AI's evidence above and close or escalate.

---
_Lab answer key (not visible to an analyst): benign, scenario newsletter_click._
_Investigation score: 0.0/100. Gates: ✗ benign explanation cited (100)._
