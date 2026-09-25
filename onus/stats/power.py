"""Exact power, minimum detectable effect, and the true size of a peeking schedule.

Power is computed from the test's own rejection region: the counts whose exact p-value is at most alpha, the
same rule ``decide`` applies. Exact tests are discrete, so power is not monotone in n (it has a sawtooth) but
is monotone in the effect and in alpha. The minimum detectable effect never looks at an observed result.
"""

import math
from collections.abc import Sequence
from fractions import Fraction

from onus.stats._common import check_alternative, check_count, probability
from onus.stats.binomial import HALF, _p_exact, binom_pmf


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
    return [k for k in range(n + 1) if _p_exact(k, n, null, alternative) <= level]


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
    return sum(
        (binom_pmf(k, n, p=alt) for k in rejection_region(n, p0=p0, alpha=alpha, alternative=alternative)),
        Fraction(0),
    )


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
    It depends on the design (n, p0, alpha, power) only, never on an observed result.
    """
    null = probability(p0, "p0", open_interval=True)
    target = probability(power, "power", open_interval=True)
    region = rejection_region(n, p0=null, alpha=alpha, alternative=alternative)
    if not region:
        return None
    upward = alternative != "less"

    def power_at(p: float) -> Fraction:
        alt = Fraction(p)
        return sum((binom_pmf(k, n, p=alt) for k in region), Fraction(0))

    # A non-empty region holds the extreme count (n, or 0 for "less"), so the power there is 1 and a crossing exists.
    far = 1.0 if upward else 0.0
    near = float(null)
    for _ in range(60):
        mid = (near + far) / 2
        if power_at(mid) >= target:
            far = mid
        else:
            near = mid
    return far


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
