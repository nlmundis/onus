"""onus.report: a verdict rendered only against its recorded read, exploratory results, and exact quotes."""

import contextlib
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sys
import time
import unittest
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any
from unittest import mock

import onus
from onus.prereg import PreregError, ReadReceipt, Rule, evaluate, load, record_read
from onus.report import MDE_POWER, assert_quoted, receipt_from_line, render, render_exploratory
from onus.report._quote import CLOSE, OPEN
from onus.report._render import exact_text, mde_text, significant_text
from onus.stats import (
    TestResult,
    binomial_mde,
    binomial_power,
    binomial_test,
    mcnemar_exact,
    paired_sign_test,
    sign_test,
    sign_test_power,
)
from tests.test_prereg import Folder, at, days_record, days_sample, record, sample, sample_b, unit

VERSION = onus.__version__
# The wall clocks: datetime's and date's methods that read the time now, and the time module's functions that do.
DATE_CLOCKS = {"now", "utcnow", "today"}
TIME_CLOCKS = {"time", "time_ns", "localtime", "gmtime", "ctime", "asctime", "strftime", "clock_gettime"}


@contextlib.contextmanager
def clock_reads() -> Iterator[list[str]]:
    """Record every wall-clock read this thread makes while the block runs, through whatever name it is called.

    A profile function sees each call Python code makes into C, so a clock read through ``datetime.now``, a module
    imported under another name, or ``time.time`` is seen wherever it is made, onus's own ``_now`` included.
    """
    seen: list[str] = []

    def profile(frame: object, event: str, arg: object) -> None:
        owner, name = getattr(arg, "__self__", None), getattr(arg, "__name__", "")
        dated = isinstance(owner, type) and issubclass(owner, date) and name in DATE_CLOCKS
        if event == "c_call" and (dated or (owner is time and name in TIME_CLOCKS)):
            seen.append(f"{getattr(owner, '__name__', owner)}.{name}")

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        yield seen
    finally:
        sys.setprofile(previous)


def mde_sample(faster: list[str]) -> list[dict[str, Any]]:
    """Twelve units whose "faster" outcomes are given; "clearer" and "completes" always win and succeed."""
    return [unit(f"q{i}", i, outcome, "win", "success") for i, outcome in enumerate(faster, start=1)]


