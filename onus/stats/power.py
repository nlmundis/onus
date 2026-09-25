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

# The minimum detectable effect is a multiple of 1/GRID (about 9.3e-10), where its exact power is cheap to check.
GRID = 2**30


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
    """Return P(X in region) for X ~ Binomial(n, p), from the exact tails of each contiguous run of counts.

    A run that starts at 0 or ends at n, as every run of a test's region does, costs one tail, not two.
    """
    total, start = Fraction(0), 0
    for i, k in enumerate(region):
        if i == 0 or k != region[i - 1] + 1:
            start = k
        if i == len(region) - 1 or region[i + 1] != k + 1:
            if start == 0:
                total += binom_tail(k, n, p=p, tail="lower")
            elif k == n:
                total += binom_tail(start, n, p=p, tail="upper")
            else:
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
    It depends on the design (n, p0, alpha, power) only, never on an observed result. The answer is a multiple
    of 2^-30: the one nearest ``p0`` whose exact power is at least ``power``, checked exactly, so the next
    multiple toward ``p0`` falls short of it.
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
    inside = set(region)
    outside = [k for k in range(n + 1) if k not in inside]
    miss = float(1 - target)

    def float_reaches(p: float) -> bool:
        # Near power 1 the power's rounding error would swamp the gap to the target, so the missed mass is
        # summed instead; each sum is then accurate relative to its own size.
        if target > HALF:
            return math.fsum(math.exp(_log_pmf(k, n, p)) for k in outside) <= miss
        return math.fsum(math.exp(_log_pmf(k, n, p)) for k in region) >= target

    # A non-empty region holds the extreme count (n, or 0 for "less"), so the power there is 1 and a crossing
    # exists. A float search finds it closely; the exact check then settles it on the grid.
    far = 1.0 if upward else 0.0
    near = float(null)
    while (mid := (near + far) / 2) not in (near, far):
        if float_reaches(mid):
            far = mid
        else:
            near = mid
    # Grid points are indexed outward from p0, so a larger index is a larger effect in either direction.
    base = math.floor(null * GRID) if upward else math.ceil(null * GRID)
    top = GRID - base if upward else base

    def reaches(i: int) -> bool:
        return _region_power(region, n, Fraction(base + i if upward else base - i, GRID)) >= target

    # Index 0 is p0 or just short of it, so it fails; index top is probability 1 (0 for "less"), so it reaches.
    index = _settle(reaches, math.ceil(abs(far * GRID - base)), top)
    return (base + index if upward else base - index) / GRID


def _settle(reaches: Callable[[int], bool], guess: int, top: int) -> int:
    """Return the smallest index in 1..top where the monotone ``reaches`` holds, searching out from ``guess``.

    Index 0 is taken to fail, and 1 <= guess <= top. It gallops outward to a reaching index and inward to a
    failing one, then bisects between them.

    Raises:
        ValueError: ``reaches`` fails even at ``top``.
    """
    low, high, step = guess - 1, guess, 1
    while not reaches(high):
        if high == top:
            raise ValueError(f"no index up to {top} reaches the target")
        low, high, step = high, min(top, high + step), 2 * step
    step = 1
    while low > 0 and reaches(low):
        high, low, step = low, max(0, low - step), 2 * step
    while high - low > 1:
        mid = (low + high) // 2
        low, high = (low, mid) if reaches(mid) else (mid, high)
    return high


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
