"""Exports detection coverage as an ATT&CK Navigator layer (layer format 4.5).

Open https://mitre-attack.github.io/attack-navigator/ -> "Open Existing Layer"
-> upload results/navigator_layer.json. Each technique is coloured by the share of
its malicious events detected at technique level; the cell comment lists the full
breakdown (technique / tactic / general / telemetry only / not observable).
"""

from __future__ import annotations

import json

from .config import path, settings

LEGEND = {">= 80% detected at technique level": "#1a9850", "60-79%": "#91cf60", "30-59%": "#fee08b",
          "1-29%": "#fc8d59", "not detected": "#d73027"}


def export(metrics: dict) -> dict:
    techniques = []
    for t, v in metrics["detection"]["per_technique"].items():
        levels = {k: n for k, n in v["levels"].items() if n}
        total = sum(levels.values())
        share = round(100 * v["levels"]["technique"] / total) if total else 0
        colour = "#1a9850" if share >= 80 else "#91cf60" if share >= 60 else "#fee08b" if share >= 30 \
            else "#fc8d59" if share > 0 else "#d73027"
        techniques.append({
            "techniqueID": t, "score": share, "color": colour, "enabled": True,
            "comment": f"Technique-level detection on {share}% of {total} malicious events. "
                       + ", ".join(f"{k}: {n}" for k, n in levels.items())
                       + f". Recall signature-only {v['recall_signature_only']}, "
                         f"with behavioural {v['recall_with_behavioural']}."})
    layer = {
        "name": "AI Triage Assurance Lab - detection coverage",
        "versions": {"attack": str(settings()["attack"]["attack_version"]), "navigator": "5.1.0", "layer": "4.5"},
        "domain": "enterprise-attack",
        "description": "Share of emulated malicious events detected at technique level. Generated from results/metrics.json.",
        "techniques": techniques,
        "gradient": {"colors": ["#d73027", "#fee08b", "#1a9850"], "minValue": 0, "maxValue": 100},
        "legendItems": [{"label": k, "color": c} for k, c in LEGEND.items()],
        "showTacticRowBackground": True,
    }
    out = path("results_dir") / "navigator_layer.json"
    out.write_text(json.dumps(layer, indent=2), encoding="utf-8")
    return layer
