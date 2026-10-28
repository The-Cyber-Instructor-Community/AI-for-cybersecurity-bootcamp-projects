# compare_runs.py: compare detectors on every test set from the score files already saved, for the research log.
# It scores nothing itself (no GPU; about a minute, mostly the 95% ranges).
#   python scripts\compare_runs.py v3 gend v4a v5 v3+gend v5+gend
# Name each model the way its score files are named; "qwen3vl-deepfake-" can be left off (v5 means
# qwen3vl-deepfake-v5). A+B is both models together, as in score_gend.py: each model's video scores turned into
# ranks (0 to 1), then averaged. The ranks are taken within the videos being compared (for example one method's
# fakes plus the real test videos), as in the research log's tables. Any number of models can be joined (v3+gend+v5).
# Reads, for each model (a missing file just leaves that model's cells empty):
#   data\scores_<name>.csv              Celeb-DF v2: held-out people and the official list (score_model.py)
#   data\scores\v4_<name>.csv           Celeb-DF++: held-out people, files as they ship (score_v4.py)
#   data\scores\ffpp_<name>.csv         FaceForensics++ c23 official test split (score_ffpp.py)
#   data\scores\dfdc_faces_<name>.csv   DFDC sample: main person (eval_dfdc.py; GenD: score_gend.py)
# "Caught at 1% / 5%": share of fakes above the cut-off that flags that share of the same test set's real videos
# (a best case: the cut-off is picked on the videos it is tested on). "Reals above 0.5": share of real videos a
# model scores above 0.5, its false alarms taken at face value; not shown for joined models (their scores are ranks).
# Paired differences (DFDC and FaceForensics++) redraw whole groups, a source video and the fakes made from it,
# 2,000 times, with the same draws for every model; "ahead in" is the share of redraws the first model wins.
# Writes data\scores\compare_runs.csv (one row per test, part, model and number) and
# data\scores\compare_runs_paired.csv, and prints the tables.
import json
import sys
from itertools import combinations

if __name__ == "__main__":
    sys.dont_write_bytecode = True      # nothing is written outside data\, not even .pyc files

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import eval_dfdc                        # per_video (who the main person is) and auc_range, exactly as eval_dfdc.py
import facekit

SCORES = facekit.DATA / "scores"
PREFIX = "qwen3vl-deepfake-"
DEFAULT = ["v3", "gend", "v4a", "v5", "v3+gend", "v5+gend"]
RESAMPLES = 2000
FAMILIES = {"FaceSwap": "swaps", "FaceReenact": "reenactment", "TalkingFace": "talking faces"}
CELEBDF, CELEBDFPP, FFPP, DFDC = "Celeb-DF v2", "Celeb-DF++", "FaceForensics++ test", "DFDC sample"


def file_name(part):
    """'v5' -> 'qwen3vl-deepfake-v5'; 'gend', 'untrained' and full names stay as they are."""
    part = part.strip()
    if part.lower() in ("gend", "untrained"):
        return part.lower()
    return part if part.startswith(PREFIX) else PREFIX + part


def shown(name):
    """How a model is labelled in the tables: qwen3vl-deepfake-v5 -> Run 5, gend -> GenD."""
    def one(part):
        if part == "gend":
            return "GenD"
        if part.startswith(PREFIX):
            return "Run " + part[len(PREFIX):].lstrip("v").replace("-", " ")
        return part
    return " + ".join(one(p) for p in name.split("+"))


def ffpp_pairs():
    """{FaceForensics++ source video id: its official pair, e.g. '000_003'}: a real video and its fakes share one."""
    out = {}
    for split in ("train", "val", "test"):
        for pair in json.loads((facekit.DATA / "ffpp_splits" / f"{split}.json").read_text()):
            for vid in pair:
                out[vid] = "_".join(sorted(pair))
    return out


FFPP_PAIR = ffpp_pairs()
DFDC_VIDEOS = pd.read_csv(sorted(SCORES.glob("dfdc_videos_*.csv"))[0])[["video", "label", "group"]]


