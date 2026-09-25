"""onus.stats against brute force, against scipy and statsmodels, and against simulation.

The oracles enumerate every outcome sequence for small n, so an exact tail is checked against a count of
sequences rather than against another formula. The reference fixture (``make reference``) is scipy's and
statsmodels' answers for a fixed case list; the sims file (``make sims``) is simulated rejection rates. Both
headers carry the sha256 of the script that wrote them, so a changed script with an unchanged file fails.
"""

import hashlib
import inspect
import io
import json
import math
import re
import signal
import sys
import tempfile
import time
import types
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr
from decimal import Decimal
from fractions import Fraction
from itertools import product
from pathlib import Path
from statistics import NormalDist
from typing import Any
from unittest import mock

import onus.stats
from onus.stats import (
    EmptySampleError,
    Family,
    IncompleteFamilyError,
    MissingDataError,
    UndeclaredMemberError,
    benjamini_hochberg,
    binom_pmf,
    binom_tail,
    binomial_mde,
    binomial_power,
    binomial_test,
    clopper_pearson,
    decide,
    holm,
    mcnemar_exact,
    paired_sign_test,
    rejection_region,
    sequential_size,
    sign_test,
    sign_test_mde,
    sign_test_power,
    wilson,
)
from tools.reference import make_reference
from tools.sims import ht_sims

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "tests" / "reference"
HALF = Fraction(1, 2)
ALTERNATIVES = ("two-sided", "greater", "less")


def sequences(n: int, p: Fraction) -> "list[tuple[int, Fraction]]":
    """Every outcome sequence of n trials, as (successes, probability), by enumeration."""
    return [(sum(seq), p ** sum(seq) * (1 - p) ** (n - sum(seq))) for seq in product((0, 1), repeat=n)]


def sign(wins: int, n: int, alternative: str) -> Fraction:
    return sign_test(wins, n - wins, ties=0, alternative=alternative, method="exact").p_exact


class OracleTest(unittest.TestCase):
    """Exact tails and p-values against a count over every outcome sequence."""

    def test_tails_at_one_half_count_every_sequence_for_n_up_to_14(self):
        for n in range(1, 15):
            seqs = sequences(n, HALF)
            for k in range(n + 1):
                with self.subTest(n=n, k=k):
                    self.assertEqual(binom_tail(k, n, p=HALF, tail="upper"), sum(w for s, w in seqs if s >= k))
                    self.assertEqual(binom_tail(k, n, p=HALF, tail="lower"), sum(w for s, w in seqs if s <= k))

    def test_tails_away_from_one_half_count_every_sequence(self):
        for p in (Fraction(1, 3), Fraction(3, 10), Fraction(0), Fraction(1)):
            for n in range(1, 11):
                seqs = sequences(n, p)
                for k in range(n + 1):
                    with self.subTest(p=p, n=n, k=k):
                        self.assertEqual(binom_tail(k, n, p=p, tail="upper"), sum(w for s, w in seqs if s >= k))
                        self.assertEqual(binom_tail(k, n, p=p, tail="lower"), sum(w for s, w in seqs if s <= k))
        self.assertEqual(binom_tail(5, 3, p="1/3", tail="upper"), 0)
        self.assertEqual(binom_tail(5, 3, p="1/3", tail="lower"), 1)

    def test_the_two_sided_p_value_is_every_outcome_no_likelier_than_the_one_observed(self):
        # At 1/2 the distribution is symmetric, so doubling the smaller tail is the same as summing every
        # outcome at most as likely as the observed one; the second definition is computed here by brute force.
        for n in range(1, 15):
            pmf = {k: Fraction(math.comb(n, k), 2**n) for k in range(n + 1)}
            for k in range(n + 1):
                with self.subTest(n=n, k=k):
                    self.assertEqual(sign(k, n, "two-sided"), sum(v for v in pmf.values() if v <= pmf[k]))

    def test_one_sided_p_values_are_the_matching_tail(self):
        for n in range(1, 15):
            seqs = sequences(n, HALF)
            for k in range(n + 1):
                with self.subTest(n=n, k=k):
                    self.assertEqual(sign(k, n, "greater"), sum(w for s, w in seqs if s >= k))
                    self.assertEqual(sign(k, n, "less"), sum(w for s, w in seqs if s <= k))


