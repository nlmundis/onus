"""Properties onus.stats must have for every input, checked with Hypothesis under a deterministic profile.

The profile is the library's gate profile: derandomized, no example database, no deadline, 200 examples.
"""

import unittest
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from onus.stats import (
    benjamini_hochberg,
    binom_tail,
    clopper_pearson,
    decide,
    holm,
    sequential_size,
    sign_test,
    sign_test_power,
    wilson,
)

GATE = settings(derandomize=True, database=None, deadline=None, max_examples=200)
ALTERNATIVES = st.sampled_from(("two-sided", "greater", "less"))
probabilities = st.builds(Fraction, st.integers(1, 99), st.just(100))


@st.composite
def counts(draw: st.DrawFn, max_n: int = 60) -> tuple[int, int]:
    n = draw(st.integers(1, max_n))
    return draw(st.integers(0, n)), n


class TailProperties(unittest.TestCase):
    @GATE
    @given(counts(), probabilities)
    def test_the_upper_and_lower_tails_are_complements(self, kn, p):
        k, n = kn
        if k >= 1:
            self.assertEqual(binom_tail(k, n, p=p, tail="upper") + binom_tail(k - 1, n, p=p, tail="lower"), 1)

    @GATE
    @given(counts())
    def test_two_sided_is_twice_the_smaller_tail_capped_at_one(self, kn):
        k, n = kn
        tails = (binom_tail(k, n, p="1/2", tail="upper"), binom_tail(k, n, p="1/2", tail="lower"))
        self.assertEqual(
            sign_test(k, n - k, ties=0, alternative="two-sided", method="exact").p_exact,
            min(Fraction(1), 2 * min(tails)),
        )


class SignTestProperties(unittest.TestCase):
    @GATE
    @given(counts(), st.integers(0, 5))
    def test_swapping_wins_and_losses_swaps_the_sides(self, kn, ties):
        wins, n = kn
        losses = n - wins
        for side, mirror in (("greater", "less"), ("less", "greater"), ("two-sided", "two-sided")):
            self.assertEqual(
                sign_test(wins, losses, ties=ties, alternative=side, method="exact").p_exact,
                sign_test(losses, wins, ties=ties, alternative=mirror, method="exact").p_exact,
            )

    @GATE
    @given(counts())
    def test_one_more_win_never_weakens_the_evidence_for_greater(self, kn):
        wins, n = kn
        if wins < n:
            fewer = sign_test(wins, n - wins, ties=0, alternative="greater", method="exact").p_exact
            more = sign_test(wins + 1, n - wins - 1, ties=0, alternative="greater", method="exact").p_exact
            self.assertLessEqual(more, fewer)


class IntervalProperties(unittest.TestCase):
    @GATE
    @given(counts(max_n=200), st.sampled_from(("0.8", "0.9", "0.95", "0.99")))
    def test_each_interval_contains_the_observed_proportion(self, kn, confidence):
        k, n = kn
        for interval in (wilson(k, n, confidence=confidence), clopper_pearson(k, n, confidence=confidence)):
            self.assertLessEqual(interval.low, k / n + 1e-12)
            self.assertGreaterEqual(interval.high, k / n - 1e-12)

    @GATE
    @given(counts(max_n=200))
    def test_failures_mirror_successes(self, kn):
        k, n = kn
        for method in (wilson, clopper_pearson):
            ours, mirror = method(k, n), method(n - k, n)
            self.assertAlmostEqual(ours.low, 1 - mirror.high, places=9)
            self.assertAlmostEqual(ours.high, 1 - mirror.low, places=9)


class MultiplicityProperties(unittest.TestCase):
    @GATE
    @given(st.lists(st.builds(Fraction, st.integers(0, 1000), st.just(1000)), min_size=1, max_size=12))
    def test_bonferroni_rejections_lie_within_holms_and_holms_within_bhs(self, ps):
        m = len(ps)
        bonferroni = {i for i, p in enumerate(ps) if decide(min(Fraction(1), m * p))}
        holms = {i for i, p in enumerate(holm(ps)) if decide(p)}
        bhs = {i for i, p in enumerate(benjamini_hochberg(ps)) if decide(p)}
        self.assertLessEqual(bonferroni, holms)
        self.assertLessEqual(holms, bhs)


class PowerProperties(unittest.TestCase):
    @GATE
    @given(st.integers(1, 60), probabilities, probabilities)
    def test_power_grows_with_the_effect(self, n, a, b):
        low, high = sorted((a, b))
        self.assertLessEqual(
            sign_test_power(n, p_alt=low, alpha="0.05", alternative="greater"),
            sign_test_power(n, p_alt=high, alpha="0.05", alternative="greater"),
        )

    @GATE
    @given(st.integers(1, 60), probabilities, ALTERNATIVES)
    def test_power_grows_with_alpha(self, n, p, alternative):
        self.assertLessEqual(
            sign_test_power(n, p_alt=p, alpha="0.01", alternative=alternative),
            sign_test_power(n, p_alt=p, alpha="0.05", alternative=alternative),
        )

    @GATE
    @given(st.integers(1, 80), ALTERNATIVES)
    def test_one_look_is_the_fixed_size(self, n, alternative):
        self.assertEqual(
            sequential_size([n], alpha="0.05", alternative=alternative),
            sign_test_power(n, p_alt="1/2", alpha="0.05", alternative=alternative),
        )


if __name__ == "__main__":
    unittest.main()