# One model's video scores per test (column p), or None if its score file is missing.
def celebdf(name):
    path = facekit.DATA / f"scores_{name}.csv"
    if not path.exists():
        return None
    v = pd.read_csv(path).groupby("video", as_index=False).agg(
        p=("p_fake", "mean"), label=("label", "first"), set=("set", "first"), official=("official_test", "first"))
    v["official"] = v["official"].astype(str) == "True"
    return v


def celebdfpp(name):
    path = SCORES / f"v4_{name}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path).groupby(["condition", "category", "method", "video"], as_index=False).agg(
        p=("p_fake", "mean"), label=("label", "first"))


def ffpp(name):
    path = SCORES / f"ffpp_{name}.csv"
    if not path.exists():
        return None
    v = pd.read_csv(path, dtype={"target": str, "source": str}).groupby("video", as_index=False).agg(
        p=("p_fake", "mean"), label=("label", "first"), method=("method", "first"), target=("target", "first"))
    v["group"] = v["target"].map(FFPP_PAIR)
    return v


def dfdc(name):
    path = SCORES / f"dfdc_faces_{name}.csv"
    if not path.exists():
        return None
    v = eval_dfdc.per_video(pd.read_csv(path), DFDC_VIDEOS)
    return v[["video", "label", "group", "p_main"]].rename(columns={"p_main": "p"})


# test: (loader, the columns that identify a video)
TESTS = {CELEBDF: (celebdf, ["video"]),
         CELEBDFPP: (celebdfpp, ["condition", "category", "method", "video"]),
         FFPP: (ffpp, ["video"]),
         DFDC: (dfdc, ["video"])}


def pooled(rows):
    """The scores to compare within `rows`: a model's own scores, or joined models' ranks taken within `rows`."""
    parts = [c for c in rows.columns if c.startswith("part ")]
    if not parts:
        return rows["p"]
    return sum(rows[c].rank(pct=True) for c in parts) / len(parts)


def load(test, name):
    """Video scores of one model for one test, or of joined models (each one's scores in a 'part' column; p ranks
    them all in one pool); None if a score file is missing."""
    loader, keys = TESTS[test]
    tables = [loader(part) for part in name.split("+")]
    if any(t is None for t in tables):
        return None
    if len(tables) == 1:
        return tables[0]
    joined = tables[0].rename(columns={"p": "part 0"})
    for k, t in enumerate(tables[1:], 1):
        joined = joined.merge(t[keys + ["p"]].rename(columns={"p": f"part {k}"}), on=keys)
    joined["p"] = pooled(joined)
    return joined


def compare(fakes, reals):
    """(fake scores, real scores) to compare; joined models' ranks are taken within these videos only."""
    rows = pd.concat([fakes, reals], ignore_index=True)
    s, is_fake = pooled(rows).to_numpy(), rows["label"].to_numpy() == 1
    return s[is_fake], s[~is_fake]


def clean(x):
    x = np.asarray(x, dtype=float)
    return x[~np.isnan(x)]


def auc(fake, real):
    fake, real = clean(fake), clean(real)
    if not len(fake) or not len(real):
        return np.nan
    return roc_auc_score(np.r_[np.ones(len(fake)), np.zeros(len(real))], np.r_[fake, real])


def caught(fake, real, share):
    """Share of fakes above the score that flags `share` of the real videos."""
    fake, real = clean(fake), clean(real)
    return float((fake > np.quantile(real, 1 - share)).mean()) if len(fake) and len(real) else np.nan


def above(scores, cut=0.5):
    scores = clean(scores)
    return float((scores > cut).mean()) if len(scores) else np.nan


