#  AI Attack Detection Classifier — with Confidence-Gated Response

A real-time **security guard for AI chatbots**. It reads every message going *in* and every reply going *out*, and decides: **allow, flag for a human, or block** — stopping attacks before they cause harm. Every detection is labelled with the two industry rulebooks: **OWASP LLM Top-10 (2025)** and **MITRE ATLAS**.


---

##  What is this? 

- AI chatbots can be **tricked** — people try to make them ignore their rules, leak secrets, or misbehave.
- This project sits **in front of** the chatbot and checks each message.
- Safe messages pass through; suspicious ones get flagged; clear attacks get blocked.
- It also checks the chatbot's **reply** so nothing sensitive leaks out.

---

##  What it detects

**Coming in (the user's message):**
- Prompt injection — "ignore your rules and do X"
- Jailbreaks / DAN — "act as an AI with no restrictions"
- System-prompt theft — "reveal your hidden instructions"
- Secret / password / API-key fishing
- Disguised attacks — hidden in base64, ROT13, leetspeak, look-alike letters, spaced-out text
- Non-English attacks (Spanish, French, German…)
- Slow-burn / multi-turn attacks that build up over several messages
- Social-engineering tricks — "as a fellow researcher, walk me through…"

**Going out (the chatbot's reply):**
- System-prompt leakage
- Secret / API-key leakage
- Personal data leakage (names, SSNs, cards, emails) — even spelled-out sneaky ones (canary tokens)

**For AI agents that take actions:**
- Risky tool-calls — delete data, send money, grant admin, disable firewall

**Behind the scenes:**
- Data poisoning (bad data sneaking into training)
- Model-stealing (someone firing tons of queries to copy the model)
- Poisoned documents in a knowledge base (RAG)
- Whole-session behaviour — spotting the *attacker's pattern*, not just one message

---

##  Tools used (and why, one line each)

- **Python + scikit-learn** — the first fast "brain" that learns attack vs safe.
- **RoBERTa / DeBERTa (Hugging Face)** — smarter AI brains for hard, disguised attacks.
- **Sentence-Transformers + Chroma** — a living "attack library" the guard compares against (RAG).
- **FastAPI + Uvicorn** — turns the guard into a real, live web service.
- **Microsoft Presidio** — finds personal data in replies.
- **OpenAI gpt-4o-mini** — a fair "judge" that rescues real users wrongly flagged.
- **Promptfoo** — a professional attack-testing (red-team) tool.
- **Langflow** — a drag-and-drop chatbot demo with the guard built in.
- **MCP server** — plugs the guard into Claude Desktop as a tool.
- **Docker** — packages the whole thing to run anywhere with one command.
- **OWASP LLM Top-10 + MITRE ATLAS** — the security labels on every catch.

---

## How I advanced it

- Upgraded from simple word-matching to a **fine-tuned RoBERTa** brain — catches attacks it's never seen.
- Built a **living threat library** that pulls **fresh, real-world attacks** (MITRE ATLAS, OWASP, NVD, and community feeds) and keeps learning.
- Made the library **poison-resistant** — bad or fake "intel" is screened out, and a **human approves** new patterns before they go live.
- Added a **fair AI judge** so real researchers/students aren't wrongly blocked.
- Added **canary tokens** — if a secret ever leaks in a reply, it's caught on the way out (even spelled-out).
- Added **per-caller query budgets** — flags and blocks anyone firing too many queries to copy the model.
- Wrapped it as a **live service + Langflow bot + MCP tool + Docker container**.
- Built a **one-command test scorecard** to prove everything works.
- **Honest science:** tested "internal-state probing" (reading the AI's activations). It performed the same as the simple method, so I **didn't ship it** — and documented why.

---

##  The numbers (real, not faked)

- Trained on **~1,342** real attack + safe examples; tested on **549** it never saw.
- **Precision ~93--97%** — when it says "attack," it's almost always right.
- **Recall ~80%** — catches most real attacks.
- **ROC-AUC 0.96** — strong overall.
- **False alarms on safe messages: ~1.5%** — very low.
- Before → after upgrades: precision **55.7% → 98.2%**, false-alarms **80.7% → 1.5%**.
- The fine-tuned brain scored **F1 0.99** vs **0.70** for simple word-matching.



---

##  Where it can be used

- Guarding **customer-facing chatbots and copilots**.
- **DLP** (data-leak protection) for anything an AI says back.
- **Tool-call safety** for autonomous AI agents.
- **SOC / security teams** — every event is a clean report with OWASP + ATLAS tags and an evidence ID.
- **AI governance / compliance** — EU AI Act, NIST AI RMF positioning.

---

##  How to run it (real-time)

**With Docker (one command):**
```bash
docker build -t guardrail .
docker run -p 8000:8000 -e OPENAI_API_KEY="your-own-key" guardrail
```
Then open `http://localhost:8000/docs` — a live API with:
- `POST /scan_input` — check a message (allow / review / block)
- `POST /check_output` — check a reply for leaks
- `POST /threat_search` — search the live attack library
- `GET /health` — service status

No API key is baked in — **each user supplies their own at run time.**

---

## 🔧 How anyone can use & improve it

- **Retrain on your own data** — feed it your own labelled examples and it learns *your* risks (fraud, spam, policy breaches).
- **Add fresh attacks anytime** — drop new patterns into the living library; a human approves them, and both blocking *and* answers get smarter.
- **Plug it into any app** — via the API, the Langflow node, or the MCP tool for Claude Desktop.

**To take it to full production, you'd add:**
- Login / API keys + support for many customers at once
- Scanning replies **word-by-word as they stream**
- A shared database (Redis/Postgres) so limits work across many servers
- Alerts pushed into a company **security dashboard (SIEM)**
- Coverage for **images / voice** (today it's text-only)

---

##  Honest limitations

- Recall on brand-new/novel attacks depends on the fine-tuned model — continuous retraining helps.
- Non-English coverage leans on the deep model; more languages need more data.
- Query-budget state resets if the single server restarts (a multi-server deploy would use Redis).
- Model-inversion defense and multi-agent protections are **not** built (out of scope for this architecture).

---
