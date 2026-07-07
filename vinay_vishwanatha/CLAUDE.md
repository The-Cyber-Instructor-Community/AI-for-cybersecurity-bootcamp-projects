# AI Threat Modeling Agent — Project Guide

Capstone project. Goal: given a product idea or architecture for an AI/agentic
system, produce (1) secure-design recommendations and (2) a pre-deployment
validation review. Built as Claude Code skills, run from VS Code. Time budget is
tight — favor a working end-to-end pipeline over breadth.

## What this is (and isn't)

It is a **threat-modeling agent for AI systems specifically** — LLM apps, RAG
apps, tool-using assistants, and multi-agent workflows. It is inspired by CSA's
MAESTRO but differentiates by being grounded (every finding traces to a named
catalog), producing cross-cutting recommendations in a 4-layer defense model, and
ending in a verifiable checklist rather than a free-form LLM dump.

## The four inputs — each has exactly one job

Do not let these overlap. If confused about which to use, re-read this table.

| Input | Its one job |
|-------|-------------|
| Context intake gate | Capture the system, assets, entry points before any analysis |
| MAESTRO 7 layers | Coverage map — confirm no part of the AI stack was missed |
| ASTRIDE categories | The threat categories applied per asset (the "what kind") |
| Defense Model (4 layers) | The recommendations bucket — structural controls + tools |
| Shift-left 5 questions | The go/no-go gate and the report's backbone |

Key point: MAESTRO = *where to look*; ASTRIDE = *what kind of threat*; Defense
Model = *what to do*. They compose as a grid, they are not redundant.

## Locked decisions

1. **Threat taxonomy: standard ASTRIDE** = the 6 STRIDE categories (Spoofing,
   Tampering, Repudiation, Information disclosure, Denial of service, Elevation of
   privilege) + **A** = AI Agent-Specific Attacks (prompt injection, unsafe tool
   invocation, reasoning subversion, context/memory poisoning).
2. **No course-specific control catalog (ASI).** Ground recommendations in the
   OWASP Top 10 for LLM Apps instead.
3. **Severity uses ASR (Attack Success Rate).** severity = impact × likelihood,
   where likelihood is anchored to measured or estimated ASR for that attack
   class. ASR baseline is also the pre-deploy gate (shift-left Q5).

## Pipeline (implemented by the orchestrator skill)

```
0. Intake      capture context + readiness gate     (references/intake-schema.md)
1. Decompose   assets + entry points + Mermaid DFD
2. Enumerate   assets × ASTRIDE, MAESTRO as coverage — severity via ASR
3. Recommend   route each finding → 1 of 4 defense layers → controls + tools
4. Report      structured around the shift-left 5 questions + checklist
```

## The 4 defense layers (each becomes one layer skill)

| Layer | Counters | Defense goal |
|-------|----------|--------------|
| L1 Prompt | injection, jailbreak, system-prompt extraction | structurally separate trusted instructions from untrusted data |
| L2 Model | adversarial examples, evasion, data extraction | control what enters (load-time) and exits (output); eval in CI/CD |
| L3 System | agent chains, memory/RAG poisoning, MCP attacks | least agency, human approval for irreversible actions, provenance |
| L4 Supply Chain | poisoned/malicious models | non-executable model formats, pinned versions, verified provenance |

Each layer skill uses the same section template:
`Threats addressed → Defense goal → Structural controls → Tooling → Validation checks`.

## Shift-left 5 questions (report spine + self-eval rubric)

1. What are the assets? (training data, weights, system prompt, retrieved data, tool creds)
2. Where does untrusted content enter, and is every entry point tagged as data, not instructions?
3. Which ASTRIDE categories apply per asset, and what's the worst case?
4. Does every tool call map to least privilege — scoped, short-lived, caller-bound?
5. Is there an ASR baseline this system must pass before and continuously after launch?

## Repo layout

```
.claude/skills/
├── ai-threat-orchestrator/     # the pipeline spine (built)
│   ├── SKILL.md
│   ├── references/intake-schema.md
│   └── scripts/render_report.py    # Phase 3
├── prompt-layer-defense/       # L1  (to build)
├── model-layer-defense/        # L2  (to build)
├── system-layer-defense/       # L3  (to build)
└── supply-chain-layer-defense/ # L4  (to build)
evals/
├── sample-ideas/               # 3 fake AI product briefs
└── rubric.md                   # scored on the 5 questions above
```

## Build phases (~10h)

- **P1 Scaffold + orchestrator** — repo, this file, the orchestrator skill in place; run it once on a sample idea to see Stages 0–2 work.
- **P2 Four layer skills** — build L1–L4 from the defense-model reference, same template. Richest is L3 (agents/RAG/MCP/Rule of Two).
- **P3 Validation + renderer** — the pass/fail/gap checklist and `render_report.py` (findings JSON → Markdown report + Mermaid).
- **P4 Eval + polish** — run 3 sample briefs, score each against the 5 questions, tune skill descriptions so they trigger, write README + demo script.

## Grounding sources (cite these in outputs)

OWASP Top 10 for LLM Apps · CSA MAESTRO (7-layer) · ASTRIDE (STRIDE + A) ·
Meta "Agents Rule of Two" · CaMeL (structural separation) · MITRE ATLAS.

## Conventions

- Skill `description` fields should be "pushy" so they trigger reliably.
- Keep each SKILL.md body focused; put long catalogs in `references/`.
- Deterministic work (scoring, report rendering) goes in Python scripts, not prose.
