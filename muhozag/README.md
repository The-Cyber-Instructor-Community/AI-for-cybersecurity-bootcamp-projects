# security-agents

Two standalone tools, connected only by a shared contract, not by importing each other's code. Either can be used independently, against any target that speaks the contract.

## What this project demonstrates

An AI-based security defense (Guardian Service) that catches disguised prompt-injection attacks a traditional regex-based filter misses, proven using an automated attack tool (Red Team CLI) built to test either one.

## Components

- **`contracts/`**: the shared request/response format both tools agree on. See `contracts/README.md`.
- **`redteam_cli/`**: attacks a target (any HTTP service, or a local Python function) using a configurable corpus of disguised attack variants.
- **`guardian_service/`**: a standalone FastAPI microservice that judges whether text is a manipulation attempt, using Claude reasoning instead of regex. Published as a container image via CI/CD.

## Results so far

| Defense | Bypass rate |
|---|---|
| Guardian Service (Claude-based reasoning) | 17% |

The Guardian Service caught every homoglyph and leetspeak disguise attempt outright, and only missed one genuinely ambiguous paraphrase, a case that could plausibly be read as harmless out of context. This is the core result the project set out to demonstrate: reasoning-based defense catches disguised attacks that literal phrase-matching filters are designed to miss.

## How to try this

```bash
# Terminal 1: start the guardian service
cd guardian_service
uv run uvicorn main:app --reload --port 8000

# Terminal 2: attack it
uv run python3 redteam_cli/cli.py --corpus redteam_cli/attack_corpus.yaml
```

Add a real `ANTHROPIC_API_KEY` to a `.env` file at the project root for genuine Claude-based judgments; without one, the service runs a minimal fallback so it still starts.

## CI/CD

- **CI** (`.github/workflows/ci.yml`): runs on every push to `main`. Lints with `ruff`, runs the test suite with `pytest`, and scans the codebase for security issues with `bandit`.
- **CD** (`.github/workflows/cd.yml`): runs only when a version tag (e.g. `v1.0.0`) is pushed. Builds the Guardian Service into a container image, scans it for known vulnerabilities with Trivy, and publishes it to GitHub Container Registry.

Published images are available at `ghcr.io/muhozag/security-agents/guardian-service`.

## Miscelaneous

- Note: this is a personal research prototype exploring AI-based defenses against prompt injection. Not a production security product, and not affiliated with or endorsed by any application it has been tested against.