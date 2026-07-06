"""
cli.py

Usage:
    python cli.py --corpus path/to/attack_corpus.yaml
    python cli.py --corpus path/to/attack_corpus.yaml --report out.md

This is the only file a user needs to run. Everything about *what* is
being tested lives in the corpus YAML file, not in this script.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from corpus import load_corpus
from runner import run_campaign


def summarize(results):
    total = len(results)
    bypassed = sum(1 for r in results if r.bypassed)

    by_technique = {}
    for r in results:
        t = r.attempt.technique
        by_technique.setdefault(t, {"total": 0, "bypassed": 0})
        by_technique[t]["total"] += 1
        if r.bypassed:
            by_technique[t]["bypassed"] += 1

    return total, bypassed, by_technique


def print_report(results):
    total, bypassed, by_technique = summarize(results)
    print("\n" + "=" * 60)
    print("RED TEAM REPORT")
    print("=" * 60)
    print(f"Total attempts: {total}")
    print(f"Bypassed: {bypassed}  |  Blocked: {total - bypassed}")
    rate = bypassed / total if total else 0
    print(f"Overall bypass rate: {rate:.0%}\n")

    print(f"{'Technique':<18}{'Total':<8}{'Bypassed':<10}{'Rate'}")
    print("-" * 60)
    for technique, stats in by_technique.items():
        r = stats["bypassed"] / stats["total"]
        print(f"{technique:<18}{stats['total']:<8}{stats['bypassed']:<10}{r:.0%}")

    print("\nExamples that bypassed:")
    shown = 0
    for r in results:
        if r.bypassed and shown < 10:
            print(f"  [{r.attempt.technique}] {r.attempt.variant!r} -> verdict={r.response.verdict}")
            shown += 1
    print("=" * 60 + "\n")


def write_markdown_report(results, path):
    total, bypassed, by_technique = summarize(results)
    rate = bypassed / total if total else 0
    lines = [
        "# Red Team Report\n",
        f"- **Total attempts:** {total}",
        f"- **Bypassed:** {bypassed}",
        f"- **Blocked:** {total - bypassed}",
        f"- **Overall bypass rate:** {rate:.0%}\n",
        "## By technique\n",
        "| Technique | Total | Bypassed | Rate |",
        "|---|---|---|---|",
    ]
    for technique, stats in by_technique.items():
        r = stats["bypassed"] / stats["total"]
        lines.append(f"| {technique} | {stats['total']} | {stats['bypassed']} | {r:.0%} |")

    lines.append("\n## Examples that bypassed\n")
    shown = 0
    for r in results:
        if r.bypassed and shown < 20:
            lines.append(f"- **[{r.attempt.technique}]** seed: `{r.attempt.seed}` -> variant: `{r.attempt.variant}`")
            shown += 1

    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Red-team a security filter via its contract.")
    parser.add_argument("--corpus", required=True, help="Path to attack_corpus.yaml")
    parser.add_argument("--report", default="redteam_report.md", help="Output markdown report path")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    results = run_campaign(corpus)
    print_report(results)
    write_markdown_report(results, args.report)
    print(f"Full report written to {args.report}")


if __name__ == "__main__":
    main()
