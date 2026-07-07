# Sample 3 — Multi-Agent Research Workflow (detailed)

A multi-agent system that produces research briefs. An **orchestrator agent**
accepts a topic and delegates to three specialists:
- a **web-research agent** that browses and fetches arbitrary public web pages,
- a **data-analysis agent** that runs Python (code execution) over the fetched data,
- a **writer agent** that compiles the final brief.

Agents communicate over the **A2A protocol**. The finished brief is emailed to
stakeholders automatically. The system runs as a cloud service and uses a
**self-hosted open-weights model** downloaded from a public model hub, loaded from
the hub's default format. There is no human review between "topic submitted" and
"brief emailed."

## Why this brief is in the set
The showcase brief. It exercises the **Agent Ecosystem** MAESTRO layer, inter-agent
trust (A2A), self-hosted **supply chain** (open-weights provenance/format), code
execution, and auto-email exfil — and it supports a genuine **cross-layer attack
path**, which is MAESTRO's whole point and your differentiation from the CSA demo.

## Should-catch (grader spot-check)
- [ ] Indirect injection via fetched web page content (A / LLM01)
- [ ] **Cross-layer path**: web page injects → propagates via A2A → analysis agent
      executes attacker code → writer exfiltrates via auto-email (cascade)
- [ ] Inter-agent spoofing / no trust boundary between agents over A2A (S / LLM06)
- [ ] Code execution on attacker-influenced data (E, A)
- [ ] Supply chain — open-weights model from a hub, executable format on load (LLM03/LLM04)
- [ ] Auto-email with no HITL — data exfiltration channel (I)
- [ ] Rule-of-Two trifecta across the pipeline: untrusted web + code exec + external email → flag
- [ ] Q5 GAP — no ASR baseline for an autonomous, no-human-in-loop pipeline

## Demo note
This is the best brief to run **live**: the cross-layer cascade is the most
memorable output, and the "no human between submit and email" detail makes the
severity obvious to a non-security grader.