class DecisionTest(unittest.TestCase):
    def test_a_p_value_equal_to_alpha_rejects(self):
        # 4 wins and no losses: P(X >= 4) = 1/16 exactly, so it rejects at 1/16 and not just below.
        result = sign_test(4, 0, ties=0, alternative="greater", method="exact")
        self.assertEqual(result.p_exact, Fraction(1, 16))
        self.assertTrue(decide(result, "1/16"))
        self.assertFalse(decide(result, "0.0624"))
        self.assertTrue(decide(Fraction(1, 20), "0.05"))

    def test_alpha_and_p_values_must_be_exact(self):
        result = sign_test(4, 0, ties=0, alternative="greater", method="exact")
        with self.assertRaisesRegex(TypeError, "string such as '0.05'"):
            decide(result, 0.05)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "not True"):
            decide(result, True)
        with self.assertRaisesRegex(ValueError, r"alpha must lie in \[0, 1\]"):
            decide(result, "3/2")
        self.assertEqual(result.p_value, 0.0625)

    def test_a_string_that_is_not_a_number_is_refused_by_name(self):
        result = sign_test(4, 0, ties=0, alternative="greater", method="exact")
        for text in ("nan", "inf", "abc", "1/0", ""):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, rf"alpha must be an exact number such as '0.05', not {text!r}"):
                    decide(result, text)
                with self.assertRaisesRegex(ValueError, rf"power must be an exact number such as '0.05', not {text!r}"):
                    sign_test_mde(20, alpha="0.05", power=text, alternative="greater")


@contextmanager
def within(seconds: float) -> Iterator[None]:
    """Fail when the budget runs out rather than when the work ends, so a slow regression fails in seconds."""

    def expire(signum: int, frame: object) -> None:
        raise AssertionError(f"took longer than {seconds} seconds")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class ScaleTest(unittest.TestCase):
    """Exact tails stay fast at sample sizes a real experiment reaches; budgets are generous, failures are not."""

    def test_a_sign_test_on_twenty_thousand_pairs_takes_seconds_not_minutes(self):
        from onus.stats import binomial

        binomial._half_prefix.cache_clear()
        with within(5.0):
            result = sign_test(10100, 9900, ties=0, alternative="two-sided", method="exact")
        self.assertTrue(0 < result.p_exact < 1)

    def test_the_minimum_detectable_effect_of_a_thousand_pairs_takes_seconds(self):
        with within(5.0):
            mde = sign_test_mde(1000, alpha="0.05", power="0.8", alternative="two-sided")
        assert mde is not None
        self.assertGreaterEqual(
            sign_test_power(1000, p_alt=Fraction(mde), alpha="0.05", alternative="two-sided"), Fraction(4, 5)
        )

    def test_the_minimum_detectable_effect_at_scale_takes_seconds(self):
        for kwargs in (
            {"n": 20000, "p0": "1/2", "alternative": "less"},
            {"n": 2000, "p0": "1/4", "alternative": "greater"},
        ):
            with self.subTest(**kwargs):
                with within(15.0):
                    self.assertIsNotNone(binomial_mde(alpha="0.05", power="0.9", **kwargs))  # type: ignore[arg-type]

    def test_the_rejection_region_matches_every_count_it_skips(self):
        # The region is found by bisection on the p-value's monotone edges; every count must agree with decide.
        for n in (1, 2, 7, 30, 101):
            for p0, sides in (("1/2", ALTERNATIVES), ("1/5", ("greater", "less")), ("9/10", ("greater", "less"))):
                for alternative in sides:
                    for alpha in ("1/1000", "1/20", "1/3", "1"):
                        with self.subTest(n=n, p0=p0, alternative=alternative, alpha=alpha):
                            expected = [
                                k
                                for k in range(n + 1)
                                if decide(binomial_test(k, n, p=p0, alternative=alternative, method="exact"), alpha)
                            ]
                            self.assertEqual(rejection_region(n, p0=p0, alpha=alpha, alternative=alternative), expected)

    def test_a_one_sided_test_away_from_one_half_on_twenty_thousand_trials_takes_a_second(self):
        with within(2.0):
            result = binomial_test(6800, 20000, p="1/3", alternative="greater", method="exact")
        self.assertTrue(0 < result.p_exact < 1)

    def test_a_tail_away_from_one_half_keeps_one_running_sum_not_every_power(self):
        import tracemalloc

        # p from a float carries a 2^53 denominator; keeping every power of 1 - p held 14 MB at n = 2000, 0.1 MB now.
        tracemalloc.start()
        try:
            with within(10.0):
                binom_tail(1000, 2000, p=Fraction(0.4912345678901234), tail="lower")
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2_000_000)

    def test_a_budget_fails_when_it_runs_out_not_when_the_work_ends(self):
        start = time.perf_counter()
        with self.assertRaisesRegex(AssertionError, "longer than 0.05 seconds"):
            with within(0.05):
                time.sleep(10)
        self.assertLess(time.perf_counter() - start, 5.0)


class ExactSizeTest(unittest.TestCase):
    """The exact tests never reject a true null more often than alpha."""

    def test_size_is_at_most_alpha_for_every_n_up_to_200(self):
        for alpha in (Fraction(1, 100), Fraction(1, 20), Fraction(1, 10)):
            for alternative in ALTERNATIVES:
                for n in range(1, 201):
                    size = sum(
                        (
                            Fraction(math.comb(n, k), 2**n)
                            for k in range(n + 1)
                            if decide(sign(k, n, alternative), alpha)
                        ),
                        Fraction(0),
                    )
                    if size > alpha:
                        self.fail(f"size {size} > alpha {alpha} at n={n}, {alternative}")


