"""Experiment: can a trained model link a new persona to a known ring without an exact match?

Run from the repo root:  python experiments/linker_experiment.py data/<watchlist>.xlsx

Labels come from the watchlist itself: two personas are in the same ring when
exact identifiers chain them together. The model only sees "soft" features
(name, email style, IP overlap, timing, location, profile-handle style), never
exact identifier equality, because the exact matcher already handles those.

Fair test: whole rings are held out. For each held-out persona, every other
persona is ranked, except the ones it shares an exact identifier with. Is a
ring-mate ranked first? In the top 5? Prints aggregates only, never rows.

Result on the hiring watchlist (Oct 13, 2026): no. Top-1 precision was about 5%,
so this stays an experiment and is not part of the score.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.process import cdist
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chimera.normalize import norm_country, norm_name  # noqa: E402
from chimera.watchlist import Watchlist  # noqa: E402

FEATURES = ["name_sim", "email_local_sim", "digit_suffix", "ip_shared", "ip_same_24", "log_day_gap",
            "same_city", "same_country", "phone_area", "github_sim", "linkedin_sim"]


def main(path: str, seed: int = 13, test_share: float = 0.3) -> None:
    rng = np.random.default_rng(seed)
    wl = Watchlist.load(path)
    n, df = len(wl), wl.df

    names = [norm_name(x) or "" for x in df["Name"]]
    dates = pd.to_datetime(df["Contact Date"], errors="coerce")
    days = np.array([(d - pd.Timestamp("2019-01-01")).days if pd.notna(d) else np.nan for d in dates], dtype=float)
    city = np.array([" ".join(str(x).lower().split()) for x in df.get("Location (City, State)", [""] * n)], dtype=object)
    country = np.array([norm_country(x) or "" for x in df.get("Location (Country)", [""] * n)], dtype=object)

    def flat(field, transform):
        vals, owner = [], []
        for i, rv in enumerate(wl.row_values):
            for v in rv[field]:
                if transform(v):
                    vals.append(transform(v))
                    owner.append(i)
        return vals, np.array(owner, dtype=int)

    loc_vals, loc_owner = flat("email", lambda e: e.split("@")[0])
    gh_vals, gh_owner = flat("github", lambda g: g.split("/", 1)[1])
    li_vals, li_owner = flat("linkedin", lambda s: s.rsplit("/", 1)[1])

    suffix_index, area_index, net_index = {}, {}, {}
    q_suffix, q_area, q_net = ([set() for _ in range(n)] for _ in range(3))
    for i, rv in enumerate(wl.row_values):
        for e in rv["email"]:
            m = re.search(r"(\d{2,})$", e.split("@")[0])
            if m:
                suffix_index.setdefault(m.group(1), set()).add(i)
                q_suffix[i].add(m.group(1))
        for p in rv["phone"]:
            if p.startswith("+1") and len(p) == 12:
                area_index.setdefault(p[:5], set()).add(i)
                q_area[i].add(p[:5])
        for ip in wl.row_ips[i]:
            if "." in ip:
                net = ip.rsplit(".", 1)[0]
                net_index.setdefault(net, set()).add(i)
                q_net[i].add(net)

    ring = np.full(n, -1)
    for i, (rid, _) in wl.ring_of.items():
        ring[i] = int(rid[2:])

    def direct_links(q):
        linked = set()
        for field, values in wl.row_values[q].items():
            for v in values:
                linked |= wl.index[field].get(v, set())
        linked.discard(q)
        return linked

    def max_sim(q_vals, vals, owner):
        out = np.zeros(n)
        if q_vals and vals:
            np.maximum.at(out, owner, cdist(q_vals, vals, scorer=fuzz.ratio, workers=-1).max(axis=0) / 100.0)
        return out

    def indicator(keys, index):
        out = np.zeros(n)
        for k in keys:
            out[list(index.get(k, ()))] = 1
        return out

    def features(q):
        X = np.zeros((n, len(FEATURES)))
        if names[q]:
            X[:, 0] = cdist([names[q]], names, scorer=fuzz.token_sort_ratio, workers=-1)[0] / 100.0
        X[:, 1] = max_sim([e.split("@")[0] for e in wl.row_values[q]["email"]], loc_vals, loc_owner)
        X[:, 2] = indicator(q_suffix[q], suffix_index)
        X[:, 3] = indicator(wl.row_ips[q], wl.ip_index)
        X[:, 4] = indicator(q_net[q], net_index)
        gap = np.abs(days - days[q])
        X[:, 5] = np.log1p(np.where(np.isnan(gap), 3650, gap))
        X[:, 6] = (city == city[q]) & (city[q] != "")
        X[:, 7] = (country == country[q]) & (country[q] != "")
        X[:, 8] = indicator(q_area[q], area_index)
        X[:, 9] = max_sim([g.split("/", 1)[1] for g in wl.row_values[q]["github"]], gh_vals, gh_owner)
        X[:, 10] = max_sim([s.rsplit("/", 1)[1] for s in wl.row_values[q]["linkedin"]], li_vals, li_owner)
        return X

    ring_ids = np.unique(ring[ring >= 0])
    rng.shuffle(ring_ids)
    test_rings = set(ring_ids[: int(test_share * len(ring_ids))].tolist())

    def queries(ring_set):
        out = []
        for q in np.where(np.isin(ring, list(ring_set)))[0]:
            mates = set(np.where(ring == ring[q])[0]) - {q} - direct_links(q)
            if mates:
                out.append((q, mates))
        return out

    train_q, test_q = queries(set(ring_ids.tolist()) - test_rings), queries(test_rings)
    print(f"Rings: {len(ring_ids)} ({len(test_rings)} held out). "
          f"Personas with ring-mates beyond exact links: train {len(train_q)}, test {len(test_q)}")

    Xs, ys = [], []
    for q, mates in train_q:
        X, excluded = features(q), direct_links(q) | {q}
        pool = np.array([j for j in range(n) if j not in excluded and ring[j] != ring[q]])
        pos = rng.choice(list(mates), size=min(10, len(mates)), replace=False)
        neg = rng.choice(pool, size=min(40, len(pool)), replace=False)
        Xs += [X[pos], X[neg]]
        ys += [np.ones(len(pos)), np.zeros(len(neg))]
    Xtr, ytr = np.vstack(Xs), np.concatenate(ys)
    print(f"Training pairs: {len(ytr)} ({int(ytr.sum())} positive)")

    models = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced")),
        "boosted_trees": HistGradientBoostingClassifier(max_iter=200, random_state=seed),
    }
    for model in models.values():
        model.fit(Xtr, ytr)

    print("\nLogistic regression weights (standardized features):")
    for f, c in sorted(zip(FEATURES, models["logistic"][-1].coef_[0]), key=lambda x: -abs(x[1])):
        print(f"  {f:16s} {c:+.2f}")

    ranks = {k: [] for k in ["logistic", "boosted_trees", "name_only", "time_only", "email_style_only"]}
    pair_scores, pair_labels, top1 = [], [], []
    for q, mates in test_q:
        X, excluded = features(q), direct_links(q) | {q}
        cand = np.array([j for j in range(n) if j not in excluded])
        is_mate = np.isin(cand, list(mates))
        scores = {
            "logistic": models["logistic"].predict_proba(X[cand])[:, 1],
            "boosted_trees": models["boosted_trees"].predict_proba(X[cand])[:, 1],
            "name_only": X[cand, 0],
            "time_only": -X[cand, 5],
            "email_style_only": X[cand, 1],
        }
        for k, s in scores.items():
            ranks[k].append(int(np.where(is_mate[np.argsort(-s, kind="stable")])[0][0]) + 1)
        best = int(np.argmax(scores["boosted_trees"]))
        top1.append((scores["boosted_trees"][best], bool(is_mate[best])))
        neg = rng.choice(np.where(~is_mate)[0], size=50, replace=False)
        pos = np.where(is_mate)[0]
        pair_scores += list(scores["boosted_trees"][pos]) + list(scores["boosted_trees"][neg])
        pair_labels += [1] * len(pos) + [0] * len(neg)

    print(f"\nPair AUC (boosted trees, held-out rings): {roc_auc_score(pair_labels, pair_scores):.3f}")
    print("\nIs a ring-mate ranked in the top k? (exact-match links removed)")
    print(f"  {'ranker':18s} {'top-1':>6s} {'top-5':>6s} {'top-20':>7s} {'median rank':>12s}")
    for k, r in ranks.items():
        r = np.array(r)
        print(f"  {k:18s} {np.mean(r <= 1):6.1%} {np.mean(r <= 5):6.1%} {np.mean(r <= 20):7.1%} {np.median(r):12.0f}")
    s, hit = np.array([x[0] for x in top1]), np.array([x[1] for x in top1])
    print("\nTop-1 precision (boosted trees): when the best candidate scores at least t, how often is it a ring-mate?")
    for t in (0.5, 0.7, 0.9):
        if (s >= t).any():
            print(f"  t={t}: {(s >= t).sum()} of {len(s)} queries, precision {hit[s >= t].mean():.0%}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python experiments/linker_experiment.py <watchlist.xlsx|csv>")
    main(sys.argv[1])
