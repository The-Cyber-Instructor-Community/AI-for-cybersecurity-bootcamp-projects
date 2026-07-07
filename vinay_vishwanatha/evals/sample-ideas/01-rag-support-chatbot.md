# Sample 1 — RAG Support Chatbot (short / PM-style)

> A customer-facing support chatbot for our SaaS product. It answers questions by
> retrieving from our public help-center articles **and** internal troubleshooting
> runbooks, and it can look up the logged-in user's account status and open
> tickets. Users chat with it on our website after logging in.

## Why this brief is in the set
Exercises the **retrieval** surface the refund agent doesn't: indirect injection
via retrieved documents, cross-user data disclosure, and vector/embedding
weaknesses. Mostly L1 + L3, MAESTRO Data Operations.

## Should-catch (grader spot-check)
- [ ] Indirect prompt injection via internal runbook content (A / LLM01)
- [ ] Cross-user disclosure — one user's account/tickets surfacing to another (I / authz)
- [ ] RAG / vector-store weakness — untrusted content in the index (LLM08)
- [ ] Mixing public + internal sources in one context without trust separation (L1)
- [ ] Q2 should FAIL if retrieved docs aren't treated as data
