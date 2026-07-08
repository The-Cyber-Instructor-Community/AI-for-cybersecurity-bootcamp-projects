"""
finetune/generate_dataset.py
─────────────────────────────
Pulls CVEs from ChromaDB and uses Claude Haiku to generate
structured pentest analysis training pairs.

Output: data/finetune_dataset.jsonl  (alpaca format)

Run:
    python3 -m finetune.generate_dataset            # default 500 CVEs
    python3 -m finetune.generate_dataset --count 50 # quick test
"""

import sys
import json
import time
import random
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
from chromadb.utils import embedding_functions
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
import anthropic

import config

console = Console()

DATASET_PATH = config.DATA_DIR / "finetune_dataset.jsonl"

SYSTEM_PROMPT = (
    "You are AutoRedTeam's vulnerability analysis engine — an expert penetration tester "
    "who specializes in CVE analysis and exploitation assessment. Your job is to analyze "
    "CVEs and produce structured, actionable intelligence for security professionals."
)

USER_PROMPT_TEMPLATE = """\
Analyze this CVE for a penetration testing engagement:

{cve_text}

Respond in exactly this format (keep each section concise — 2-4 sentences max):

## Severity Reasoning
[Why the CVSS score is accurate; what specific factors (AV, AC, privileges, impact) drive it]

## Attack Vector
[How an attacker exploits this: network/local/physical, authentication required, complexity, tools needed]

## Exploitation Likelihood
HIGH / MEDIUM / LOW — [reasoning: public PoC availability, complexity, prevalence in the wild]

## Affected Systems
[Specific software, versions, and configurations that are vulnerable]

## Pentest Steps
1. [Step]
2. [Step]
3. [Step]

## Remediation
[Patch version, config change, or compensating control]

## Pentest Priority
CRITICAL / HIGH / MEDIUM / LOW — [one sentence justification]\
"""


def load_cves_from_chroma(count: int) -> list[dict]:
    """Pull CVE documents from ChromaDB."""
    client = chromadb.PersistentClient(path=str(config.DB_DIR))
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBEDDING_MODEL
    )
    collection = client.get_collection(
        name=config.CVE_COLLECTION,
        embedding_function=emb_fn,
    )

    total = collection.count()
    console.print(f"[cyan]ChromaDB has {total} CVEs — sampling {count}[/]")

    result = collection.get(
        limit=min(count * 2, total),
        include=["documents", "metadatas"]
    )

    items = list(zip(result["documents"], result["metadatas"]))
    random.shuffle(items)
    return items[:count]


def call_claude(client: anthropic.Anthropic, cve_text: str) -> str | None:
    """Call Claude Haiku to generate a structured CVE analysis."""
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": USER_PROMPT_TEMPLATE.format(cve_text=cve_text)}],
        )
        return msg.content[0].text.strip()
    except anthropic.RateLimitError:
        console.print("[yellow]Rate limit hit — waiting 30s...[/]")
        time.sleep(30)
        return call_claude(client, cve_text)
    except Exception as e:
        console.print(f"[red]API error: {e}[/]")
        return None


def build_training_example(cve_text: str, analysis: str) -> dict:
    """Format as alpaca-style training example."""
    return {
        "instruction": (
            "You are an expert penetration tester. Analyze the following CVE and provide "
            "a structured security assessment for a pentest engagement."
        ),
        "input": cve_text,
        "output": analysis,
    }


def generate(count: int = 500):
    console.print(Panel.fit(
        "[bold cyan]AutoRedTeam — Fine-tuning Dataset Generator[/]\n"
        f"Generating {count} CVE analysis training pairs via Claude Haiku",
        border_style="cyan"
    ))

    if not config.ANTHROPIC_API_KEY:
        console.print("[red]ANTHROPIC_API_KEY not set in .env — aborting.[/]")
        sys.exit(1)

    # Estimated cost
    avg_input_tokens  = 250
    avg_output_tokens = 400
    cost_estimate = count * (avg_input_tokens * 0.80 + avg_output_tokens * 4.0) / 1_000_000
    console.print(f"[dim]Estimated API cost: ~${cost_estimate:.2f} (Claude Haiku)[/]\n")

    # Load CVEs
    cves = load_cves_from_chroma(count)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    examples = []
    skipped  = 0

    with Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating training examples...", total=len(cves))

        for doc, meta in cves:
            analysis = call_claude(client, doc)
            if analysis:
                examples.append(build_training_example(doc, analysis))
            else:
                skipped += 1
            progress.advance(task)
            time.sleep(0.1)   # light throttle

    # Save
    DATASET_PATH.parent.mkdir(exist_ok=True)
    with open(DATASET_PATH, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    console.print(Panel.fit(
        f"[bold green]✓ Dataset ready![/]\n"
        f"[bold]{len(examples)}[/] training examples saved\n"
        f"[dim]{skipped} skipped due to API errors[/]\n"
        f"Path: [cyan]{DATASET_PATH}[/]",
        border_style="green"
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500,
                        help="Number of CVEs to convert (default: 500)")
    args = parser.parse_args()
    generate(args.count)