def numbers(test, v, single):
    """{(part, number): value} for one model on one test."""
    out = {}
    if test == CELEBDF:
        for part, rows in [("held-out people", v[v["set"] == "test"]), ("official list", v[v["official"]])]:
            out[(part, "AUC")] = auc(*compare(rows[rows["label"] == 1], rows[rows["label"] == 0]))
        if single:
            test_rows = v[v["set"] == "test"]
            out[("held-out people", "reals above 0.5")] = above(test_rows.loc[test_rows["label"] == 0, "p"])
            out[("held-out people", "fakes above 0.5")] = above(test_rows.loc[test_rows["label"] == 1, "p"])
    elif test == CELEBDFPP:
        per_condition = {}
        for condition in ("original", "reenc"):
            rows = v[v["condition"] == condition]
            reals, per = rows[rows["label"] == 0], []
            for (category, method), f in rows[rows["label"] == 1].groupby(["category", "method"]):
                fake, real = compare(f, reals)
                per.append({"family": FAMILIES.get(category, category), "method": method,
                            "AUC": auc(fake, real), "caught@5%": caught(fake, real, 0.05)})
            per = pd.DataFrame(per, columns=["family", "method", "AUC", "caught@5%"])
            per_condition[condition] = per[per["method"] != "Celeb-DF-v2"]     # the 21 new methods
            if condition == "original":
                for r in per.to_dict("records"):
                    out[(r["method"], "AUC")] = r["AUC"]
                    out[(r["method"], "caught@5%")] = r["caught@5%"]
        new = per_condition["original"]
        out[("21 new methods", "AUC")] = new["AUC"].mean()
        out[("21 new methods", "caught@5%")] = new["caught@5%"].mean()
        out[("21 new methods, re-encoded", "AUC")] = per_condition["reenc"]["AUC"].mean()
        for family, f in new.groupby("family"):
            out[(family, "AUC")] = f["AUC"].mean()
        original = v[v["condition"] == "original"]
        original_reals = original[original["label"] == 0]
        matched = v[(v["condition"] == "matched") & (v["label"] == 0)]
        # The matched clips against the cut-off that flags 5% of the real test videos as they ship. The clips are
        # real, so they count as "fake" here only to keep them apart from the reals they are compared with.
        clips, real = compare(matched.assign(label=1), original_reals)
        out[("matched real clips", "flagged at the 5% cut-off")] = float((clean(clips) >= np.quantile(clean(real), 0.95)).mean())
        if single:
            for source in ("Celeb-real", "YouTube-real"):
                out[(source, "reals above 0.5")] = above(original_reals.loc[original_reals["method"] == source, "p"])
            out[("matched real clips", "reals above 0.5")] = above(matched["p"])
    elif test == FFPP:
        reals, fakes = v[v["label"] == 0], v[v["label"] == 1]
        for part, f in [("all five", fakes)] + list(fakes.groupby("method")):
            fake, real = compare(f, reals)
            out[(part, "AUC")] = auc(fake, real)
            out[(part, "caught@1%")] = caught(fake, real, 0.01)
            out[(part, "caught@5%")] = caught(fake, real, 0.05)
        if single:
            out[("real videos", "reals above 0.5")] = above(reals["p"])
    elif test == DFDC:                      # every video is in the one comparison, so p (one pool) is right here
        value, low, high = eval_dfdc.auc_range(v.rename(columns={"p": "p_main"}), "p_main")
        out.update({("main person", "AUC"): value, ("main person", "AUC low"): low, ("main person", "AUC high"): high})
        real, fake = v.loc[v["label"] == 0, "p"], v.loc[v["label"] == 1, "p"]
        for share in (0.01, 0.05, 0.10):
            out[("main person", f"caught@{share:.0%}")] = caught(fake, real, share)
        if single:
            out[("main person", "reals above 0.5")] = above(real)
            out[("main person", "median real")] = float(np.median(clean(real)))
            out[("main person", "median fake")] = float(np.median(clean(fake)))
    return out


