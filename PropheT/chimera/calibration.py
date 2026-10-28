"""Channel calibration with a guaranteed false-alarm rate, from genuine calls only (Oct 24).

Every detector Chimera uses was tuned on someone else's footage, and its cut-offs do not carry over: a webcam mic
through Zoom made four voice detectors call a real speaker fake, and public footage sits mid-scale for the face
check. A recruiter can record genuine calls on its own channel (its own people, consenting volunteers) but never
labelled deepfake calls. So the cut-offs come from genuine calls alone, set by split conformal prediction:

  Put the n genuine calls' scores in order. For a target false-alarm rate alpha, take the k-th smallest,
  k = ceil((n + 1)(1 - alpha)), and set the cut-off just above it. If a new genuine call is exchangeable with the
  calibration calls (same channel, same setup, same detector), it reaches the cut-off with probability at most
  (n + 1 - m) / (n + 1), where m is the number of calibration scores below the cut-off (m >= k). That holds for any
  detector and any score distribution; it is a statement about genuine calls, and says nothing about how many fakes
  are caught, which only labelled fakes can measure.

Two limits follow. The smallest rate n calls can certify is 1 / (n + 1): 19 calls for 5%, 9 for 10%, 99 for 1%.
And the bound holds on average over calibration sets; the chance that a particular set gives a realised rate above
alpha is P(Binomial(n, 1 - alpha) >= m), reported as `delta` (with m = n it is (1 - alpha)^n).

The unit is a call segment (one recorded answer, or a 36-s piece of a block recorded in one go, cut at Zoom's
keyframes), never a half-second window: windows within a call are correlated, so they are not exchangeable. Pieces
of one recording share its room and setup, so they are less independent than separate takes; held-out takes check
that. For the live check the call's score is its highest running average.

Chimera's two strengths map to two targets: moderate at 10% and strong at 5% (`LEVELS`). With fewer calls than a
target needs, the cut-off goes above every calibration call and the card says the target was not certified.
"""

import hashlib
import math
from pathlib import Path

import numpy as np

LEVELS = {"moderate": 0.10, "strong": 0.05}    # target false-alarm rate per genuine call
LIVE_ALPHA = 0.05                              # the live meter's "LIKELY FAKE" line
UNIT = ("a call segment: one recorded answer (about 45 s), or one keyframe-to-keyframe piece (about 36 s) of a "
        "block recorded in one go")


def strictly_above(value: float, step: float = 1e-4) -> float:
    """The smallest multiple of `step` strictly greater than `value` (so a score equal to it is not flagged).
    Checked after rounding, because 0.35 / 1e-4 is 3499.9999... in floating point."""
    above = round(math.floor(value / step + 1e-9) * step, 6)
    while above <= value:
        above = round(above + step, 6)
    return above


def binom_tail(n: int, p: float, k: int) -> float:
    """P(Binomial(n, p) >= k)."""
    return float(sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(max(k, 0), n + 1)))


def level(scores, alpha: float, step: float = 1e-4) -> dict:
    """The conformal cut-off for one target rate: cut-off, its false-alarm bound, and whether the target holds."""
    s = np.sort(np.asarray([x for x in scores if x is not None], dtype=float))
    n = len(s)
    if n == 0:
        return {"n": 0, "alpha": alpha, "certified": False, "cutoff": None, "bound": None, "k": None, "delta": None}
    k = math.ceil((n + 1) * (1 - alpha) - 1e-9)
    certified = k <= n
    k = min(k, n)
    cutoff = strictly_above(float(s[k - 1]), step)
    m = int(np.sum(s < cutoff))                        # ties at the k-th score are below the cut-off too
    bound = (n + 1 - m) / (n + 1)
    return {"n": n, "alpha": alpha, "k": k, "threshold": round(float(s[k - 1]), 6), "cutoff": cutoff,
            "bound": round(bound, 4), "certified": bool(certified and bound <= alpha + 1e-12),
            "delta": round(binom_tail(n, 1 - alpha, m), 4), "smallest_certifiable": round(1 / (n + 1), 4)}


def leave_one_out(scores, alpha: float, step: float = 1e-4) -> dict:
    """Each calibration call against the cut-off made from the others: the realised rate, as a sanity check."""
    s = [x for x in scores if x is not None]
    flagged = 0
    for i, x in enumerate(s):
        cut = level(s[:i] + s[i + 1:], alpha, step)["cutoff"]
        flagged += cut is not None and x >= cut
    return {"flagged": flagged, "n": len(s)}


def entry(calib, test=(), levels=None, step: float = 1e-4) -> dict:
    """One detector's part of the card: each level's cut-off and bound, the leave-one-out check, held-out reals."""
    levels = levels or LEVELS
    calib = [x for x in calib if x is not None]
    test = [x for x in test if x is not None]
    out = {"n": len(calib), "levels": {}}
    for name, alpha in levels.items():
        lv = level(calib, alpha, step)
        if lv["cutoff"] is not None:
            lv["leave_one_out"] = leave_one_out(calib, alpha, step)
            lv["held_out_flagged"] = {"flagged": int(sum(x >= lv["cutoff"] for x in test)), "n": len(test)}
        out["levels"][name] = lv
    return out


def file_sha256(path, length: int = 12) -> str | None:
    """A short fingerprint of a weights file, so a card is tied to the detector that made its scores."""
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:length]


def describe(e: dict, level_name: str) -> str:
    """One sentence for the evidence line: what the cut-off guarantees and on how many calls."""
    lv = e["levels"][level_name]
    target = "" if lv["certified"] else f" (target {lv['alpha']:.0%} not reachable with {e['n']} calls)"
    return (f"set from {e['n']} genuine calls on this channel; a genuine call reaches it at most "
            f"{lv['bound']:.1%} of the time{target}")
