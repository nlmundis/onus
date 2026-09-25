"""Exact binomial tails and the tests built on them: binomial, sign, paired sign, and exact McNemar.

Every p-value is an exact fraction. A two-sided p-value is defined only at a null of 1/2, where the binomial
distribution is symmetric and doubling the smaller tail is unambiguous; elsewhere the refusal says so.
"""

import math
import numbers
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache

from onus.stats._common import (
    EmptySampleError,
    MissingDataError,
    TestResult,
    check_alternative,
    check_count,
    check_method,
    probability,
)

HALF = Fraction(1, 2)
METHODS = ("exact",)
TAILS = ("upper", "lower")


# A few rows only: a row of n + 1 sums of up to n bits each is large at the sample sizes experiments reach.
@lru_cache(maxsize=16)
def _half_prefix(n: int) -> tuple[int, ...]:
    """Return the running sums of the n-th binomial row: element k is C(n, 0) + ... + C(n, k - 1)."""
    sums, total, coefficient = [0], 0, 1
    for k in range(n + 1):
        total += coefficient
        sums.append(total)
        coefficient = coefficient * (n - k) // (k + 1)  # C(n, k + 1), from C(n, k)
    return tuple(sums)


def binom_pmf(k: int, n: int, *, p: Fraction | int | str) -> Fraction:
    """Return P(X = k) for X ~ Binomial(n, p), exactly."""
    check_count(n, "n")
    check_count(k, "k")
    prob = probability(p, "p")
    if k > n:
        return Fraction(0)
    return math.comb(n, k) * prob**k * (1 - prob) ** (n - k)


def binom_tail(k: int, n: int, *, p: Fraction | int | str, tail: str) -> Fraction:
    """Return P(X >= k) (``tail="upper"``) or P(X <= k) (``tail="lower"``) for X ~ Binomial(n, p), exactly.

    Raises:
        ValueError: ``tail`` is neither "upper" nor "lower", or ``k`` or ``n`` is out of range.
    """
    check_count(n, "n")
    check_count(k, "k")
    prob = probability(p, "p")
    if tail not in TAILS:
        raise ValueError(f"tail must be one of {TAILS}, not {tail!r}")
    if k > n:
        return Fraction(0) if tail == "upper" else Fraction(1)
    if prob == HALF:
        sums = _half_prefix(n)
        count = sums[n + 1] - sums[k] if tail == "upper" else sums[k + 1]
        return Fraction(count, 2**n)
    first, last = (k, n) if tail == "upper" else (0, k)
    num, den = prob.numerator, prob.denominator
    # Sum C(n, j) num^j q^(n - j), q = den - num, over the tail by Horner's rule: each step multiplies the running
    # sum by q and adds the next term, stepped from the last by small factors, so no power of q is ever kept.
    q = den - num
    term, total = math.comb(n, first) * num**first, 0
    for j in range(first, last + 1):
        total = total * q + term
        term = term * (n - j) // (j + 1) * num  # C(n, j + 1) num^(j + 1), from C(n, j) num^j
    return Fraction(total * q ** (n - last), den**n)


def _p_exact(k: int, n: int, null: Fraction, alternative: str) -> Fraction:
    if alternative == "greater":
        return binom_tail(k, n, p=null, tail="upper")
    if alternative == "less":
        return binom_tail(k, n, p=null, tail="lower")
    upper, lower = binom_tail(k, n, p=null, tail="upper"), binom_tail(k, n, p=null, tail="lower")
    return min(Fraction(1), 2 * min(upper, lower))


def binomial_test(k: int, n: int, *, p: Fraction | int | str, alternative: str, method: str) -> TestResult:
    """Test whether ``k`` successes in ``n`` trials are consistent with success probability ``p``.

    "greater" asks whether the true probability exceeds ``p``, "less" whether it falls short. "two-sided" is
    available only at ``p = 1/2``.

    Raises:
        EmptySampleError: ``n`` is 0.
        ValueError: ``k > n``, ``p`` is not in (0, 1), a two-sided test away from 1/2, or an unknown
            alternative or method.
    """
    check_count(k, "k")
    check_count(n, "n")
    check_alternative(alternative)
    check_method(method, METHODS)
    null = probability(p, "p", open_interval=True)
    if n == 0:
        raise EmptySampleError("a binomial test needs at least one trial; n is 0")
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed n ({n})")
    if alternative == "two-sided" and null != HALF:
        raise ValueError(f"a two-sided binomial test is defined here only at p = 1/2, not {null}; test one side")
    return TestResult("binomial", method, alternative, _p_exact(k, n, null, alternative), k, n, null)