def paired(test, tables):
    """Every two models' AUC difference on the same videos, with the same redraws of whole groups for all."""
    present = [name for name, t in tables.items() if t is not None]
    if len(present) < 2:
        return []
    merged = None
    for name in present:
        t = tables[name][["video", "label", "group", "p"]].rename(columns={"p": name})
        merged = t if merged is None else merged.merge(t[["video", name]], on="video")
    merged = merged.dropna().reset_index(drop=True)
    y, s = merged["label"].to_numpy(), merged[present].to_numpy()
    groups = list(merged.groupby("group").indices.values())
    rng, draws = np.random.default_rng(facekit.SEED), []
    for _ in range(RESAMPLES):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        if 0 < y[idx].sum() < len(idx):
            draws.append([roc_auc_score(y[idx], s[idx, m]) for m in range(len(present))])
    draws = np.asarray(draws)
    full = [roc_auc_score(y, s[:, m]) for m in range(len(present))]
    rows = []
    for a, b in combinations(range(len(present)), 2):
        d = draws[:, b] - draws[:, a]
        rows.append({"test": test, "comparison": f"{shown(present[b])} - {shown(present[a])}", "videos": len(merged),
                     "difference": full[b] - full[a], "low": np.percentile(d, 2.5), "high": np.percentile(d, 97.5),
                     "ahead in": float((d > 0).mean())})
    return rows


def show(title, rows, models):
    """Print one table: `rows` are (row label, function from a model's name to its cell); empty columns dropped."""
    table = pd.DataFrame({m: [cell(m) for _, cell in rows] for m in models}, index=[label for label, _ in rows])
    table = table.loc[:, (table != "").any()]
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 30):
        print(f"\n{title}\n" + table.to_string())