class BinomialTest(unittest.TestCase):
    def test_a_result_carries_its_counts(self):
        result = binomial_test(3, 10, p="1/3", alternative="less", method="exact")
        self.assertEqual((result.test, result.method, result.successes, result.n), ("binomial", "exact", 3, 10))
        self.assertEqual(result.null, Fraction(1, 3))
        self.assertEqual(result.p_exact, binom_tail(3, 10, p="1/3", tail="lower"))

    def test_refusals(self):
        cases = {
            "only at p = 1/2": lambda: binomial_test(3, 10, p="1/3", alternative="two-sided", method="exact"),
            "at least one trial": lambda: binomial_test(0, 0, p="1/2", alternative="greater", method="exact"),
            r"k \(11\) cannot exceed n \(10\)": lambda: binomial_test(
                11, 10, p="1/2", alternative="less", method="exact"
            ),
            r"p must lie in \(0, 1\)": lambda: binomial_test(1, 2, p=1, alternative="less", method="exact"),
            "alternative must be one of": lambda: binomial_test(1, 2, p="1/2", alternative="up", method="exact"),
            "method must be one of": lambda: binomial_test(1, 2, p="1/2", alternative="less", method="normal"),
            "tail must be one of": lambda: binom_tail(1, 2, p="1/2", tail="both"),
            "n must not be negative": lambda: binom_tail(1, -2, p="1/2", tail="upper"),
        }
        for message, call in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    call()
        self.assertTrue(issubclass(EmptySampleError, ValueError))
        with self.assertRaisesRegex(TypeError, "k must be an int"):
            binom_tail(1.0, 2, p="1/2", tail="upper")  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "k must be an int"):
            binom_tail(True, 2, p="1/2", tail="upper")

    def test_a_one_sided_p_value_computes_only_its_own_tail(self):
        from onus.stats import binomial

        for alternative, tail in (("greater", "upper"), ("less", "lower")):
            with self.subTest(alternative=alternative):
                with mock.patch.object(binomial, "binom_tail", wraps=binomial.binom_tail) as spy:
                    binomial_test(3, 10, p="1/3", alternative=alternative, method="exact")
                self.assertEqual(spy.call_args_list, [mock.call(3, 10, p=Fraction(1, 3), tail=tail)])

    def test_the_pmf_matches_the_tails(self):
        from onus.stats import binom_pmf

        self.assertEqual(
            binom_pmf(2, 5, p="1/3"), binom_tail(2, 5, p="1/3", tail="upper") - binom_tail(3, 5, p="1/3", tail="upper")
        )
        self.assertEqual(binom_pmf(6, 5, p="1/3"), 0)


class SignTestTest(unittest.TestCase):
    def test_ties_are_recorded_and_left_out(self):
        result = sign_test(7, 2, ties=3, alternative="two-sided", method="exact")
        self.assertEqual((result.successes, result.n, result.ties), (7, 9, 3))
        self.assertEqual(result.p_exact, sign(7, 9, "two-sided"))
        with self.assertRaisesRegex(EmptySampleError, r"none \(4 ties\)"):
            sign_test(0, 0, ties=4, alternative="greater", method="exact")

    def test_paired_values_become_wins_losses_and_ties(self):
        result = paired_sign_test(
            [3, 5, 2, 4, 4], [1, 5, 3, 2, 1], alternative="greater", missing="refuse", method="exact"
        )
        self.assertEqual((result.successes, result.n, result.ties, result.missing), (3, 4, 1, 0))
        self.assertEqual(result.p_exact, sign(3, 4, "greater"))
        self.assertEqual(result.warnings, ())

    def test_a_missing_value_is_refused_or_dropped_as_asked(self):
        first = [3, None, 2, float("nan"), 4, 6]
        second = [1, 5, 3, 2, None, 1]
        with self.assertRaisesRegex(MissingDataError, r"3 pairs have a missing value \(the first at index 1\)"):
            paired_sign_test(first, second, alternative="greater", missing="refuse", method="exact")
        dropped = paired_sign_test(first, second, alternative="greater", missing="drop", method="exact")
        self.assertEqual((dropped.successes, dropped.n, dropped.missing), (2, 3, 3))
        self.assertEqual(dropped.warnings, ("3 pairs with a missing value were dropped",))
        with self.assertRaisesRegex(ValueError, "missing must be 'refuse' or 'drop'"):
            paired_sign_test(first, second, alternative="greater", missing="ignore", method="exact")
        with self.assertRaisesRegex(ValueError, "3 values against 2"):
            paired_sign_test([1, 2, 3], [1, 2], alternative="greater", missing="drop", method="exact")

    def test_a_decimal_nan_is_missing_and_a_non_number_is_refused(self):
        first: list[float | Fraction | Decimal] = [Decimal("3"), Decimal("NaN"), Decimal("sNaN"), Fraction(1, 2), 2.5]
        second: list[float | Fraction | Decimal] = [Decimal("1"), Decimal("2"), 1, Decimal("0.25"), 3]
        with self.assertRaisesRegex(MissingDataError, r"2 pairs have a missing value \(the first at index 1\)"):
            paired_sign_test(first, second, alternative="greater", missing="refuse", method="exact")
        dropped = paired_sign_test(first, second, alternative="greater", missing="drop", method="exact")
        self.assertEqual((dropped.successes, dropped.n, dropped.missing), (2, 3, 2))
        values: list[Any] = ["3", True, 1j, b"3", [3]]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, r"second\[1\] must be a real number or None, not"):
                    paired_sign_test([None, 2], [1, value], alternative="greater", missing="drop", method="exact")

    def test_exact_mcnemar_is_the_sign_test_on_the_discordant_pairs(self):
        result = mcnemar_exact(9, 2, alternative="two-sided", method="exact")
        self.assertEqual((result.test, result.successes, result.n), ("mcnemar", 9, 11))
        self.assertEqual(result.p_exact, sign(9, 11, "two-sided"))
        # One-sided, the direction matters: "greater" asks whether b outcomes are the likelier ones.
        for alternative in ("greater", "less"):
            with self.subTest(alternative=alternative):
                self.assertEqual(
                    mcnemar_exact(9, 2, alternative=alternative, method="exact").p_exact, sign(9, 11, alternative)
                )
        with self.assertRaisesRegex(EmptySampleError, "at least one discordant pair"):
            mcnemar_exact(0, 0, alternative="two-sided", method="exact")


