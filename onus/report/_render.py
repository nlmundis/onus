"""The sentence that quotes a pre-registered verdict, and the one that quotes an exploratory result."""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, ROUND_UP, Context, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import onus
from onus.prereg import (
    Evaluation,
    Horizon,
    Hypothesis,
    HypothesisResult,
    PreregError,
    ReadReceipt,
    Rule,
    evaluate,
)
from onus.prereg._evaluate import CLOSED_EVERYWHERE
from onus.report._receipts import bound_read, re_read_kind
from onus.stats import TestResult, binomial_mde, binomial_power, rejection_region

# The power a minimum detectable effect is stated at. Frozen once released: documents quote the sentences.
MDE_POWER = Fraction(4, 5)
CORRECTION_NAMES = {"holm": "Holm", "benjamini-hochberg": "Benjamini-Hochberg"}
TEST_NAMES = {"sign": "sign test", "binomial": "binomial test", "mcnemar": "McNemar test"}
_COUNTS = {
    "sign": "wins {k}, losses {rest}, n = {n} discordant pairs",
    "binomial": "successes {k}, failures {rest}, n = {n} trials",
    "mcnemar": "b = {k}, c = {rest}, n = {n} discordant pairs",
}
P_DIGITS = 4
MDE_DIGITS = 4


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


def mde_text(null: Fraction, mde: float) -> str:
    """Return the MDE ``mde`` as the null plus or minus its gap: "0.5 + 0.4635", or "0.999 - 0.001844" below it.

    The null is exact; the gap, the MDE's distance from it, has four significant digits, rounded up from its
    exact value. So the printed effect lies no nearer the null than the MDE and still reaches the power, since
    power is monotone in the effect; and the gap keeps its precision wherever the null sits, even at p0 = 0.999,
    where the whole gap is below 0.001.

    Where that rounded gap would print an effect outside [0, 1], as when the MDE lies within one rounding step of
    1 (or of 0, below the null), the gap is printed exactly instead, as the null is: "1/3 + 2/3". There no gap of
    four significant digits both reaches the power and names a probability, so the digits give way (E7).
    """
    gap = Fraction(mde) - null
    digits = Context(prec=MDE_DIGITS, rounding=ROUND_UP).divide(Decimal(abs(gap.numerator)), Decimal(gap.denominator))
    effect = null + Fraction(digits) if gap > 0 else null - Fraction(digits)
    text = f"{digits:f}" if 0 <= effect <= 1 else exact_text(abs(gap))
    return f"{exact_text(null)} {'+' if gap > 0 else '-'} {text}"


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


def _members(rule: Rule, hypothesis: Hypothesis) -> int:
    """Return m, the number of hypotheses in ``hypothesis``'s family, itself included."""
    return sum(1 for other in rule.hypotheses if other.family == hypothesis.family)


def _p_values(rule: Rule, hypothesis: Hypothesis, outcome: HypothesisResult) -> str:
    """Return the p-value clause: the exact p, the family's adjusted p with its correction and m, and alpha."""
    correction = CORRECTION_NAMES[rule.families[hypothesis.family]]
    return (
        f"p = {significant_text(outcome.result.p_exact)}, {correction}-adjusted p = "
        f'{significant_text(outcome.adjusted_p)} in family "{hypothesis.family}" (m = {_members(rule, hypothesis)}) at '
        f"α = {exact_text(outcome.alpha)}"
    )


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
    return f"{head}: {what} probability {mde_text(result.null, mde)}"


def _early(horizon: Horizon, read_at: datetime) -> str:
    """Return an early read's verdict: that it was read early, when, and when its days window closed everywhere."""
    assert horizon.end is not None  # only a days horizon's read is ever early
    closed = datetime.combine(horizon.end, CLOSED_EVERYWHERE, tzinfo=UTC)
    return f"read early (read at {read_at.isoformat()}; window closed at {closed.isoformat()})"


# How a re-read's clause opens, by what the read differed in from those before it (``re_read_kind``).
_RE_READ = {"data": "re-read on different data", "record": "re-read after a read under a different record"}


def _re_read(kind: str | None, first: str | None, *, early: bool) -> list[str]:
    """Return the clause naming the ``first`` read a re-read superseded; none for a read that superseded none.

    ``kind`` is ``re_read_kind``'s. An early read carries the clause only for a re-read on different data (E12): one
    of the same data after a read under a different record was sealed because a label differs, so there the clause
    would say so.
    """
    if kind is None or (early and kind != "data"):
        return []
    assert first is not None  # a read that superseded another names it
    return [f"{_RE_READ[kind]}; first read {first[:12]}"]