def main():
    models = ["+".join(file_name(p) for p in arg.split("+")) for arg in (sys.argv[1:] or DEFAULT)]
    tables = {test: {m: load(test, m) for m in models} for test in TESTS}
    found = {test: [shown(m) for m, t in by_model.items() if t is not None] for test, by_model in tables.items()}
    for test, names in found.items():
        print(f"{test}: {', '.join(names) if names else 'no score files'}")

    rows = []
    for test, by_model in tables.items():
        for m, v in by_model.items():
            if v is not None:
                for (part, number), value in numbers(test, v, "+" not in m).items():
                    rows.append({"test": test, "part": part, "model": shown(m), "number": number, "value": value})
    long = pd.DataFrame(rows)
    lookup = long.set_index(["test", "part", "model", "number"])["value"].to_dict()

    def get(test, part, number, fmt="{:.3f}"):
        def cell(model):
            value = lookup.get((test, part, model, number), np.nan)
            return "" if pd.isna(value) else fmt.format(value)
        return cell

    def dfdc_auc(model):
        value = lookup.get((DFDC, "main person", model, "AUC"), np.nan)
        if pd.isna(value):
            return ""
        return (f"{value:.3f} [{lookup[(DFDC, 'main person', model, 'AUC low')]:.3f}, "
                f"{lookup[(DFDC, 'main person', model, 'AUC high')]:.3f}]")

    def joined_cells(*cells, inside=" / "):
        """Several cells of one model in one: '18% / 27%', or 'AUC (caught)' with inside=None."""
        def cell(model):
            parts = [c(model) for c in cells]
            if not all(parts):
                return ""
            return f"{parts[0]} ({parts[1]})" if inside is None else inside.join(parts)
        return cell

    pct = "{:.0%}"
    names = [shown(m) for m in models]
    dfdc_caught = joined_cells(*[get(DFDC, "main person", f"caught@{s}", pct) for s in ("1%", "5%", "10%")])
    show("AUC (1.0 = every fake scores above every real video, 0.5 = a coin flip)", [
        ("Celeb-DF v2, held-out people", get(CELEBDF, "held-out people", "AUC")),
        ("Celeb-DF v2, official list", get(CELEBDF, "official list", "AUC")),
        ("Celeb-DF++, 21 new methods (mean)", get(CELEBDFPP, "21 new methods", "AUC")),
        ("  swaps (7)", get(CELEBDFPP, "swaps", "AUC")),
        ("  reenactment (7)", get(CELEBDFPP, "reenactment", "AUC")),
        ("  talking faces (7)", get(CELEBDFPP, "talking faces", "AUC")),
        ("  InSwapper (Deep-Live-Cam)", get(CELEBDFPP, "InSwapper", "AUC")),
        ("  LivePortrait", get(CELEBDFPP, "LivePortrait", "AUC")),
        ("  21 new, after the shared encode", get(CELEBDFPP, "21 new methods, re-encoded", "AUC")),
        ("  caught at 5% (mean of 21)", get(CELEBDFPP, "21 new methods", "caught@5%", pct)),
        ("FaceForensics++ test, all five", get(FFPP, "all five", "AUC")),
        ("  caught at 1% / 5%", joined_cells(get(FFPP, "all five", "caught@1%", pct),
                                             get(FFPP, "all five", "caught@5%", pct))),
        ("DFDC sample, main person [95% CI]", dfdc_auc),
        ("  caught at 1% / 5% / 10%", dfdc_caught),
    ], names)

    show("Real videos scored above 0.5 (false alarms at face value; single models only)", [
        ("Celeb-DF v2 held-out reals", get(CELEBDF, "held-out people", "reals above 0.5", pct)),
        ("Celeb-DF++ test: Celeb-real", get(CELEBDFPP, "Celeb-real", "reals above 0.5", pct)),
        ("Celeb-DF++ test: YouTube-real", get(CELEBDFPP, "YouTube-real", "reals above 0.5", pct)),
        ("Celeb-DF++ matched face-only real clips", get(CELEBDFPP, "matched real clips", "reals above 0.5", pct)),
        ("  ...flagged at the 5% cut-off", get(CELEBDFPP, "matched real clips", "flagged at the 5% cut-off", "{:.1%}")),
        ("FaceForensics++ test reals", get(FFPP, "real videos", "reals above 0.5", pct)),
        ("DFDC reals", get(DFDC, "main person", "reals above 0.5", pct)),
        ("DFDC median score: real", get(DFDC, "main person", "median real", "{:.4f}")),
        ("DFDC median score: fake", get(DFDC, "main person", "median fake", "{:.4f}")),
        ("Celeb-DF v2 held-out fakes above 0.5", get(CELEBDF, "held-out people", "fakes above 0.5", pct)),
    ], names)

    ffpp_methods = ["Deepfakes", "Face2Face", "FaceSwap", "NeuralTextures", "FaceShifter"]
    show("FaceForensics++ test by method: AUC (caught at 5%)",
         [(method, joined_cells(get(FFPP, method, "AUC"), get(FFPP, method, "caught@5%", pct), inside=None))
          for method in ffpp_methods], names)

    pp = long[(long["test"] == CELEBDFPP) & (long["number"] == "AUC")] if len(long) else long
    methods = [p for p in dict.fromkeys(pp["part"]) if p not in
               ("21 new methods", "21 new methods, re-encoded", "swaps", "reenactment", "talking faces")] if len(pp) else []
    show("Celeb-DF++ by method: AUC (files as they ship)",
         [(method, get(CELEBDFPP, method, "AUC")) for method in methods], names)

    pairs = pd.DataFrame(paired(DFDC, tables[DFDC]) + paired(FFPP, tables[FFPP]))
    if len(pairs):
        print("\nPaired AUC differences on the same videos (2,000 redraws of whole groups):")
        for r in pairs.to_dict("records"):
            print(f"  {r['test']:<22} {r['comparison']:<32} {r['difference']:+.3f} [{r['low']:+.3f}, {r['high']:+.3f}]"
                  f"  ahead in {r['ahead in']:.1%}  ({r['videos']} videos)")
        pairs.to_csv(facekit.inside_data(SCORES / "compare_runs_paired.csv"), index=False)
    long.to_csv(facekit.inside_data(SCORES / "compare_runs.csv"), index=False)
    print(f"\nSaved {SCORES / 'compare_runs.csv'} and {SCORES / 'compare_runs_paired.csv'}")


if __name__ == "__main__":
    main()