class IntervalTest(unittest.TestCase):
    def test_an_empty_sample_has_no_interval(self):
        for method in (wilson, clopper_pearson):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(EmptySampleError, "n is 0"):
                    method(0, 0)
                with self.assertRaisesRegex(ValueError, "cannot exceed"):
                    method(5, 4)

    def test_wilson_takes_its_quantile_from_the_confidence_unless_given_one(self):
        for confidence in ("0.8", "0.9", "0.95", "0.99"):
            with self.subTest(confidence=confidence):
                z = NormalDist().inv_cdf(1 - (1 - float(Fraction(confidence))) / 2)
                by_level, by_z = wilson(7, 20, confidence=confidence), wilson(7, 20, z=z)
                self.assertEqual((by_level.low, by_level.high), (by_z.low, by_z.high))
                # The interval records the confidence its z implies, not the unrelated default.
                self.assertAlmostEqual(float(by_z.confidence), float(Fraction(confidence)), places=12)
        self.assertEqual(wilson(7, 20).confidence, Fraction(19, 20))
        self.assertNotEqual(wilson(7, 20).low, wilson(7, 20, z=1.0).low)

    def test_wilson_refuses_a_quantile_that_cannot_be_one_and_a_confidence_beside_it(self):
        for z in (-1.96, 0.0, float("nan"), float("inf"), 40.0):
            with self.subTest(z=z):
                with self.assertRaisesRegex(ValueError, "z must be a positive"):
                    wilson(3, 10, z=z)
        with self.assertRaisesRegex(ValueError, "confidence or z, not both"):
            wilson(3, 10, confidence="0.9", z=1.64)
        wrong: list[Any] = [True, "1.96", Fraction(49, 25), Decimal("1.96")]
        for z in wrong:
            with self.subTest(z=z):
                with self.assertRaisesRegex(TypeError, "z must be a float such as 1.96"):
                    wilson(3, 10, z=z)
        self.assertEqual(wilson(3, 10, z=2), wilson(3, 10, z=2.0))

    def test_clopper_pearson_bounds_meet_their_exact_tails_even_at_high_confidence(self):
        # At each bound the exact tail equals (1 - confidence) / 2: P(X >= k) at the lower, P(X <= k) at the upper.
        # Near 0 or 1 the exact bound may fall between two floats, so the crossing must lie within two floats of it.
        def steps(x: float, count: int, toward: float) -> float:
            for _ in range(count):
                x = math.nextafter(x, toward)
            return x

        for confidence in ("0.95", "0.999999", "0.9999999999", "0.99999999999999", "0.99999999999999999999"):
            tail = (1 - Fraction(confidence)) / 2
            slack = Fraction(1, 10**6)
            for k, n in ((1, 300), (5, 20), (0, 7), (13, 40), (299, 300)):
                with self.subTest(confidence=confidence, k=k, n=n):
                    interval = clopper_pearson(k, n, confidence=confidence)
                    if k > 0:
                        # P(X >= k | p) rises with p: below the bound it is under the tail, above it over.
                        below, above = steps(interval.low, 2, 0.0), steps(interval.low, 2, 1.0)
                        self.assertLessEqual(binom_tail(k, n, p=Fraction(below), tail="upper"), tail * (1 + slack))
                        self.assertGreaterEqual(binom_tail(k, n, p=Fraction(above), tail="upper"), tail * (1 - slack))
                    if k < n:
                        # P(X <= k | p) falls with p: below the bound it is over the tail, above it under.
                        below, above = steps(interval.high, 2, 0.0), steps(interval.high, 2, 1.0)
                        self.assertGreaterEqual(binom_tail(k, n, p=Fraction(below), tail="lower"), tail * (1 - slack))
                        self.assertLessEqual(binom_tail(k, n, p=Fraction(above), tail="lower"), tail * (1 + slack))

    def test_a_confidence_of_zero_or_one_is_refused(self):
        for confidence in ("0", "1"):
            for method in (wilson, clopper_pearson):
                with self.subTest(confidence=confidence, method=method.__name__):
                    with self.assertRaisesRegex(ValueError, r"confidence must lie in \(0, 1\)"):
                        method(3, 10, confidence=confidence)

    def test_the_bounds_are_closed_at_zero_and_n(self):
        for n in range(1, 60):
            for confidence in ("0.8", "0.9", "0.95", "0.99"):
                for method in (wilson, clopper_pearson):
                    with self.subTest(n=n, confidence=confidence, method=method.__name__):
                        self.assertEqual(method(0, n, confidence=confidence).low, 0.0)
                        self.assertEqual(method(n, n, confidence=confidence).high, 1.0)

    def test_clopper_pearson_covers_at_least_the_nominal_level_on_a_1001_point_grid(self):
        for confidence in ("0.9", "0.95"):
            for n in (1, 2, 3, 5, 10, 25, 50):
                bounds = [clopper_pearson(k, n, confidence=confidence) for k in range(n + 1)]
                for i in range(1001):
                    p = i / 1000
                    coverage = math.fsum(
                        math.comb(n, k) * p**k * (1 - p) ** (n - k)
                        for k, b in enumerate(bounds)
                        if b.low <= p <= b.high
                    )
                    if coverage < float(Fraction(confidence)) - 1e-12:
                        self.fail(f"coverage {coverage} < {confidence} at n={n}, p={p}")