def _decided(
    rule: Rule, hypothesis: Hypothesis, outcome: HypothesisResult, kind: str | None, first: str | None
) -> list[str]:
    """Return a decided read's clauses: verdict, re-read if any, test and counts, p-values, MDE if not met, warnings."""
    clauses = [f"{hypothesis.name}: {outcome.label}", *_re_read(kind, first, early=False)]
    clauses += [describe(outcome.result), _p_values(rule, hypothesis, outcome)]
    if not outcome.met:
        clauses.append(_mde(hypothesis, outcome.result, _members(rule, hypothesis)))
    clauses.append(_warnings(outcome.result))
    return clauses


def _sentence(
    rule: Rule,
    evaluation: Evaluation,
    index: int,
    *,
    read_early_at: datetime | None,
    kind: str | None,
    first: str | None,
) -> str:
    """Return the sentence for hypothesis ``index``.

    ``read_early_at`` is the read time of an early read, else None; ``kind`` is ``re_read_kind``'s, and ``first`` the
    line sha256 of the first read a re-read superseded.
    """
    hypothesis, outcome = rule.hypotheses[index], evaluation.hypotheses[index]
    if read_early_at is not None:
        # E8: an early read reveals nothing about the result, so it states no verdict, count, p-value, α, family, MDE,
        # test, or warning; only when it was read, when the window closed everywhere, and the provenance. E12: that a
        # read was a re-read on different data is its history, not its result, so an early re-read says that too.
        clauses = [f"{hypothesis.name}: {_early(rule.horizon, read_early_at)}"]
        clauses += _re_read(kind, first, early=True)
    else:
        clauses = _decided(rule, hypothesis, outcome, kind, first)
    clauses.append(f"prereg {rule.id}, data sha256 {evaluation.data_sha256[:12]} over {evaluation.n} units")
    clauses.append(f"onus {onus.__version__}")
    sentence = "; ".join(clauses) + "."
    # The sentence is one line. load refuses a name, family, or file stem holding a line break (E10); this is the
    # second check, so no sentence that spans lines is ever returned.
    if sentence.splitlines() != [sentence]:
        raise PreregError(
            f"{hypothesis.name!r} of {rule.id!r} cannot be quoted on one line: its name, its family, or the record's "
            "file stem holds a line break"
        )
    return sentence


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
    evaluation: its prereg, experiment, data_sha256, n, and labels, the receipt's read time, and the early flag
    that time gives under the rule's horizon. Every number in the sentence comes from ``data``, and whether the
    read was early from its recorded time, so a hand-built receipt, a hand-edited evaluation, or a hand-edited
    early flag cannot be rendered.

    The sentence is one line. A read that is not early carries its verdict ("met" or "not met"), the test and its
    counts, the exact p-value and the family's adjusted one, the minimum detectable effect when it is not met, and
    any warnings. A read recorded before its days window closed everywhere reveals nothing about the result: in
    their place it carries only "read early (read at <the read time>; window closed at <the window's end day, 12:00
    UTC>)". A read that superseded another says so just after its verdict or its "read early (...)": "re-read on
    different data; first read <hash>" when an earlier read of the experiment, or of a record with the same file
    stem, used other data, and otherwise, on a read that is not early, "re-read after a read under a different
    record; first read <hash>", since there one of those earlier reads gave the same data another label, under
    another record; the first read named may itself be of this record. An early read says nothing in that second
    case, where saying it would give away that a label changed. Every sentence ends with the prereg id, a data hash,
    the number of units used, and the onus version. It reads no clock: the read time it prints is the one the reads
    file records. p-values have four significant digits; alphas are exact; the MDE is the null plus a gap of four
    significant digits, rounded away from the null, or the exact gap where those digits would print an effect
    outside [0, 1].

    Raises:
        TypeError: ``receipt`` is not a ReadReceipt.
        PreregError: ``rule`` has no hypothesis ``name``; ``evaluate`` refuses; the receipt does not bind this
            evaluation, as above; or the sentence would span lines, since the hypothesis's name, its family, or
            the record's file stem holds a line break, which load refuses first.
    """
    names = [hypothesis.name for hypothesis in rule.hypotheses]
    if name not in names:
        raise PreregError(f"{rule.id!r} has no hypothesis named {name!r}; it has {names}")
    evaluation = evaluate(rule, data, as_of=as_of)
    read, earlier = bound_read(evaluation, horizon=rule.horizon, receipt=receipt, reads_path=reads_path)
    return _sentence(
        rule,
        evaluation,
        names.index(name),
        read_early_at=read.at if read.early else None,
        kind=re_read_kind(read, earlier),
        first=read.supersedes,
    )


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