def renamed(names: dict[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """record() and sample() with hypotheses renamed, each old name to its new one, in the record and the outcomes."""
    hypotheses = [{**h, "name": names.get(h["name"], h["name"])} for h in record()["hypotheses"]]
    data = [{**u, "outcomes": {names.get(k, k): v for k, v in u["outcomes"].items()}} for u in sample()]
    return record(hypotheses=hypotheses), data


def loosened(content: dict[str, Any]) -> dict[str, Any]:
    """``content`` with its primary family read at alpha 0.5, under which one more of its hypotheses is met."""
    for hypothesis in content["hypotheses"]:
        if hypothesis.get("family") == "primary":
            hypothesis["alpha"] = "0.5"
    return content


class Reads(Folder):
    """A folder with a record and a reads file, and a way to record a read in it."""

    def setUp(self):
        super().setUp()
        self.reads = self.folder / "reads.jsonl"

    def rule(self, content: dict[str, Any] | None = None, name: str = "layout.json") -> Rule:
        return load(self.write(record() if content is None else content, name=name))

    def read(
        self,
        rule: Rule,
        data: list[dict[str, Any]],
        *,
        as_of: date | None = None,
        supersedes: str | None = None,
        reason: str | None = None,
    ) -> ReadReceipt:
        evaluation = evaluate(rule, data, as_of=as_of)
        return record_read(rule, evaluation, reads_path=self.reads, supersedes=supersedes, reason=reason)


class RenderTest(Reads):
    """render re-derives the verdict from the data and renders it only against the read its receipt names."""

    def test_each_hypothesis_is_quoted_in_one_sentence(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        tail = f"prereg {rule.id}, data sha256 {receipt.data_sha256[:12]} over 6 units; onus {VERSION}."
        expected = {
            "faster": (
                "faster: met; one-sided (greater) sign test, method exact, null 0.5: wins 6, losses 0, n = 6 discordant"
                ' pairs; ties 0, missing 0; p = 0.01562, Holm-adjusted p = 0.03125 in family "primary" (m = 2) at α ='
                f" 0.05; no warnings; {tail}"
            ),
            "clearer": (
                "clearer: not met; two-sided sign test, method exact, null 0.5: wins 4, losses 1, n = 5 discordant"
                ' pairs; ties 1, missing 0; p = 0.375, Holm-adjusted p = 0.375 in family "primary" (m = 2) at α ='
                " 0.05; MDE at 80% power, at n = 5 discordant pairs (conditional on the observed ties) and α/m ="
                " 0.05/2 = 0.025 (a Bonferroni bound): none, since no outcome at this n can reach significance at"
                f" level α/m = 0.025; no warnings; {tail}"
            ),
            "completes": (
                "completes: not met; one-sided (greater) binomial test, method exact, null 0.5: successes 5, failures"
                " 1, n = 6 trials; ties 0, missing 0; p = 0.1094, Benjamini-Hochberg-adjusted p = 0.1094 in family"
                ' "guard" (m = 1) at α = 0.1; MDE at 80% power, at n = 6 trials and α/m = 0.1/1 = 0.1 (a Bonferroni'
                f" bound): success probability 0.5 + 0.4635; no warnings; {tail}"
            ),
        }
        for name, sentence in expected.items():
            with self.subTest(name=name):
                self.assertEqual(render(rule, sample(), name, receipt=receipt, reads_path=self.reads), sentence)
        # 0.5 + 0.4635 is 0.8 ** (1 / 6) rounded up: the power reaches 80% there and not one step nearer the null.
        self.assertGreaterEqual((Fraction(1, 2) + Fraction("0.4635")) ** 6, MDE_POWER)
        self.assertLess((Fraction(1, 2) + Fraction("0.4634")) ** 6, MDE_POWER)

    def test_the_mde_is_at_the_non_tied_n_and_alpha_over_m_and_rounded_away_from_the_null(self):
        # 11 non-tied pairs and a tie; at 0.025 the region is 10 or 11 wins, at 0.05 it would be 9 to 11, and at 12
        # pairs 10 to 12, so each would give another effect.
        for alternative, faster, upward in (
            ("greater", ["win"] * 8 + ["loss"] * 3 + ["tie"], True),
            ("less", ["win"] * 3 + ["loss"] * 8 + ["tie"], False),
        ):
            with self.subTest(alternative=alternative):
                hypotheses = [{**record()["hypotheses"][0], "alternative": alternative}, *record()["hypotheses"][1:]]
                rule = self.rule(record(hypotheses=hypotheses, horizon={"kind": "count", "n": 12}, looks=[12]))
                self.reads = self.folder / f"reads-{alternative}.jsonl"
                receipt = self.read(rule, mde_sample(faster))
                sentence = render(rule, mde_sample(faster), "faster", receipt=receipt, reads_path=self.reads)
                self.assertTrue(sentence.startswith("faster: not met; "), sentence)
                head = (
                    "MDE at 80% power, at n = 11 discordant pairs (conditional on the observed ties) and α/m = 0.05/2 ="
                    " 0.025 (a Bonferroni bound): win probability 0.5 "
                )
                match = re.search(re.escape(head) + r"([+-]) (\d\.\d+);", sentence)
                assert match is not None, sentence
                self.assertEqual(match.group(1), "+" if upward else "-")
                away = 1 if upward else -1
                printed = Fraction(1, 2) + away * Fraction(match.group(2))
                # One unit in the gap's fourth significant digit, toward the null.
                nearer = printed - away * Fraction(10) ** (Decimal(match.group(2)).adjusted() - 3)
                power = {
                    p: sign_test_power(11, p_alt=p, alpha="1/40", alternative=alternative) for p in (printed, nearer)
                }
                self.assertGreaterEqual(power[printed], MDE_POWER)
                self.assertLess(power[nearer], MDE_POWER)

    def test_no_mde_exists_when_alpha_alone_reaches_the_power(self):
        hypotheses = [*record()["hypotheses"][:2], {**record()["hypotheses"][2], "alpha": "0.9"}]
        rule = self.rule(record(hypotheses=hypotheses))
        data = [{**u, "outcomes": {**u["outcomes"], "completes": "failure"}} for u in sample()]
        receipt = self.read(rule, data)
        sentence = render(rule, data, "completes", receipt=receipt, reads_path=self.reads)
        self.assertIn(
            "completes: not met; one-sided (greater) binomial test, method exact, null 0.5: successes 0, failures 6",
            sentence,
        )
        self.assertIn(
            "MDE at 80% power, at n = 6 trials and α/m = 0.9/1 = 0.9 (a Bonferroni bound): no MDE exists, since at"
            " this level the test has 80% power with no effect at all; ",
            sentence,
        )
        # At 0.9 the test rejects on 2 or more successes of 6, which happens 57 times in 64 under the null.
        self.assertEqual(binomial_power(6, p0="1/2", p_alt="1/2", alpha="0.9", alternative="greater"), Fraction(57, 64))

    def test_no_mde_exists_when_alpha_alone_gives_exactly_the_power(self):
        # One trial at p0 = 4/5 and alpha 0.8: the test rejects on a success, which happens 4 times in 5 under the null.
        completes = {**record()["hypotheses"][2], "alpha": "0.8", "p0": "4/5"}
        content = record(
            hypotheses=[completes],
            families={"guard": {"correction": "benjamini-hochberg"}},
            horizon={"kind": "count", "n": 1},
            looks=[1],
        )
        rule = self.rule(content)
        data = [{"participant": "p1", "enrolled": 1, "outcomes": {"completes": "failure"}}]
        self.assertEqual(binomial_power(1, p0="4/5", p_alt="4/5", alpha="0.8", alternative="greater"), MDE_POWER)
        receipt = self.read(rule, data)
        self.assertIn(
            "MDE at 80% power, at n = 1 trials and α/m = 0.8/1 = 0.8 (a Bonferroni bound): no MDE exists, since at"
            " this level the test has 80% power with no effect at all; ",
            render(rule, data, "completes", receipt=receipt, reads_path=self.reads),
        )

    def test_the_level_with_no_rejection_region_is_named_alpha_over_m(self):
        # clearer, 4 wins and 2 losses: at n = 6 no two-sided outcome has p <= 0.025, the Bonferroni bound. Yet 6 wins
        # give p = 1/32, which Holm meets at α = 0.05 beside faster's 1/64, so that level is not the sentence's α.
        rule = self.rule()
        receipt = self.read(rule, sample_b())
        sentence = render(rule, sample_b(), "clearer", receipt=receipt, reads_path=self.reads)
        self.assertIn(
            "α/m = 0.05/2 = 0.025 (a Bonferroni bound): none, since no outcome at this n can reach significance at"
            " level α/m = 0.025; ",
            sentence,
        )
        self.assertEqual(re.findall(r"\bα = ([^;]+);", sentence), ["0.05"])
        swept = [{**u, "outcomes": {**u["outcomes"], "clearer": "win"}} for u in sample()]
        self.assertEqual(evaluate(rule, swept).labels()["clearer"], "met")

    def test_an_mde_whose_rounded_gap_would_pass_the_boundary_prints_the_exact_gap(self):
        # E7: at n = 2400 and alpha 10^-1145, just above p0 to the 2400th power, only the extreme count rejects, so the
        # MDE lies within 10^-4 of the boundary; its gap rounded up to four digits, 0.6667, would print 1.00000001
        # above p0 = 0.33330001, and -0.00000001 below p0 = 0.66669999. The exact gap is printed instead.
        alpha = "0." + "0" * 1144 + "1"
        gap = "0.6666070179300212860107421875"
        for p0, alternative, outcome, printed in (
            ("0.33330001", "greater", "failure", f"0.33330001 + {gap}"),
            ("0.66669999", "less", "success", f"0.66669999 - {gap}"),
        ):
            with self.subTest(alternative=alternative):
                completes = {**record()["hypotheses"][2], "alternative": alternative, "alpha": alpha, "p0": p0}
                content = record(
                    hypotheses=[completes],
                    families={"guard": {"correction": "benjamini-hochberg"}},
                    horizon={"kind": "count", "n": 2400},
                    looks=[2400],
                )
                rule = self.rule(content, name=f"boundary-{alternative}.json")
                data = [
                    {"participant": f"p{i}", "enrolled": i, "outcomes": {"completes": outcome}} for i in range(2400)
                ]
                self.reads = self.folder / f"boundary-{alternative}.jsonl"
                receipt = self.read(rule, data)
                sentence = render(rule, data, "completes", receipt=receipt, reads_path=self.reads)
                self.assertIn(f"(a Bonferroni bound): success probability {printed}; no warnings; ", sentence)
                mde = binomial_mde(2400, p0=p0, alpha=alpha, power=MDE_POWER, alternative=alternative)
                assert mde is not None
                away = 1 if alternative == "greater" else -1
                # The printed gap is the MDE's own, so the effect is a probability and reaches the power; four digits
                # rounded up would not be a probability.
                self.assertEqual(Fraction(p0) + away * Fraction(gap), Fraction(mde))
                self.assertTrue(0 <= Fraction(mde) <= 1)
                self.assertFalse(0 <= Fraction(p0) + away * Fraction("0.6667") <= 1)
                self.assertGreaterEqual(
                    binomial_power(2400, p0=p0, p_alt=Fraction(mde), alpha=alpha, alternative=alternative), MDE_POWER
                )

    def test_a_met_verdict_carries_no_mde(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        self.assertNotIn("MDE", render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads))

    def test_an_early_read_reveals_nothing_about_the_result(self):
        # E8: an early read's sentence carries the name, when it was read and when its window closed everywhere, and
        # the provenance, and nothing else; the same data read once the window has closed carries all the rest.
        rule, window = self.rule(days_record()), date(2026, 1, 8)
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:59:59.999999+00:00")):
            early = self.read(rule, days_sample(), as_of=window)
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T12:00:00+00:00")):
            closed = self.read(rule, days_sample(), as_of=window)
        tail = f"prereg {rule.id}, data sha256 {early.data_sha256[:12]} over 3 units; onus {VERSION}."
        # What the result would give away: each is in a sentence read once the window has closed, never in an early one.
        revealing = (
            "met;",
            "test, method exact",
            "null 0.5",
            "ties ",
            "missing ",
            "p = ",
            "-adjusted p = ",
            'in family "',
            "α",
            "MDE at 80% power",
            "warnings",
        )
        for name in ("faster", "clearer", "completes"):
            with self.subTest(name=name):
                sentence = render(rule, days_sample(), name, receipt=early, reads_path=self.reads, as_of=window)
                self.assertEqual(
                    sentence,
                    f"{name}: read early (read at 2026-01-08T11:59:59.999999+00:00; window closed at"
                    f" 2026-01-08T12:00:00+00:00); {tail}",
                )
                decided = render(rule, days_sample(), name, receipt=closed, reads_path=self.reads, as_of=window)
                self.assertTrue(decided.startswith(f"{name}: not met; "), decided)
                for text in revealing:
                    self.assertIn(text, decided)
                    self.assertNotIn(text, sentence)

    def test_an_early_re_read_names_the_first_read(self):
        # E12: an early re-read on different data says so and names the first read, as one made once the window has
        # closed does; that is the read's history, and nothing about the result.
        rule, window = self.rule(days_record()), date(2026, 1, 8)
        corrected = [
            unit("b", "2026-01-06", "loss", "win", "failure") if u["participant"] == "b" else u for u in days_sample()
        ]
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T10:00:00+00:00")):
            first = self.read(rule, days_sample(), as_of=window)
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            again = self.read(
                rule, corrected, as_of=window, supersedes=first.line_sha256, reason="b was recorded wrongly"
            )
        self.assertEqual(
            render(rule, corrected, "faster", receipt=again, reads_path=self.reads, as_of=window),
            f"faster: read early (read at 2026-01-08T11:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00);"
            f" re-read on different data; first read {first.line_sha256[:12]};"
            f" prereg {rule.id}, data sha256 {again.data_sha256[:12]} over 3 units; onus {VERSION}.",
        )
        # The first read, early too, superseded nothing, and its sentence names no other read.
        self.assertEqual(
            render(rule, days_sample(), "faster", receipt=first, reads_path=self.reads, as_of=window),
            f"faster: read early (read at 2026-01-08T10:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00);"
            f" prereg {rule.id}, data sha256 {first.data_sha256[:12]} over 3 units; onus {VERSION}.",
        )
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T12:00:00+00:00")):
            late = self.read(rule, corrected, as_of=window, supersedes=first.line_sha256, reason="read once closed")
        self.assertIn(
            f"; re-read on different data; first read {first.line_sha256[:12]}; ",
            render(rule, corrected, "faster", receipt=late, reads_path=self.reads, as_of=window),
        )

    def test_an_early_re_read_under_a_different_record_gives_no_label_away(self):
        # E12, after its review: the same data read early again under an edited record needed supersedes only because
        # a label differs, so a clause on that read would tell a reader holding both sentences that one did.
        window = date(2026, 1, 8)
        rule = self.rule(days_record())
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T10:00:00+00:00")):
            first = self.read(rule, days_sample(), as_of=window)
        edited = self.rule(loosened(days_record()))
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            with self.assertRaisesRegex(PreregError, "with other labels"):
                self.read(edited, days_sample(), as_of=window)
            again = self.read(
                edited, days_sample(), as_of=window, supersedes=first.line_sha256, reason="alpha was recorded wrongly"
            )
        self.assertEqual(again.data_sha256, first.data_sha256)
        for name in ("faster", "clearer", "completes"):
            with self.subTest(name=name):
                self.assertEqual(
                    render(edited, days_sample(), name, receipt=again, reads_path=self.reads, as_of=window),
                    f"{name}: read early (read at 2026-01-08T11:00:00+00:00; window closed at"
                    f" 2026-01-08T12:00:00+00:00); prereg {edited.id}, data sha256 {again.data_sha256[:12]} over 3"
                    f" units; onus {VERSION}.",
                )
        # Once the window has closed the verdict is stated, and so is what the re-read differed in.
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T12:00:00+00:00")):
            late = self.read(
                edited, days_sample(), as_of=window, supersedes=first.line_sha256, reason="read once closed"
            )
        self.assertTrue(
            render(edited, days_sample(), "faster", receipt=late, reads_path=self.reads, as_of=window).startswith(
                f"faster: met; re-read after a read under a different record; first read {first.line_sha256[:12]}; "
            )
        )

    def test_a_re_read_of_the_same_data_under_a_different_record_is_not_called_one_on_different_data(self):
        # Another experiment's read of other data stands first in the reads file, and is none of this one's.
        other = self.rule(record(experiment="another synthetic comparison"), name="other.json")
        self.read(other, sample_b())
        first = self.read(self.rule(), sample())
        edited = self.rule(loosened(record()))
        second = self.read(edited, sample(), supersedes=first.line_sha256, reason="alpha was recorded wrongly")
        self.assertEqual(second.data_sha256, first.data_sha256)
        sentence = render(edited, sample(), "faster", receipt=second, reads_path=self.reads)
        self.assertTrue(
            sentence.startswith(
                f"faster: met; re-read after a read under a different record; first read {first.line_sha256[:12]}; "
            ),
            sentence,
        )
        # A later read on other data is one on different data, and changes nothing the earlier read's sentence says.
        third = self.read(edited, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        self.assertTrue(
            render(edited, sample_b(), "faster", receipt=third, reads_path=self.reads).startswith(
                f"faster: met; re-read on different data; first read {first.line_sha256[:12]}; one-sided"
            )
        )
        self.assertEqual(render(edited, sample(), "faster", receipt=second, reads_path=self.reads), sentence)

    def test_a_re_read_counts_the_reads_the_seal_held_it_to_by_experiment_and_by_record_stem(self):
        # An edited record keeps its file's stem and may rename its experiment; a copy under another file name keeps
        # the experiment. The seal holds a read under either to the first read, and render sorts it by that read too.
        first = self.read(self.rule(), sample())
        renamed = self.rule(record(experiment="synthetic layout comparison, renamed"))
        copied = self.rule(record(), name="copy.json")
        for other in (renamed, copied):
            with self.subTest(other=other.id):
                again = self.read(other, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
                sentence = render(other, sample_b(), "faster", receipt=again, reads_path=self.reads)
                self.assertTrue(
                    sentence.startswith(
                        f"faster: met; re-read on different data; first read {first.line_sha256[:12]}; one-sided"
                    ),
                    sentence,
                )

    def test_a_re_read_the_reads_file_does_not_explain_is_quoted_as_one_and_no_more(self):
        # No reads file written from honest evaluations holds such a read. One that does is still rendered, so an
        # honest correction stays quotable, and its clause claims neither different data nor a different record.
        rule = self.rule()
        result = evaluate(rule, sample())
        forged = dataclasses.replace(
            result,
            hypotheses=(
                dataclasses.replace(result.hypotheses[0], adjusted_p=Fraction(1), met=False),
                *result.hypotheses[1:],
            ),
        )
        wrong = record_read(rule, forged, reads_path=self.reads)
        honest = self.read(rule, sample(), supersedes=wrong.line_sha256, reason="the labels were recorded wrongly")
        self.assertEqual(honest.data_sha256, wrong.data_sha256)
        sentence = render(rule, sample(), "faster", receipt=honest, reads_path=self.reads)
        self.assertTrue(
            sentence.startswith(f"faster: met; re-read; first read {wrong.line_sha256[:12]}; one-sided"), sentence
        )
        # The first read's line removed by hand, from a file whose re-read was on different data: the same.
        self.reads.unlink()
        first = self.read(rule, sample())
        second = self.read(rule, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        lines = self.reads.read_text(encoding="utf-8").splitlines(keepends=True)
        self.reads.write_text("".join(lines[1:]), encoding="utf-8")
        self.assertTrue(
            render(rule, sample_b(), "faster", receipt=second, reads_path=self.reads).startswith(
                f"faster: met; re-read; first read {first.line_sha256[:12]}; one-sided"
            )
        )

    def test_an_early_re_read_the_reads_file_does_not_explain_carries_no_clause(self):
        rule, window = self.rule(days_record()), date(2026, 1, 8)
        result = evaluate(rule, days_sample(), as_of=window)
        forged = dataclasses.replace(
            result,
            hypotheses=(
                dataclasses.replace(result.hypotheses[0], adjusted_p=Fraction(0), met=True),
                *result.hypotheses[1:],
            ),
        )
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T10:00:00+00:00")):
            wrong = record_read(rule, forged, reads_path=self.reads)
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            honest = self.read(
                rule, days_sample(), as_of=window, supersedes=wrong.line_sha256, reason="the labels were wrong"
            )
        self.assertEqual(
            render(rule, days_sample(), "faster", receipt=honest, reads_path=self.reads, as_of=window),
            f"faster: read early (read at 2026-01-08T11:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00);"
            f" prereg {rule.id}, data sha256 {honest.data_sha256[:12]} over 3 units; onus {VERSION}.",
        )

    def test_the_first_record_read_again_after_an_edited_one_does_not_claim_to_differ_from_the_first_read(self):
        # The record is edited, read, and put back: the third read is of the first read's own record, data, and
        # labels, and was sealed by the read in between, so its clause speaks of that read and not of its own record.
        original = self.rule()
        first = self.read(original, sample())
        edited = self.rule(loosened(record()))
        self.read(edited, sample(), supersedes=first.line_sha256, reason="alpha was recorded wrongly")
        restored = self.rule()
        self.assertEqual(restored.id, original.id)
        third = self.read(restored, sample(), supersedes=first.line_sha256, reason="the alpha was right after all")
        sentence = render(restored, sample(), "faster", receipt=third, reads_path=self.reads)
        self.assertTrue(
            sentence.startswith(
                f"faster: met; re-read after a read under a different record; first read {first.line_sha256[:12]}; "
            ),
            sentence,
        )
        self.assertNotIn("re-read under a different record", sentence)

    def test_a_re_read_on_different_data_names_the_first_read(self):
        rule = self.rule()
        first = self.read(rule, sample())
        second = self.read(rule, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        again = render(rule, sample_b(), "faster", receipt=second, reads_path=self.reads)
        self.assertTrue(
            again.startswith(
                f"faster: met; re-read on different data; first read {first.line_sha256[:12]}; one-sided (greater)"
            ),
            again,
        )
        self.assertTrue(
            render(rule, sample(), "faster", receipt=first, reads_path=self.reads).startswith("faster: met; one")
        )
        # E4: the corrected data read again needs supersedes, the first read, again, and its sentence says so too.
        third = self.read(rule, sample_b(), supersedes=first.line_sha256, reason="the corrected data, read again")
        self.assertTrue(
            render(rule, sample_b(), "faster", receipt=third, reads_path=self.reads).startswith(
                f"faster: met; re-read on different data; first read {first.line_sha256[:12]}; one-sided (greater)"
            )
        )
        # The first data read again matches the first read and differs from the re-reads: on different data still.
        fourth = self.read(rule, sample(), supersedes=first.line_sha256, reason="the first data, read again")
        self.assertTrue(
            render(rule, sample(), "faster", receipt=fourth, reads_path=self.reads).startswith(
                f"faster: met; re-read on different data; first read {first.line_sha256[:12]}; one-sided (greater)"
            )
        )

    def test_render_requires_the_receipt_of_a_recorded_read(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        with self.assertRaisesRegex(TypeError, "needs the ReadReceipt of a recorded read, not None"):
            render(rule, sample(), "faster", receipt=None, reads_path=self.reads)  # type: ignore[arg-type]
        forged = dataclasses.replace(receipt, line_sha256="0" * 64)
        with self.assertRaisesRegex(PreregError, f"no line of .* has sha256 '{'0' * 64}'"):
            render(rule, sample(), "faster", receipt=forged, reads_path=self.reads)
        missing = self.folder / "missing.jsonl"
        with self.assertRaisesRegex(PreregError, "there is no reads file at"):
            render(
                rule, sample(), "faster", receipt=dataclasses.replace(receipt, reads_path=missing), reads_path=missing
            )

    def test_render_reads_only_the_file_the_receipt_names(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        copy = self.folder / "copy.jsonl"
        shutil.copyfile(self.reads, copy)
        with self.assertRaisesRegex(PreregError, "the receipt names the reads file .*reads.jsonl, not .*copy.jsonl"):
            render(rule, sample(), "faster", receipt=receipt, reads_path=copy)
        # The same file spelled another way (a temporary folder is often reached through a symlink) is the same file.
        spelled = self.folder.resolve() / ".." / self.folder.name / "reads.jsonl"
        self.assertTrue(render(rule, sample(), "faster", receipt=receipt, reads_path=spelled).startswith("faster: met"))

    def test_render_refuses_the_same_file_under_another_name(self):
        # E5 keeps D1's equality of resolved paths, and resolve() keeps a name's spelling, so a hard link to the reads
        # file is refused, and so is its name in another case, which a disk that folds case opens as the same file.
        rule = self.rule()
        receipt = self.read(rule, sample())
        linked = self.folder / "linked.jsonl"
        os.link(self.reads, linked)
        self.assertTrue(os.path.samefile(linked, self.reads))
        for other in (linked, self.folder / "Reads.jsonl"):
            with self.subTest(other=other.name):
                with self.assertRaisesRegex(
                    PreregError, f"the receipt names the reads file .*reads.jsonl, not .*{other.name}$"
                ):
                    render(rule, sample(), "faster", receipt=receipt, reads_path=other)

    def test_a_read_recorded_through_a_relative_path_names_its_file_after_a_change_of_directory(self):
        rule = self.rule()
        elsewhere = self.folder / "elsewhere"
        elsewhere.mkdir()
        with contextlib.chdir(self.folder):
            receipt = record_read(rule, evaluate(rule, sample()), reads_path="reads.jsonl")
        self.assertEqual(receipt.reads_path, self.reads.resolve())
        with contextlib.chdir(elsewhere):
            self.assertTrue(
                render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads).startswith("faster: met")
            )
            self.assertEqual(receipt_from_line("../reads.jsonl", receipt.line_sha256), receipt)
            with self.assertRaisesRegex(PreregError, "the receipt names the reads file .*reads.jsonl, not reads.jsonl"):
                render(rule, sample(), "faster", receipt=receipt, reads_path="reads.jsonl")

    def test_render_re_derives_the_verdict_from_the_data(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        with self.assertRaisesRegex(PreregError, r"its \['data_sha256'\] differ"):
            render(rule, sample_b(), "faster", receipt=receipt, reads_path=self.reads)
        stricter_hypotheses = [
            {**h, "alpha": "0.01"} if h["family"] == "primary" else h for h in record()["hypotheses"]
        ]
        stricter = self.rule(record(hypotheses=stricter_hypotheses), name="stricter.json")
        with self.assertRaisesRegex(PreregError, r"its \['prereg', 'labels'\] differ"):
            render(stricter, sample(), "faster", receipt=receipt, reads_path=self.reads)
        with self.assertRaisesRegex(PreregError, "has no hypothesis named 'slower'"):
            render(rule, sample(), "slower", receipt=receipt, reads_path=self.reads)

    def test_a_hand_edited_line_or_receipt_is_refused_field_by_field(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        good = json.loads(self.reads.read_text(encoding="utf-8"))
        edits: dict[str, object] = {
            "prereg": "layout@000000000000",
            "experiment": "an edited synthetic experiment",
            "data_sha256": "0" * 64,
            "n": 7,
            "labels": {**good["labels"], "faster": "not met"},
        }
        for field, value in edits.items():
            with self.subTest(line=field):
                edited = self.folder / f"edited-{field}.jsonl"
                text = json.dumps({**good, field: value}, sort_keys=True, separators=(",", ":"))
                edited.write_text(text + "\n", encoding="utf-8")
                forged = receipt_from_line(edited, hashlib.sha256(text.encode()).hexdigest())
                with self.assertRaisesRegex(PreregError, rf"its \['{field}'\] differ"):
                    render(rule, sample(), "faster", receipt=forged, reads_path=edited)
        receipts = {
            "at": dataclasses.replace(receipt, at=receipt.at + timedelta(microseconds=1)),
            "prereg": dataclasses.replace(receipt, prereg="layout@000000000000"),
            "data_sha256": dataclasses.replace(receipt, data_sha256="0" * 64),
        }
        for field, forged in receipts.items():
            with self.subTest(receipt=field):
                with self.assertRaisesRegex(PreregError, rf"its \['{field}'\] differ"):
                    render(rule, sample(), "faster", receipt=forged, reads_path=self.reads)

    def test_a_hand_edited_early_flag_is_refused(self):
        # A line's early flag is the one its read time gives under the rule's horizon. Flipped by hand, it would have
        # render state the verdict of a read made before its window closed, call a read early that was not, or call
        # early a count horizon's read, which never is.
        days, window = self.rule(days_record(), name="window.json"), date(2026, 1, 8)
        cases = [
            ("a count horizon's read", self.rule(), sample(), None, "2026-01-08T11:00:00+00:00"),
            ("a read before noon UTC on the end day", days, days_sample(), window, "2026-01-08T11:00:00+00:00"),
            ("a read at noon UTC on the end day", days, days_sample(), window, "2026-01-08T12:00:00+00:00"),
        ]
        for i, (label, rule, data, as_of, when) in enumerate(cases):
            with self.subTest(label):
                self.reads = self.folder / f"flag{i}.jsonl"
                with mock.patch("onus.prereg._evaluate._now", return_value=at(when)):
                    receipt = self.read(rule, data, as_of=as_of)
                render(
                    rule, data, "faster", receipt=receipt, reads_path=self.reads, as_of=as_of
                )  # the flag as recorded
                good = json.loads(self.reads.read_text(encoding="utf-8"))
                self.assertIs(good["early"], i == 1)
                text = json.dumps({**good, "early": not good["early"]}, sort_keys=True, separators=(",", ":"))
                self.reads.write_text(text + "\n", encoding="utf-8")
                forged = receipt_from_line(self.reads, hashlib.sha256(text.encode()).hexdigest())
                with self.assertRaisesRegex(PreregError, r"its \['early'\] differ"):
                    render(rule, data, "faster", receipt=forged, reads_path=self.reads, as_of=as_of)

    def test_a_malformed_line_anywhere_in_the_reads_file_refuses(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        with self.reads.open("a", encoding="utf-8") as reads:
            reads.write('{"schema": "read/1"}\n')
        with self.assertRaisesRegex(PreregError, "line 2 of .* is not a read/2 line"):
            render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads)

    def test_a_sentence_that_would_span_lines_is_refused(self):
        # E1: the sentence stays one line. load refuses a name, a family, or a file stem holding any break that
        # str.splitlines makes (E10, in RecordTest), and render refuses the sentence too, as a second check, which is
        # seen here with load's check switched off.
        marks = ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
        with self.assertRaisesRegex(PreregError, r"^hypotheses\[0\]\.name must be one line"):
            self.rule(renamed({"faster": "fast\u2028er"})[0])
        families = {"pri\u2028mary": {"correction": "holm"}, "guard": {"correction": "benjamini-hochberg"}}
        family = record(
            hypotheses=[
                {**h, "family": "pri\u2028mary"} if h["family"] == "primary" else h for h in record()["hypotheses"]
            ],
            families=families,
        )
        cases = [(f"fast{mark}er", *renamed({"faster": f"fast{mark}er"}), "layout.json") for mark in marks]
        cases += [("faster", family, sample(), "family.json"), ("faster", record(), sample(), "lay\u2028out.json")]
        for i, (name, content, data, file_name) in enumerate(cases):
            with (
                self.subTest(name=name, file_name=file_name),
                mock.patch("onus.prereg._rule._one_line", side_effect=lambda value, where: value),
            ):
                rule = self.rule(content, name=file_name)
                self.reads = self.folder / f"broken{i}.jsonl"
                receipt = self.read(rule, data)
                with self.assertRaisesRegex(PreregError, "cannot be quoted on one line: its name, its family, or the"):
                    render(rule, data, name, receipt=receipt, reads_path=self.reads)
        # The control: the same name with no break in it renders.
        self.reads = self.folder / "whole.jsonl"
        content, data = renamed({"faster": "fast er"})
        rule = self.rule(content, name="whole.json")
        receipt = self.read(rule, data)
        self.assertTrue(
            render(rule, data, "fast er", receipt=receipt, reads_path=self.reads).startswith("fast er: met;")
        )

    def test_render_reads_no_clock(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        # The watch sees a clock read through any name: here, three of them.
        with clock_reads() as control:
            datetime.now(UTC)
            date.today()
            time.time()
        self.assertEqual(control, ["datetime.now", "date.today", "time.time"])
        with (
            clock_reads() as seen,
            mock.patch("onus.prereg._evaluate._now", side_effect=AssertionError("render read the clock")),
        ):
            sentence = render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads)
        self.assertEqual(seen, [])
        self.assertTrue(sentence.startswith("faster: met"))

    def test_rendering_a_read_again_gives_the_same_sentence_and_writes_nothing(self):
        # render is idempotent: it only reads the reads file, so a second call records no read and changes no line,
        # and its sentence for a recorded read is the same however often it is asked for.
        rule = self.rule()
        first = self.read(rule, sample())
        again = self.read(rule, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        before = self.reads.read_bytes()
        for receipt, data in ((first, sample()), (again, sample_b())):
            with self.subTest(read=receipt.line_sha256[:12]):
                sentence = render(rule, data, "faster", receipt=receipt, reads_path=self.reads)
                self.assertEqual(render(rule, data, "faster", receipt=receipt, reads_path=self.reads), sentence)
        self.assertEqual(self.reads.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["layout.json", "reads.jsonl"])


class ReceiptTest(Reads):
    """receipt_from_line rebuilds a recorded read's receipt from its line, and from nothing else."""

    def test_a_receipt_is_rebuilt_from_its_line(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        rebuilt = receipt_from_line(str(self.reads), receipt.line_sha256)
        self.assertEqual(rebuilt, receipt)
        self.assertTrue(render(rule, sample(), "faster", receipt=rebuilt, reads_path=self.reads).startswith("faster"))

    def test_a_line_that_was_never_recorded_has_no_receipt(self):
        self.read(self.rule(), sample())
        with self.assertRaisesRegex(PreregError, "no read with that receipt was recorded there"):
            receipt_from_line(self.reads, "0" * 64)
        with self.assertRaisesRegex(PreregError, "there is no reads file at"):
            receipt_from_line(self.folder / "missing.jsonl", "0" * 64)


class ExploratoryTest(Folder):
    """render_exploratory quotes a bare test result, with no verdict, and nothing pre-registered."""

    def test_a_test_result_is_quoted_with_no_verdict(self):
        cases = {
            "one-sided (greater) sign test, method exact, null 0.5: wins 6, losses 0, n = 6 discordant pairs; ties 0,"
            " missing 0; p = 0.01562; no warnings": sign_test(6, 0, ties=0, alternative="greater", method="exact"),
            "one-sided (less) binomial test, method exact, null 1/3: successes 2, failures 7, n = 9 trials; ties 0,"
            " missing 0; p = 0.3772; no warnings": binomial_test(2, 9, p="1/3", alternative="less", method="exact"),
            "two-sided McNemar test, method exact, null 0.5: b = 3, c = 1, n = 4 discordant pairs; ties 0, missing 0;"
            " p = 0.625; no warnings": mcnemar_exact(3, 1, alternative="two-sided", method="exact"),
            "one-sided (less) sign test, method exact, null 0.5: wins 1, losses 1, n = 2 discordant pairs; ties 1,"
            " missing 1; p = 0.75; warning: 1 pairs with a missing value were dropped": paired_sign_test(
                [3, None, 1, 2], [1, 2, 1, 5], alternative="less", missing="drop", method="exact"
            ),
        }
        for body, result in cases.items():
            with self.subTest(test=result.test):
                self.assertEqual(render_exploratory(result), f"Exploratory: {body}; onus {VERSION}.")
        self.assertEqual(
            binomial_test(2, 9, p="1/3", alternative="less", method="exact").p_exact, Fraction(7424, 19683)
        )

    def test_only_a_bare_test_result_is_quoted(self):
        result = sign_test(6, 0, ties=0, alternative="greater", method="exact")
        evaluation = evaluate(load(self.write(record())), sample())
        registered = evaluation.hypotheses[0]
        with self.assertRaisesRegex(TypeError, "'faster' is pre-registered: quote it with render()"):
            render_exploratory(registered)  # type: ignore[arg-type]
        # The known gap: the bare result inside a pre-registered one can still be quoted, unrecorded.
        self.assertTrue(render_exploratory(registered.result).startswith("Exploratory: "))
        for other in (evaluation, Fraction(1, 64), None):
            with self.subTest(other=type(other).__name__):
                with self.assertRaisesRegex(TypeError, f"takes a TestResult, not {type(other).__name__}"):
                    render_exploratory(other)  # type: ignore[arg-type]
        self.assertEqual(render_exploratory(result), render_exploratory(dataclasses.replace(result)))

    def test_a_test_it_cannot_count_is_refused(self):
        unknown = TestResult("t", "exact", "greater", Fraction(1, 2), 1, 2, Fraction(1, 2))
        with self.assertRaisesRegex(ValueError, "cannot describe the test 't'"):
            render_exploratory(unknown)


class NumberTextTest(unittest.TestCase):
    """How the sentences write numbers: alphas exactly, p-values to four digits, MDEs as the null and a gap."""

    def test_exact_values_are_written_exactly(self):
        cases = {
            Fraction(1, 20): "0.05",
            Fraction(1, 40): "0.025",
            Fraction(1, 60): "1/60",
            Fraction(1, 3): "1/3",
            Fraction(80): "80",
            Fraction(1): "1",
            Fraction(3, 8): "0.375",
            Fraction(1, 1024): "0.0009765625",
        }
        for value, text in cases.items():
            with self.subTest(value=value):
                self.assertEqual(exact_text(value), text)

    def test_p_values_are_rounded_half_to_even_at_four_significant_digits(self):
        cases = {
            Fraction(1, 64): "0.01562",
            Fraction(3, 64): "0.04688",
            Fraction(3, 8): "0.375",
            Fraction(7, 64): "0.1094",
            Fraction(1, 20) + Fraction(1, 10**9): "0.05000",
            Fraction(1): "1",
            Fraction(1, 2**30): "9.313E-10",
        }
        for value, text in cases.items():
            with self.subTest(value=value):
                self.assertEqual(significant_text(value), text)

    def test_an_mde_is_the_null_and_its_gap_to_four_significant_digits_rounded_away_from_the_null(self):
        # At n = 4000, four fixed decimals printed 1.0000 at p0 = 999/1000 and overstated the effect by about a quarter
        # at p0 = 1/1000000; four significant digits of the gap hold wherever p0 sits.
        cases = {
            ("999/1000", "greater"): "0.999 + 0.0009443",
            ("1/1000000", "greater"): "0.000001 + 0.0004013",
            ("999/1000", "less"): "0.999 - 0.001844",
        }
        for (p0, alternative), text in cases.items():
            with self.subTest(p0=p0, alternative=alternative):
                mde = binomial_mde(4000, p0=p0, alpha="0.05", power=MDE_POWER, alternative=alternative)
                assert mde is not None
                self.assertEqual(mde_text(Fraction(p0), mde), text)
                null, sign, gap = text.split(" ")
                away = 1 if sign == "+" else -1
                printed = Fraction(null) + away * Fraction(gap)
                nearer = printed - away * Fraction(10) ** (Decimal(gap).adjusted() - 3)
                power = {
                    p: binomial_power(4000, p0=p0, p_alt=p, alpha="0.05", alternative=alternative)
                    for p in (printed, nearer)
                }
                self.assertGreaterEqual(power[printed], MDE_POWER)
                self.assertLess(power[nearer], MDE_POWER)
        # A gap with a shorter exact decimal keeps it; a null with no finite decimal is written "a/b".
        self.assertEqual(mde_text(Fraction(1, 2), 0.75), "0.5 + 0.25")
        self.assertEqual(mde_text(Fraction(1, 3), 0.5), "1/3 + 0.1667")

    def test_an_mde_whose_rounded_gap_would_pass_zero_or_one_is_printed_with_its_exact_gap(self):
        # E7: rounded up, the gap 2/3 prints 0.6667, which past 1/3 is above 1 and short of 2/3 is below 0; the exact
        # gap, written as the null is, keeps the printed effect the MDE itself.
        self.assertEqual(mde_text(Fraction(1, 3), 1.0), "1/3 + 2/3")
        self.assertEqual(mde_text(Fraction(2, 3), 0.0), "2/3 - 2/3")
        self.assertEqual(mde_text(Fraction(1, 2), 1.0), "0.5 + 0.5")
        # On the boundary, not past it, the four digits stand: 0.3333 + 0.6667 is 1, and 0.6667 - 0.6667 is 0, though
        # the exact gap is 2^-30 short of each.
        self.assertEqual(mde_text(Fraction("0.3333"), 1 - 2**-30), "0.3333 + 0.6667")
        self.assertEqual(mde_text(Fraction("0.6667"), 2**-30), "0.6667 - 0.6667")
        self.assertNotEqual(Fraction(1 - 2**-30) - Fraction("0.3333"), Fraction("0.6667"))


def marked(text: str) -> str:
    """``text`` between the two quote markers, each on a line of its own."""
    return f"{OPEN}\n{text}\n{CLOSE}\n"


class QuoteTest(Reads):
    """assert_quoted fails unless the quotes a document marks are exactly the rendered sentences."""

    FASTER = (
        "faster: met; one-sided (greater) sign test; prereg layout@0123456789ab, data sha256 ba5eba11 over 8 units."
    )
    CLEARER = "clearer: not met; one-sided (greater) sign test; prereg layout@0123456789ab, data sha256 ba5eba11."

    def test_a_document_marking_each_rendered_sentence_passes(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        sentences = [
            render(rule, sample(), name, receipt=receipt, reads_path=self.reads) for name in ("faster", "clearer")
        ]
        exploratory = render_exploratory(sign_test(5, 1, ties=0, alternative="greater", method="exact"))
        doc = "# Results\n\n" + marked(sentences[0]) + "\nProse between.\n\n" + marked(sentences[1])
        assert_quoted(doc, sentences)
        assert_quoted(doc, tuple(sentences))
        # The same sentence marked twice is quoted twice, and an exploratory sentence is quoted like any other.
        assert_quoted(doc + marked(sentences[0]) + marked(exploratory), [*sentences, exploratory])
        assert_quoted(marked(sentences[0]), [sentences[0], sentences[0]])
        # A sentence's own whitespace is read as a span's is: handed over wrapped, it is the same sentence.
        assert_quoted(marked(sentences[0]), [sentences[0].replace("; ", ";\n")])

    def test_a_marked_quote_may_be_wrapped_and_indented_and_nothing_else(self):
        words = self.FASTER.split(" ")
        wrapped = "\n".join(" ".join(words[i : i + 4]) for i in range(0, len(words), 4))
        for label, text in {
            "one line": self.FASTER,
            "markers on the sentence's line": None,
            "hard-wrapped": wrapped,
            "indented and wrapped": "    " + wrapped.replace("\n", "\n    "),
            "tabs, CRLF, and spaces left at line ends": wrapped.replace("\n", " \t\r\n"),
            "a blank line inside": wrapped.replace("\n", "\n\n", 1),
            "a no-break space and a line separator, which str.split reads as whitespace": wrapped.replace(
                "\n", "\u00a0\u2028"
            ),
        }.items():
            with self.subTest(label):
                doc = f"- {OPEN}{self.FASTER}{CLOSE}\n" if text is None else marked(text)
                assert_quoted(doc, [self.FASTER])
        for label, text in {
            "a rounded figure": self.FASTER.replace("8 units", "about 8 units"),
            "a changed character": self.FASTER.replace("met;", "met:"),
            "another letter case": self.FASTER.replace("faster: met", "Faster: Met"),
            "a zero-width space, which str.split does not read as whitespace": self.FASTER.replace(
                "met;", "met;\u200b"
            ),
            "a blockquote marker opening a wrapped line": wrapped.replace("\n", "\n> "),
            "a list marker inside the span": "- " + self.FASTER,
            "a word split by the wrap": self.FASTER.replace("greater", "grea\nter"),
            "two sentences in one span": self.FASTER + " " + self.CLEARER,
            "nothing": "",
        }.items():
            with self.subTest(label):
                with self.assertRaisesRegex(AssertionError, "line 3 of the document is none of the rendered sentences"):
                    assert_quoted("# Results\n\n" + marked(text), [self.FASTER, self.CLEARER])

    def test_a_stale_copy_inside_markers_fails_wherever_it_stands(self):
        stale = self.FASTER.replace("ba5eba11", "0ddba11")
        good = marked(self.FASTER) + marked(self.CLEARER)
        for label, doc in {"before": marked(stale) + good, "after": good + marked(stale)}.items():
            with self.subTest(stale=label):
                with self.assertRaisesRegex(
                    AssertionError, "is none of the rendered sentences: 'faster: met; .*0ddba11"
                ):
                    assert_quoted(doc, [self.FASTER, self.CLEARER])
        # The message names the line of the span's opening marker.
        with self.assertRaisesRegex(AssertionError, "marked at line 7 of the document"):
            assert_quoted(good + marked(stale), [self.FASTER, self.CLEARER])

    def test_a_sentence_the_document_does_not_mark_fails(self):
        # The message names the first sentence, in the order given, that no span holds.
        for label, (doc, missing) in {
            "no markers at all": (f"- {self.FASTER}\n- {self.CLEARER}\n", "faster: met"),
            "an empty document": ("", "faster: met"),
            "the other sentence marked": (marked(self.FASTER) + f"- {self.CLEARER}\n", "clearer: not met"),
        }.items():
            with self.subTest(label):
                with self.assertRaisesRegex(AssertionError, f"marks no quote of the rendered sentence '{missing}"):
                    assert_quoted(doc, [self.FASTER, self.CLEARER])
        # Only marked text is checked: a stale copy outside any markers is not found.
        assert_quoted(f"- {self.FASTER} (stale, unmarked)\n" + marked(self.FASTER), [self.FASTER])

    def test_a_marker_that_is_not_exact_fails_instead_of_marking_nothing(self):
        stale = self.FASTER.replace("ba5eba11", "0ddba11")
        for label, opening in {
            "no spaces": "<!--onus:quote-->",
            "two spaces": "<!--  onus:quote -->",
            "another case": "<!-- ONUS:QUOTE -->",
            "a key after it": "<!-- onus:quote layout@0123456789ab faster -->",
            "never finished": "<!-- onus:quote",
            "not a comment": "onus:quote",
        }.items():
            with self.subTest(label):
                with self.assertRaisesRegex(
                    AssertionError, "line 2 of the document mentions .* outside an exact marker"
                ):
                    assert_quoted(f"# Results\n{opening}\n{self.FASTER}\n{CLOSE}\n", [self.FASTER])
        # The closing marker is held to its exact text as the opening one is.
        for label, closing in {
            "a space after the slash": "<!-- / onus:quote -->",
            "no spaces": "<!--/onus:quote-->",
            "another case": "<!-- /ONUS:QUOTE -->",
            "never finished": "<!-- /onus:quote",
        }.items():
            with self.subTest(closing=label):
                with self.assertRaisesRegex(AssertionError, "line 3 of the document mentions .* outside an exact"):
                    assert_quoted(f"{OPEN}\n{self.FASTER}\n{closing}\n", [self.FASTER])
        # Known limit: a slip inside the ten characters is not seen, so such a pair marks nothing, and what stands
        # between it is as unchecked as any unmarked text.
        assert_quoted(f"<!-- onus: quote -->{stale}<!-- /onus: quote -->\n" + marked(self.FASTER), [self.FASTER])
        # A pair of inexact markers round a stale copy marks nothing, so the copy must not pass unchecked beside a
        # good quote: with other spacing, and in another case.
        for label, (opening, closing) in {
            "no spaces": ("<!--onus:quote-->", "<!--/onus:quote-->"),
            "another case": ("<!-- ONUS:QUOTE -->", "<!-- /ONUS:QUOTE -->"),
        }.items():
            with self.subTest(pair=label):
                with self.assertRaisesRegex(AssertionError, "line 1 of the document mentions .* outside an exact"):
                    assert_quoted(f"{opening}{stale}{closing}\n" + marked(self.FASTER), [self.FASTER])
        # At the very start of a document, where no marker's opening could stand before it.
        with self.assertRaisesRegex(AssertionError, "line 1 of the document mentions"):
            assert_quoted("onus:quote -->" + marked(self.FASTER), [self.FASTER])

    def test_markers_that_do_not_pair_fail(self):
        # Each would leave a stale copy unchecked beside a good quote, were the stray marker let through.
        stale = self.FASTER.replace("ba5eba11", "0ddba11")
        good = marked(self.FASTER)
        cases = {
            "a closing marker first": (f"{CLOSE}\n" + good, "line 1 of the document closes a quote that no"),
            "a second closing marker": (good + f"{CLOSE}\n", "line 4 of the document closes a quote that no"),
            "an opening marker inside a span": (
                f"{OPEN}\n{stale}\n{OPEN}\n{self.FASTER}\n{CLOSE}\n",
                "line 3 of the document opens a quote inside the one opened at line 1",
            ),
            "a span never closed": (good + f"\n{OPEN}\n{stale}\n", "opened at line 5 of the document is never closed"),
        }
        for label, (doc, message) in cases.items():
            with self.subTest(label):
                with self.assertRaisesRegex(AssertionError, message):
                    assert_quoted(doc, [self.FASTER])
        # Two spans one after the other are two quotes: the first is closed before the second opens.
        assert_quoted(good + good, [self.FASTER])

    def test_only_text_and_a_list_of_sentences_are_compared(self):
        doc = marked(self.FASTER)
        with self.assertRaisesRegex(TypeError, "reads a document's text, not bytes"):
            assert_quoted(doc.encode(), [self.FASTER])  # type: ignore[arg-type]
        for label, sentences in {
            "one string": self.FASTER,
            "a set": {self.FASTER},
            "a generator": (each for each in [self.FASTER]),
            "a list holding bytes": [self.FASTER.encode()],
            "a list holding None": [self.FASTER, None],
        }.items():
            with self.subTest(label):
                with self.assertRaisesRegex(TypeError, "as a list or tuple of strings"):
                    assert_quoted(doc, sentences)  # type: ignore[arg-type]
        empties: tuple[list[str], tuple[str, ...]] = ([], ())
        for empty in empties:
            # With no sentence, a document that marks nothing would otherwise pass, having been checked against nothing.
            with self.assertRaisesRegex(ValueError, "needs at least one rendered sentence"):
                assert_quoted("No result is quoted here.\n", empty)
            with self.assertRaisesRegex(ValueError, "needs at least one rendered sentence"):
                assert_quoted(doc, empty)
        for label, sentence in {
            "empty": "",
            "only whitespace": " \n\t",
            "holding the opening marker": f"{OPEN} faster: met.",
            "holding the marker's words in another case": "Onus:Quote is met.",
        }.items():
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "is not a sentence a document can quote"):
                    assert_quoted(doc, [self.FASTER, sentence])
        # An empty sentence would match an empty span: a caller that lost its sentence must not pass.
        with self.assertRaisesRegex(ValueError, "is not a sentence a document can quote"):
            assert_quoted(marked(""), [""])