class MultiplicityTest(unittest.TestCase):
    def test_holm_takes_the_running_maximum(self):
        # Sorted: 1/100 * 3, 3/100 * 2, 1/25 * 1 = 3/100, 6/100, 4/100; the last is raised to 6/100.
        self.assertEqual(holm(["1/100", "1/25", "3/100"]), [Fraction(3, 100), Fraction(3, 50), Fraction(3, 50)])
        self.assertEqual(holm(["1/2", "3/4"]), [1, 1])

    def test_benjamini_hochberg_takes_the_running_minimum_from_the_top(self):
        # Sorted: 1/100 * 3/1, 3/100 * 3/2, 1/25 * 3/3 = 3/100, 9/200, 4/100; the middle is lowered to 4/100.
        self.assertEqual(
            benjamini_hochberg(["1/100", "1/25", "3/100"]), [Fraction(3, 100), Fraction(1, 25), Fraction(1, 25)]
        )
        self.assertEqual(benjamini_hochberg(["9/10", "3/4"]), [Fraction(9, 10), Fraction(9, 10)])

    def test_results_and_exact_values_can_be_mixed_but_floats_cannot(self):
        result = sign_test(9, 1, ties=0, alternative="greater", method="exact")
        self.assertEqual(holm([result, "1/2"])[0], min(Fraction(1), 2 * result.p_exact))
        with self.assertRaises(TypeError):
            holm([0.01, 0.2])  # type: ignore[list-item]
        with self.assertRaisesRegex(ValueError, "no p-values"):
            holm([])

    def test_a_family_refuses_an_undeclared_member_and_an_incomplete_adjustment(self):
        family = Family("primary", ["speed", "accuracy"], correction="holm")
        family.add("speed", "1/100")
        with self.assertRaisesRegex(UndeclaredMemberError, "does not declare 'cost'"):
            family.add("cost", "1/1000")
        with self.assertRaisesRegex(IncompleteFamilyError, r"no result yet for \['accuracy'\]"):
            family.adjusted()
        with self.assertRaisesRegex(ValueError, "already has a result"):
            family.add("speed", "1/50")
        family.add("accuracy", "3/100")
        self.assertEqual(family.adjusted(), {"speed": Fraction(1, 50), "accuracy": Fraction(3, 100)})
        self.assertEqual(family.decide("0.025"), {"speed": True, "accuracy": False})
        # Between the raw p-values and the adjusted ones: the raw 1/100 would reject, the adjusted 1/50 does not.
        self.assertEqual(family.decide("0.015"), {"speed": False, "accuracy": False})
        # Three members, where Benjamini-Hochberg and Holm disagree (Holm would give 3/100, 3/50, 3/50).
        bh = Family("secondary", ["a", "b", "c"], correction="benjamini-hochberg")
        for member, p in zip("abc", ("1/100", "1/25", "3/100"), strict=True):
            bh.add(member, p)
        self.assertEqual(bh.adjusted(), {"a": Fraction(3, 100), "b": Fraction(1, 25), "c": Fraction(1, 25)})

    def test_a_family_is_declared_whole(self):
        cases = {
            "declares no members": lambda: Family("f", [], correction="holm"),
            "declares a member twice": lambda: Family("f", ["a", "a"], correction="holm"),
            "correction must be one of": lambda: Family("f", ["a"], correction="bonferroni"),
        }
        for message, call in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    call()


