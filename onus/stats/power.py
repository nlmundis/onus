"""Exact power, minimum detectable effect, and the true size of a peeking schedule.

Power is computed from the test's own rejection region: the counts whose exact p-value is at most alpha, the
same rule ``decide`` applies. Exact tests are discrete, so power is not monotone in n (it has a sawtooth) but
is monotone in the effect and in alpha. The minimum detectable effect never looks at an observed result.
"""

import math
from collections.abc import Callable, Sequence
from fractions import Fraction

from onus.stats._common import check_alternative, check_count, probability
from onus.stats.binomial import HALF, _p_exact, binom_tail
from onus.stats.intervals import _log_pmf

# How far the minimum detectable effect is moved outward from the float search's answer.
MARGIN = 1e-9


def rejection_region(n: int, *, p0: Fraction | int | str, alpha: Fraction | int | str, alternative: str) -> list[int]:
    """Return every count k in 0..n whose exact binomial p-value against ``p0`` is at most ``alpha``.

    Raises:
        ValueError: a two-sided region away from ``p0 = 1/2``, or an out-of-range argument.
    """
    check_count(n, "n")
    check_alternative(alternative)
    null = probability(p0, "p0", open_interval=True)
    level = probability(alpha, "alpha")
    if alternative == "two-sided" and null != HALF:
        raise ValueError(f"a two-sided binomial test is defined here only at p0 = 1/2, not {null}; use one side")
    if n == 0:
        return []

    def rejects(k: int) -> bool:
        return _p_exact(k, n, null, alternative) <= level

    # Each alternative's p-value is monotone in k (a two-sided one at 1/2 on each half, symmetrically), so the
    # region is one tail, or two mirrored tails, whose edge a bisection finds in O(log n) exact p-values.
    if alternative == "greater":
        start = _first(lambda k: rejects(k), 0, n + 1)  # p falls as k rises
        return list(range(start, n + 1))
    if alternative == "less":
        stop = _first(lambda k: not rejects(k), 0, n + 1)  # p rises as k rises
        return list(range(0, stop))
    stop = _first(lambda k: not rejects(k), 0, n // 2 + 1)  # on the lower half, two-sided p rises with k
    lower = set(range(0, stop))
    return sorted(lower | {n - k for k in lower})


def _first(predicate: Callable[[int], bool], lo: int, hi: int) -> int:
    """Return the smallest k in [lo, hi) where the monotone ``predicate`` holds, or ``hi`` if it holds nowhere."""
    while lo < hi:
        mid = (lo + hi) // 2
        if predicate(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def _region_power(region: list[int], n: int, p: Fraction) -> Fraction:
    """Return P(X in region) for X ~ Binomial(n, p), from the exact tails of each contiguous run of counts."""
    total, start = Fraction(0), 0
    for i, k in enumerate(region):
        if i == 0 or k != region[i - 1] + 1:
            start = k
        if i == len(region) - 1 or region[i + 1] != k + 1:
            total += binom_tail(start, n, p=p, tail="upper") - binom_tail(k + 1, n, p=p, tail="upper")
    return total


def binomial_power(
    n: int,
    *,
    p0: Fraction | int | str,
    p_alt: Fraction | int | str,
    alpha: Fraction | int | str,
    alternative: str,
) -> Fraction:
    """Return the exact probability that the binomial test against ``p0`` rejects when the truth is ``p_alt``."""
    alt = probability(p_alt, "p_alt")
    return _region_power(rejection_region(n, p0=p0, alpha=alpha, alternative=alternative), n, alt)


def sign_test_power(n: int, *, p_alt: Fraction | int | str, alpha: Fraction | int | str, alternative: str) -> Fraction:
    """Return the exact power of the sign test on ``n`` non-tied pairs when a win has probability ``p_alt``."""
    return binomial_power(n, p0=HALF, p_alt=p_alt, alpha=alpha, alternative=alternative)


def binomial_mde(
    n: int,
    *,
    p0: Fraction | int | str,
    alpha: Fraction | int | str,
    power: Fraction | int | str,
    alternative: str,
) -> float | None:
    """Return the success probability nearest ``p0`` at which the test reaches ``power``, or None if none does.

    For "greater" and "two-sided" it is the smallest probability above ``p0``; for "less", the largest below.
    It depends on the design (n, p0, alpha, power) only, never on an observed result. It is found to within
    about 1e-9 and rounded outward, so the exact power at the returned probability is at least ``power``.
    """
    null = probability(p0, "p0", open_interval=True)
    target = probability(power, "power", open_interval=True)
    region = rejection_region(n, p0=null, alpha=alpha, alternative=alternative)
    if not region:
        return None
    if _region_power(region, n, null) >= target:
        raise ValueError(
            f"the test reaches power {target} with no effect at all (alpha is that large), so no effect is minimal"
        )
    upward = alternative != "less"

    def float_power(p: float) -> float:
        return math.fsum(math.exp(_log_pmf(k, n, p)) for k in region)

    # A non-empty region holds the extreme count (n, or 0 for "less"), so the power there is 1 and a crossing
    # exists. The search runs in floats, whose power is good to about 1e-11 even at n in the tens of thousands;
    # the answer is then moved outward by MARGIN, so the exact power there is at least the target.
    far = 1.0 if upward else 0.0
    near = float(null)
    while (mid := (near + far) / 2) not in (near, far):
        if float_power(mid) >= target:
            far = mid
        else:
            near = mid
    return min(1.0, far + MARGIN) if upward else max(0.0, far - MARGIN)


def sign_test_mde(
    n: int, *, alpha: Fraction | int | str, power: Fraction | int | str, alternative: str
) -> float | None:
    """Return the smallest win probability (largest, for "less") at which the sign test reaches ``power``."""
    return binomial_mde(n, p0=HALF, alpha=alpha, power=power, alternative=alternative)


def sequential_size(looks: Sequence[int], *, alpha: Fraction | int | str, alternative: str) -> Fraction:
    """Return the exact probability, under the null, that a sign test run at every look rejects at least once.

    ``looks`` are the cumulative numbers of non-tied pairs at which the result is read, in increasing order;
    each look applies the fixed-sample test at level ``alpha``. With one look this is that test's exact size,
    at most ``alpha``; with more, it is the inflated error rate that peeking actually produces.

    Raises:
        ValueError: ``looks`` is empty or not strictly increasing positive counts.
    """
    check_alternative(alternative)
    level = probability(alpha, "alpha")
    if not looks or any(check_count(n, "look") < 1 for n in looks) or list(looks) != sorted(set(looks)):
        raise ValueError(f"looks must be strictly increasing positive counts, not {list(looks)}")
    # weights[k] * 2**-n is the probability of reaching the current look with k wins and no rejection yet.
    weights, n, rejected = {0: 1}, 0, Fraction(0)
    for look in looks:
        steps = look - n
        grown: dict[int, int] = {}
        for k, weight in weights.items():
            for j in range(steps + 1):
                grown[k + j] = grown.get(k + j, 0) + weight * math.comb(steps, j)
        n = look
        region = set(rejection_region(n, p0=HALF, alpha=level, alternative=alternative))
        rejected += Fraction(sum(w for k, w in grown.items() if k in region), 2**n)
        weights = {k: w for k, w in grown.items() if k not in region}
    return rejected
