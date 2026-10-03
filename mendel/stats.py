"""Statistics: the paired bootstrap, run summaries and the gene label rule."""
from __future__ import annotations

from collections.abc import Hashable, Sequence

import numpy as np


def paired_bootstrap(diffs: Sequence[float], strata: Sequence[Hashable] | None = None, *,
                     n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """(mean, lo, hi): the mean paired difference and its 95% bootstrap interval.

    `diffs` are per-pair differences (one per instance and seed). With `strata` (the instance of each
    pair) the estimate is the mean of per-instance means, and seeds are resampled within each
    instance: the instances are the fixed, listed ones; the seeds are the random part.
    If any instance has fewer than two pairs there is nothing to resample within it, so all pairs are
    pooled instead (otherwise one seed per instance would give a zero-width interval).
    The resampling is seeded, so the same data always gives the same interval.
    Intervals from fewer than about four pairs per instance are rough; treat them as such."""
    values = np.asarray(list(diffs), dtype=float)
    if values.size == 0:
        return 0.0, 0.0, 0.0
    if strata is None:
        groups = [values]
    else:
        labels = list(strata)
        order = list(dict.fromkeys(labels))
        groups = [values[[i for i, s in enumerate(labels) if s == name]] for name in order]
        if min(len(g) for g in groups) < 2:
            groups = [values]
    point = float(np.mean([g.mean() for g in groups]))
    rng = np.random.default_rng(seed)
    boot = np.zeros(n_boot)
    for g in groups:
        picks = rng.integers(0, len(g), size=(n_boot, len(g)))
        boot += g[picks].mean(axis=1)
    boot /= len(groups)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return point, float(lo), float(hi)


def effect_summary(diffs: Sequence[float], strata: Sequence[Hashable] | None = None) -> dict:
    """{"effect", "ci": [lo, hi], "pairs"} for a list of paired differences."""
    effect, lo, hi = paired_bootstrap(diffs, strata)
    return {"effect": effect, "ci": [lo, hi], "pairs": len(diffs)}


def summarise(scores: Sequence[float], direction: str = "max") -> dict:
    """{"mean", "best", "runs"}; best is the max for 'max' problems and the min for 'min'."""
    scores = [float(s) for s in scores]
    if not scores:
        return {"mean": None, "best": None, "runs": 0}
    best = max(scores) if direction == "max" else min(scores)
    return {"mean": sum(scores) / len(scores), "best": best, "runs": len(scores)}


def verdict(result: dict | None) -> int:
    """+1 when the interval is entirely above zero (helps), -1 entirely below (hurts), else 0."""
    if not result or not result.get("runs") or result.get("ci") is None:
        return 0
    lo, hi = result["ci"]
    if lo > 0:
        return 1
    if hi < 0:
        return -1
    return 0


def _within(result: dict | None, tol: float) -> bool:
    if not result or result.get("ci") is None:
        return False
    lo, hi = result["ci"]
    return -tol <= lo and hi <= tol


def label_gene(train: dict | None, heldout: dict | None, tol: float = 0.0) -> str:
    """The gene label rule of PROTOCOL.md section 3.

    `train` is the gene's knockout on training instances, `heldout` its knockout pooled over the
    held-out instances; both are {"effect", "ci": [lo, hi], "runs"}. Effects are 'on minus off'.

      general       helps on training instances and on held-out instances (both intervals above zero)
      specific      helps on training instances only
      harmful       hurts on training instances, or hurts on held-out without helping on training
      neutral       both intervals span zero and lie within +-tol of it (no effect, measured tightly)
      inconclusive  an interval spans zero and is too wide to call the gene neutral, or there is no data
    """
    if not train or not train.get("runs"):
        return "inconclusive"
    t, h = verdict(train), verdict(heldout)
    if t > 0:
        return "general" if h > 0 else "specific"
    if t < 0 or h < 0:
        return "harmful"
    if h == 0 and _within(train, tol) and (not heldout or not heldout.get("runs") or _within(heldout, tol)):
        return "neutral"
    return "inconclusive"