class PowerTest(unittest.TestCase):
    def test_power_counts_every_sequence_the_test_rejects(self):
        for n, p_alt, alternative in (
            (10, Fraction(4, 5), "greater"),
            (12, Fraction(1, 4), "less"),
            (11, Fraction(2, 3), "two-sided"),
        ):
            with self.subTest(n=n, alternative=alternative):
                rejected = sum(w for s, w in sequences(n, p_alt) if decide(sign(s, n, alternative), "0.05"))
                self.assertEqual(sign_test_power(n, p_alt=p_alt, alpha="0.05", alternative=alternative), rejected)

    def test_the_rejection_region_is_the_tests_own(self):
        self.assertEqual(rejection_region(10, p0="1/2", alpha="0.05", alternative="greater"), [9, 10])
        self.assertEqual(rejection_region(10, p0="1/2", alpha="0.05", alternative="two-sided"), [0, 1, 9, 10])
        self.assertEqual(rejection_region(0, p0="1/2", alpha="0.05", alternative="less"), [])
        # 4 of 4: the p-value is exactly 1/16, so at alpha = 1/16 the count is in the region, as decide says.
        self.assertEqual(rejection_region(4, p0="1/2", alpha="1/16", alternative="greater"), [4])
        self.assertEqual(sign_test_power(4, p_alt="1/2", alpha="1/16", alternative="greater"), Fraction(1, 16))
        self.assertEqual(
            rejection_region(20, p0="1/4", alpha="0.05", alternative="greater"),
            [k for k in range(21) if binom_tail(k, 20, p="1/4", tail="upper") <= Fraction(1, 20)],
        )
        with self.assertRaisesRegex(ValueError, "only at p0 = 1/2"):
            rejection_region(10, p0="1/4", alpha="0.05", alternative="two-sided")

    def test_the_power_at_the_null_is_the_size(self):
        self.assertEqual(
            binomial_power(30, p0="1/4", p_alt="1/4", alpha="0.05", alternative="greater"),
            sum(
                binom_tail(k, 30, p="1/4", tail="upper") - binom_tail(k + 1, 30, p="1/4", tail="upper")
                for k in rejection_region(30, p0="1/4", alpha="0.05", alternative="greater")
            ),
        )

    def test_the_minimum_detectable_effect_is_the_nearest_probability_reaching_the_power(self):
        for alternative, sign_of in (("greater", 1), ("two-sided", 1), ("less", -1)):
            with self.subTest(alternative=alternative):
                mde = sign_test_mde(30, alpha="0.05", power="0.8", alternative=alternative)
                assert mde is not None
                at = sign_test_power(30, p_alt=Fraction(mde), alpha="0.05", alternative=alternative)
                nearer = sign_test_power(
                    30, p_alt=Fraction(mde - sign_of * 1e-6), alpha="0.05", alternative=alternative
                )
                self.assertGreaterEqual(at, Fraction(4, 5))
                self.assertLess(nearer, Fraction(4, 5))
        self.assertIsNone(sign_test_mde(4, alpha="0.05", power="0.8", alternative="two-sided"))
        for power in ("0", "1"):
            with self.subTest(power=power):
                with self.assertRaisesRegex(ValueError, r"power must lie in \(0, 1\)"):
                    sign_test_mde(30, alpha="0.05", power=power, alternative="greater")
        self.assertIsNotNone(binomial_mde(40, p0="1/4", alpha="0.05", power="0.9", alternative="greater"))
        # A test that already reaches the power with no effect at all has no minimum detectable effect.
        with self.assertRaisesRegex(ValueError, "reaches power 1/10 with no effect"):
            binomial_mde(20, p0="1/2", alpha="1/2", power="1/10", alternative="greater")

    def test_the_minimum_detectable_effect_is_the_grid_point_nearest_p0_whose_exact_power_reaches_the_target(self):
        from onus.stats.power import GRID

        certain = 1 - Fraction(1, 10**400)  # so near 1 that a float cannot tell it from 1
        cases = [
            # Near power 1 a float power is off by more than the gap to the target.
            (30, "1/2", "greater", Fraction("0.99999999")),
            (50, "1/100", "greater", Fraction("0.999999999")),
            (50, "99/100", "less", Fraction("0.999999999")),
            (30, "1/2", "less", Fraction("0.99999999999999")),
            (119, "1/2", "two-sided", Fraction("0.9999999")),
            # The float search's guess falls short, or overshoots, of the exact crossing.
            (12, "1/3", "less", Fraction("0.99999999")),
            (33, "1/3", "greater", Fraction(1, 2)),
            # Only probability 1 (0 for "less") reaches the target.
            (5, "1/2", "greater", certain),
            (40, "1/3", "less", certain),
        ]
        for n, p0, alternative, target in cases:
            with self.subTest(n=n, p0=p0, alternative=alternative, target=target):
                mde = binomial_mde(n, p0=p0, alpha="0.05", power=target, alternative=alternative)
                assert mde is not None
                at = Fraction(mde)
                self.assertEqual(GRID % at.denominator, 0)
                self.assertTrue(0 <= at <= 1)
                self.assertGreaterEqual(
                    binomial_power(n, p0=p0, p_alt=at, alpha="0.05", alternative=alternative), target
                )
                nearer = at - Fraction(1 if alternative != "less" else -1, GRID)
                self.assertLess(binomial_power(n, p0=p0, p_alt=nearer, alpha="0.05", alternative=alternative), target)

    def test_the_exact_settling_finds_the_crossing_from_any_guess(self):
        from onus.stats.power import _settle

        top = 64
        for crossing in (1, 5, 37, 63, 64):
            for guess in sorted(
                {1, max(1, crossing - 9), max(1, crossing - 1), crossing, min(top, crossing + 1), 50, top}
            ):
                asked: list[int] = []

                def reaches(i: int, crossing: int = crossing, asked: list[int] = asked) -> bool:
                    asked.append(i)
                    return i >= crossing

                with self.subTest(crossing=crossing, guess=guess):
                    self.assertEqual(_settle(reaches, guess, top), crossing)
                    self.assertTrue(all(1 <= i <= top for i in asked), asked)
        with within(1.0):
            with self.assertRaisesRegex(ValueError, "no index up to 64 reaches"):
                _settle(lambda i: False, 3, top)

    def test_the_power_of_any_region_is_its_exact_probability(self):
        from onus.stats.power import _region_power

        p = Fraction(2, 7)
        for region in ([], [0], [9], [0, 1, 2], [7, 8, 9], [3, 4, 5], [0, 1, 5, 8, 9], list(range(10))):
            with self.subTest(region=region):
                self.assertEqual(_region_power(region, 9, p), sum((binom_pmf(k, 9, p=p) for k in region), Fraction(0)))

    def test_one_look_is_the_fixed_sample_size(self):
        for n in (1, 5, 20, 37):
            for alternative in ALTERNATIVES:
                with self.subTest(n=n, alternative=alternative):
                    self.assertEqual(
                        sequential_size([n], alpha="0.05", alternative=alternative),
                        sign_test_power(n, p_alt=HALF, alpha="0.05", alternative=alternative),
                    )

    def test_peeking_is_counted_once_per_sequence(self):
        # Brute force over all 2^12 sequences, reading at 6, 9, and 12 pairs.
        looks = [6, 9, 12]
        for alternative in ALTERNATIVES:
            regions = {n: set(rejection_region(n, p0="1/2", alpha="1/10", alternative=alternative)) for n in looks}
            count = sum(any(sum(seq[:n]) in regions[n] for n in looks) for seq in product((0, 1), repeat=12))
            with self.subTest(alternative=alternative):
                self.assertEqual(sequential_size(looks, alpha="1/10", alternative=alternative), Fraction(count, 2**12))
        for bad in ([], [5, 5], [5, 3], [0, 4]):
            with self.subTest(looks=bad):
                with self.assertRaisesRegex(ValueError, "strictly increasing positive"):
                    sequential_size(bad, alpha="0.05", alternative="greater")