def sign_test(wins: int, losses: int, *, ties: int, alternative: str, method: str) -> TestResult:
    """Test whether wins and losses are equally likely, from their counts; ties are recorded and left out.

    "greater" asks whether wins are more likely than losses, "less" whether they are less likely.

    Raises:
        EmptySampleError: there are no wins and no losses.
        ValueError: an unknown alternative or method, or a negative count.
    """
    check_count(wins, "wins")
    check_count(losses, "losses")
    check_count(ties, "ties")
    check_alternative(alternative)
    check_method(method, METHODS)
    n = wins + losses
    if n == 0:
        raise EmptySampleError(f"a sign test needs at least one win or loss; there were none ({ties} ties)")
    return TestResult("sign", method, alternative, _p_exact(wins, n, HALF, alternative), wins, n, HALF, ties=ties)


Paired = float | int | Fraction | Decimal | None


def _present(value: Paired, name: str) -> Paired:
    """Return ``value``, or None when it is missing (None or a NaN); refuse anything that is not a real number."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real | Decimal):
        raise TypeError(f"{name} must be a real number or None, not {value!r}")
    missing = value.is_nan() if isinstance(value, Decimal) else math.isnan(value)
    return None if missing else value


def paired_sign_test(
    first: Sequence[Paired],
    second: Sequence[Paired],
    *,
    alternative: str,
    missing: str,
    method: str,
) -> TestResult:
    """Sign test on paired values: a win where ``first`` exceeds ``second``, a loss where it falls short.

    Each value is a real number (an int, float, Fraction, or Decimal) or None. A pair with a missing value
    (None, or a float or Decimal NaN) is refused with ``missing="refuse"``, or dropped and counted in
    the result with ``missing="drop"``. Equal values are ties, recorded and left out.

    Raises:
        MissingDataError: a pair has a missing value and ``missing`` is "refuse".
        EmptySampleError: no pair is a win or a loss.
        TypeError: a value is not a real number or None.
        ValueError: the sequences differ in length, or an unknown alternative, method, or missing policy.
    """
    if missing not in ("refuse", "drop"):
        raise ValueError(f"missing must be 'refuse' or 'drop', not {missing!r}")
    if len(first) != len(second):
        raise ValueError(f"first and second must be paired: {len(first)} values against {len(second)}")
    gaps, wins, losses, ties = [], 0, 0, 0
    for index, pair in enumerate(zip(first, second, strict=True)):
        a, b = _present(pair[0], f"first[{index}]"), _present(pair[1], f"second[{index}]")
        if a is None or b is None:
            gaps.append(index)
        elif a > b:
            wins += 1
        elif a < b:
            losses += 1
        else:
            ties += 1
    if gaps and missing == "refuse":
        raise MissingDataError(
            f"{len(gaps)} pairs have a missing value (the first at index {gaps[0]}); pass missing='drop' to drop them"
        )
    result = sign_test(wins, losses, ties=ties, alternative=alternative, method=method)
    warnings = (f"{len(gaps)} pairs with a missing value were dropped",) if gaps else ()
    return TestResult("sign", method, alternative, result.p_exact, wins, result.n, HALF, ties, len(gaps), warnings)


def mcnemar_exact(b: int, c: int, *, alternative: str, method: str) -> TestResult:
    """Exact McNemar test on the discordant pairs of a paired 2x2 table.

    ``b`` counts pairs positive on the first measure only and ``c`` pairs positive on the second only; the
    concordant pairs carry no information and are not taken. "greater" asks whether ``b`` outcomes are more
    likely than ``c`` outcomes.

    Raises:
        EmptySampleError: there are no discordant pairs.
    """
    check_count(b, "b")
    check_count(c, "c")
    check_alternative(alternative)
    check_method(method, METHODS)
    if b + c == 0:
        raise EmptySampleError("an exact McNemar test needs at least one discordant pair; there were none")
    return TestResult("mcnemar", method, alternative, _p_exact(b, b + c, HALF, alternative), b, b + c, HALF)
