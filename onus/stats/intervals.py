"""Confidence intervals for a binomial proportion: Wilson score and Clopper-Pearson.

Both refuse n = 0, where there is no proportion to bound. The bounds are floats: Wilson's involves a normal
quantile, and Clopper-Pearson's are roots of the exact binomial tails, found by bisection to float precision.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from statistics import NormalDist

from onus.stats._common import EmptySampleError, check_count, probability


@dataclass(frozen=True)
class Interval:
    """A confidence interval for a binomial proportion.

    Attributes:
        low: the lower bound, in [0, 1].
        high: the upper bound, in [0, 1].
        k: the successes it was computed from.
        n: the trials it was computed from.
        confidence: the nominal coverage, e.g. 19/20.
        method: "wilson" or "clopper-pearson".
    """

    low: float
    high: float
    k: int
    n: int
    confidence: Fraction
    method: str


def _checked(k: int, n: int, confidence: Fraction | int | str) -> Fraction:
    check_count(k, "k")
    check_count(n, "n")
    if n == 0:
        raise EmptySampleError("a proportion needs at least one trial; n is 0")
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed n ({n})")
    return probability(confidence, "confidence", open_interval=True)


def wilson(k: int, n: int, *, confidence: Fraction | int | str | None = None, z: float | None = None) -> Interval:
    """Return the Wilson score interval for ``k`` successes in ``n`` trials.

    Give ``confidence`` (default 0.95), or ``z``, the normal quantile to use directly; not both. With ``z``, the
    interval records the two-sided confidence that ``z`` implies.

    Raises:
        EmptySampleError: ``n`` is 0.
        ValueError: both ``confidence`` and ``z`` are given, or ``z`` is not a positive finite quantile.
        TypeError: ``z`` is not an int or a float (a bool, a string, or an exact number).
    """
    if z is None:
        level = _checked(k, n, "0.95" if confidence is None else confidence)
        crit = NormalDist().inv_cdf(1 - float(1 - level) / 2)
    else:
        if confidence is not None:
            raise ValueError("wilson takes confidence or z, not both")
        if isinstance(z, bool) or not isinstance(z, int | float):
            raise TypeError(f"z must be a float such as 1.96, not {z!r}")
        crit = float(z)
        implied = 2 * NormalDist().cdf(crit) - 1 if math.isfinite(crit) else math.nan
        if not 0 < implied < 1:
            raise ValueError(
                f"z must be a positive finite quantile below about 8 (where float confidence is 1), not {z!r}"
            )
        level = _checked(k, n, Fraction(implied))
    phat = k / n
    denom = 1 + crit**2 / n
    center = (phat + crit**2 / (2 * n)) / denom
    half = crit * math.sqrt(phat * (1 - phat) / n + crit**2 / (4 * n * n)) / denom
    # At k = 0 and k = n the bound is exactly 0 or 1; in floats center -/+ half only lands near it.
    low = 0.0 if k == 0 else max(0.0, center - half)
    high = 1.0 if k == n else min(1.0, center + half)
    return Interval(low, high, k, n, level, "wilson")


def _log_pmf(j: int, n: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * math.log(p) + (n - j) * math.log1p(-p)


def _upper(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), 0 < p < 1, in floats."""
    return math.fsum(math.exp(_log_pmf(j, n, p)) for j in range(k, n + 1))


def _root(f: Callable[[float], float], target: float) -> float:
    """Return the p in (0, 1) where the increasing function ``f`` crosses ``target``, by bisection."""
    lo, hi = 0.0, 1.0
    # Halving a float interval ends when the midpoint can no longer move: at most about 1075 steps.
    while (mid := (lo + hi) / 2) not in (lo, hi):
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return mid


def clopper_pearson(k: int, n: int, *, confidence: Fraction | int | str = "0.95") -> Interval:
    """Return the exact Clopper-Pearson interval for ``k`` successes in ``n`` trials.

    The lower bound is the p at which P(X >= k) equals (1 - confidence) / 2, the upper the p at which
    P(X <= k) does; they are 0 at k = 0 and 1 at k = n. Its coverage is at least the nominal level at every p.

    Raises:
        EmptySampleError: ``n`` is 0.
    """
    level = _checked(k, n, confidence)
    tail = float(1 - level) / 2
    low = 0.0 if k == 0 else _root(lambda p: _upper(k, n, p), tail)
    # By symmetry, the upper bound for k is one minus the lower bound for n - k. Solving P(X >= k + 1) = 1 - tail
    # directly would lose everything to cancellation once 1 - tail rounds to 1 at high confidence.
    high = 1.0 if k == n else 1 - _root(lambda p: _upper(n - k, n, p), tail)
    return Interval(low, high, k, n, level, "clopper-pearson")