class ApiRuleTest(unittest.TestCase):
    """alternative, method, and missing are keyword-only with no default, on every public function."""

    def test_every_call_states_its_sidedness_method_and_missing_policy(self):
        checked = 0
        for name in onus.stats.__all__:
            target = getattr(onus.stats, name)
            # Functions, and the one class a caller configures; result types only carry these as fields.
            if not (inspect.isfunction(target) or target is Family):
                continue
            for parameter in inspect.signature(target).parameters.values():
                if parameter.name in ("alternative", "method", "missing", "correction"):
                    checked += 1
                    with self.subTest(function=name, parameter=parameter.name):
                        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                        self.assertIs(parameter.default, inspect.Parameter.empty)
        self.assertGreaterEqual(checked, 16, "the rule must not pass by finding nothing to check")


def close(a: float, b: float, tolerance: float) -> bool:
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance * 1e-3)


class ReferenceTest(unittest.TestCase):
    """onus.stats against scipy's and statsmodels' answers, committed by `make reference`."""

    fixture: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((REFERENCE / "stats_reference.json").read_text(encoding="utf-8"))

    def test_the_fixture_was_written_by_the_current_script(self):
        script = (ROOT / "tools" / "reference" / "make_reference.py").read_bytes()
        self.assertEqual(
            self.fixture["header"]["script_sha256"], hashlib.sha256(script).hexdigest(), "run make reference"
        )

    def test_the_fixture_holds_every_case_the_script_lists(self):
        # Case by case, so a section emptied or cut short cannot pass as a smaller reference.
        fixture = self.fixture
        self.assertEqual(
            [(c["k"], c["n"], c["p"], c["alternative"]) for c in fixture["binomial"]], list(make_reference.BINOMIAL)
        )
        self.assertEqual(
            [(c["k"], c["n"], c["confidence"]) for c in fixture["intervals"]], list(make_reference.INTERVALS)
        )
        self.assertEqual([c["p_values"] for c in fixture["families"]], make_reference.FAMILIES)

    def test_the_fixture_came_from_the_versions_the_makefile_pins(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        for name, variable in (("scipy", "SCIPY"), ("statsmodels", "STATSMODELS")):
            with self.subTest(library=name):
                pin = re.search(rf"(?m)^{variable} := {name}==(\S+)$", makefile)
                assert pin is not None, variable
                self.assertEqual(self.fixture["header"][name], pin.group(1), "run make reference")

    def test_binomial_p_values_match(self):
        for case in self.fixture["binomial"]:
            with self.subTest(**case):
                ours = binomial_test(case["k"], case["n"], p=case["p"], alternative=case["alternative"], method="exact")
                self.assertTrue(close(ours.p_value, case["p_value"], 1e-12), (ours.p_value, case["p_value"]))

    def test_intervals_match(self):
        for case in self.fixture["intervals"]:
            for method, function, tolerance in (("wilson", wilson, 1e-12), ("clopper-pearson", clopper_pearson, 1e-9)):
                with self.subTest(k=case["k"], n=case["n"], confidence=case["confidence"], method=method):
                    ours = function(case["k"], case["n"], confidence=case["confidence"])
                    self.assertTrue(close(ours.low, case[method][0], tolerance), (ours.low, case[method][0]))
                    self.assertTrue(close(ours.high, case[method][1], tolerance), (ours.high, case[method][1]))

    def test_adjusted_p_values_match(self):
        for case in self.fixture["families"]:
            for name, function in (("holm", holm), ("benjamini-hochberg", benjamini_hochberg)):
                with self.subTest(family=case["p_values"], method=name):
                    ours = [float(v) for v in function(case["p_values"])]
                    self.assertTrue(
                        all(close(a, b, 1e-12) for a, b in zip(ours, case[name], strict=True)), (ours, case[name])
                    )


class SimulationTest(unittest.TestCase):
    """The exact power and peeking size against simulated rejection rates, committed by `make sims`."""

    def test_every_simulated_rate_lies_within_three_standard_errors_of_the_exact_one(self):
        sims = json.loads((REFERENCE / "sims.json").read_text(encoding="utf-8"))
        script = (ROOT / "tools" / "sims" / "ht_sims.py").read_bytes()
        self.assertEqual(sims["header"]["script_sha256"], hashlib.sha256(script).hexdigest(), "run make sims")
        self.assertEqual(len(sims["cases"]), len(ht_sims.CASES))
        for case in sims["cases"]:
            with self.subTest(case=case["name"]):
                if len(case["looks"]) == 1:
                    exact = sign_test_power(
                        case["looks"][0], p_alt=case["p_win"], alpha=case["alpha"], alternative=case["alternative"]
                    )
                else:
                    self.assertEqual(case["p_win"], "1/2", "a peeking case is simulated under the null")
                    exact = sequential_size(case["looks"], alpha=case["alpha"], alternative=case["alternative"])
                se = math.sqrt(float(exact) * (1 - float(exact)) / case["reps"])
                self.assertLessEqual(abs(case["rate"] - float(exact)), 3 * se, (case["rate"], float(exact)))


class ScriptTest(unittest.TestCase):
    """The two scripts that write the committed files, run here with stand-ins so they stay covered."""

    def test_the_reference_script_writes_a_header_and_every_case(self):
        def module(name: str, **attributes: object) -> types.ModuleType:
            fake = types.ModuleType(name)
            fake.__dict__.update(attributes)
            return fake

        modules = {
            "scipy": module("scipy", __version__="0.0-fake"),
            "scipy.stats": module(
                "scipy.stats", binomtest=lambda k, n, p, alternative: types.SimpleNamespace(pvalue=0.5)
            ),
            "statsmodels": module("statsmodels", __version__="0.0-fake"),
            "statsmodels.stats.proportion": module(
                "statsmodels.stats.proportion", proportion_confint=lambda k, n, alpha, method: (0.25, 0.75)
            ),
            "statsmodels.stats.multitest": module(
                "statsmodels.stats.multitest", multipletests=lambda ps, method: (None, [0.5] * len(ps))
            ),
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules):
            out = Path(tmp) / "reference.json"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(make_reference.main([str(out)]), 0)
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["header"]["scipy"], "0.0-fake")
        self.assertEqual(len(written["binomial"]), len(make_reference.BINOMIAL))
        self.assertEqual(written["intervals"][0]["clopper-pearson"], [0.25, 0.75])
        self.assertEqual(len(written["families"]), len(make_reference.FAMILIES))

    def test_the_simulation_script_writes_a_rate_for_every_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sims.json"
            with redirect_stderr(io.StringIO()):
                self.assertEqual(ht_sims.main([str(out), "--reps", "20"]), 0)
            written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([case["name"] for case in written["cases"]], [case[0] for case in ht_sims.CASES])
        self.assertTrue(all(0 <= case["rate"] <= 1 and case["reps"] == 20 for case in written["cases"]))


if __name__ == "__main__":
    unittest.main()
