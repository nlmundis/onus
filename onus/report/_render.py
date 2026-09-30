"""The sentence that quotes a pre-registered verdict, and the one that quotes an exploratory result."""

import math
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import onus
from onus.prereg import Evaluation, Hypothesis, HypothesisResult, PreregError, ReadReceipt, Rule, evaluate
from onus.report._receipts import bound_read
from onus.stats import TestResult, binomial_mde, binomial_power, rejection_region

# The power a minimum detectable effect is stated at. Frozen once released: assert_quoted pins the sentences.
MDE_POWER = Fraction(4, 5)
CORRECTION_NAMES = {"holm": "Holm", "benjamini-hochberg": "Benjamini-Hochberg"}
TEST_NAMES = {"sign": "sign test", "binomial": "binomial test", "mcnemar": "McNemar test"}
_COUNTS = {
    "sign": "wins {k}, losses {rest}, n = {n} discordant pairs",
    "binomial": "successes {k}, failures {rest}, n = {n} trials",
    "mcnemar": "b = {k}, c = {rest}, n = {n} discordant pairs",
}
P_DIGITS = 4
MDE_PLACES = 4


def exact_text(value: Fraction) -> str:
    """Return the non-negative ``value`` exactly: as a decimal when it has a finite one ("0.05"), else as "a/b"."""
    rest, places = value.denominator, 0
    for prime in (2, 5):
        count = 0
        while rest % prime == 0:
            rest, count = rest // prime, count + 1
        places = max(places, count)
    if rest != 1:
        return f"{value.numerator}/{value.denominator}"
    if places == 0:
        return str(value.numerator)
    digits = str(value.numerator * 10**places // value.denominator).rjust(places + 1, "0")
    return f"{digits[:-places]}.{digits[-places:]}"


def significant_text(value: Fraction) -> str:
    """Return ``value`` to four significant digits, rounded half to even from the exact fraction.

    An exact decimal with fewer digits keeps its own ("0.375"); a rounded one keeps all four ("0.05000").
    """
    context = Context(prec=P_DIGITS, rounding=ROUND_HALF_EVEN)
    return str(context.divide(Decimal(value.numerator), Decimal(value.denominator)))


def away_text(value: float, *, upward: bool) -> str:
    """Return ``value`` to four decimal places, rounded up when ``upward`` and down otherwise, from its exact value.

    An MDE is rounded away from the null, so the effect printed still reaches the power: power is monotone in
    the effect.
    """
    scaled = Fraction(value) * 10**MDE_PLACES
    step = math.ceil(scaled) if upward else math.floor(scaled)
    return f"{step // 10**MDE_PLACES}.{step % 10**MDE_PLACES:0{MDE_PLACES}d}"


def describe(result: TestResult) -> str:
    """Return a test result's sidedness, test, method, null, counts, ties, and missing values, as one clause.

    Raises:
        ValueError: ``result`` names a test onus.report does not know how to count.
    """
    if result.test not in TEST_NAMES:
        raise ValueError(f"onus.report cannot describe the test {result.test!r}; it knows {sorted(TEST_NAMES)}")
    side = "two-sided" if result.alternative == "two-sided" else f"one-sided ({result.alternative})"
    counts = _COUNTS[result.test].format(k=result.successes, rest=result.n - result.successes, n=result.n)
    return (
        f"{side} {TEST_NAMES[result.test]}, method {result.method}, null {exact_text(result.null)}: {counts}; "
        f"ties {result.ties}, missing {result.missing}"
    )


def _warnings(result: TestResult) -> str:
    return "; ".join(f"warning: {warning}" for warning in result.warnings) or "no warnings"


def _mde(hypothesis: Hypothesis, result: TestResult, m: int) -> str:
    """Return the minimum detectable effect clause: at MDE_POWER, and at alpha/m, a Bonferroni bound on the family.

    With exact fractions, a raw p-value at or below alpha/m is met under Holm or Benjamini-Hochberg whatever the
    family's other members show, so this is a floor on the power; it overstates the MDE, loosely for large
    families and for Benjamini-Hochberg.
    """
    n = result.n  # the test's non-tied n, not the units used, so a sign test's MDE is conditional on its ties
    level = hypothesis.alpha / m
    power = exact_text(MDE_POWER * 100)
    ties = " (conditional on the observed ties)" if result.test == "sign" else ""
    unit = "trials" if result.test == "binomial" else "discordant pairs"
    head = (
        f"MDE at {power}% power, at n = {n} {unit}{ties} and α/m = {exact_text(hypothesis.alpha)}/{m} = "
        f"{exact_text(level)} (a Bonferroni bound)"
    )
    # The level is α/m, and is named so: the sentence's α is the hypothesis's, at which an outcome here may be met.
    if not rejection_region(n, p0=result.null, alpha=level, alternative=result.alternative):
        return f"{head}: none, since no outcome at this n can reach significance at level α/m = {exact_text(level)}"
    if binomial_power(n, p0=result.null, p_alt=result.null, alpha=level, alternative=result.alternative) >= MDE_POWER:
        return f"{head}: no MDE exists, since at this level the test has {power}% power with no effect at all"
    mde = binomial_mde(n, p0=result.null, alpha=level, power=MDE_POWER, alternative=result.alternative)
    assert mde is not None  # the rejection region is not empty
    what = "win" if result.test == "sign" else "success"
    return f"{head}: {what} probability {away_text(mde, upward=result.alternative != 'less')}"


def _sentence(rule: Rule, evaluation: Evaluation, index: int, early: bool, supersedes: str | None) -> str:
    hypothesis, outcome = rule.hypotheses[index], evaluation.hypotheses[index]
    result = outcome.result
    m = sum(1 for other in rule.hypotheses if other.family == hypothesis.family)
    verdict = "read early" if early else outcome.label
    if supersedes is not None:
        verdict += f"; re-read on different data; first read {supersedes[:12]}"
    correction = CORRECTION_NAMES[rule.families[hypothesis.family]]
    clauses = [
        f"{hypothesis.name}: {verdict}",
        describe(result),
        f"p = {significant_text(result.p_exact)}, {correction}-adjusted p = {significant_text(outcome.adjusted_p)} "
        f'in family "{hypothesis.family}" (m = {m}) at α = {exact_text(outcome.alpha)}',
    ]
    if not outcome.met:
        clauses.append(_mde(hypothesis, result, m))
    clauses.append(_warnings(result))
    clauses.append(f"prereg {rule.id}, data sha256 {evaluation.data_sha256[:12]} over {evaluation.n} units")
    clauses.append(f"onus {onus.__version__}")
    return "; ".join(clauses) + "."


def render(
    rule: Rule,
    data: Sequence[Mapping[str, Any]],
    name: str,
    *,
    receipt: ReadReceipt,
    reads_path: str | Path,
    as_of: date | None = None,
) -> str:
    """Return the sentence that quotes hypothesis ``name``'s verdict under ``rule``, re-derived from ``data``.

    ``render`` runs ``evaluate`` itself, then requires that ``reads_path``, the file the receipt names once both
    are resolved, holds the line whose sha256 is ``receipt.line_sha256``, and that the line records this
    evaluation: its prereg, experiment, data_sha256, n, and labels, and the receipt's read time. Every number in
    the sentence comes from ``data``, so a hand-built receipt or a hand-edited evaluation cannot be rendered.

    The sentence carries the verdict ("met" or "not met"; "read early" in its place when the read was recorded
    before a days window closed everywhere; and "re-read on different data; first read <hash>" when the read
    superseded another), the test and its counts, the exact p-value and the family's adjusted one, the minimum
    detectable effect whenever the verdict is not met, and the prereg id, a data hash, and the onus version. It
    reads no clock. p-values have four significant digits; alphas are exact.

    Raises:
        TypeError: ``receipt`` is not a ReadReceipt.
        PreregError: ``rule`` has no hypothesis ``name``; ``evaluate`` refuses; or the receipt does not bind this
            evaluation, as above.
    """
    names = [hypothesis.name for hypothesis in rule.hypotheses]
    if name not in names:
        raise PreregError(f"{rule.id!r} has no hypothesis named {name!r}; it has {names}")
    evaluation = evaluate(rule, data, as_of=as_of)
    read = bound_read(evaluation, receipt=receipt, reads_path=reads_path)
    return _sentence(rule, evaluation, names.index(name), read.early, read.supersedes)


def render_exploratory(result: TestResult) -> str:
    """Return the sentence that quotes a test result no rule registered, starting "Exploratory:".

    It carries the sidedness, the null, the counts, ties, missing values, the method, any warnings, the p-value,
    and the onus version; with no alpha, it states no verdict, no significance, and no minimum detectable effect.

    Raises:
        TypeError: ``result`` is not a TestResult, including a pre-registered hypothesis's result.
        ValueError: ``result`` names a test onus.report does not know how to count.
    """
    if isinstance(result, HypothesisResult):
        raise TypeError(f"{result.name!r} is pre-registered: quote it with render(), which needs its read's receipt")
    if not isinstance(result, TestResult):
        raise TypeError(f"render_exploratory takes a TestResult, not {type(result).__name__}")
    return (
        f"Exploratory: {describe(result)}; p = {significant_text(result.p_exact)}; {_warnings(result)}; "
        f"onus {onus.__version__}."
    )
