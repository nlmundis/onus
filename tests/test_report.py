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
from onus.report._quote import RENDERED
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

    def test_a_met_verdict_carries_no_mde(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        self.assertNotIn("MDE", render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads))

    def test_an_early_read_states_no_verdict_and_no_mde(self):
        rule = self.rule(days_record())
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            early = self.read(rule, days_sample(), as_of=date(2026, 1, 8))
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T12:00:00+00:00")):
            closed = self.read(rule, days_sample(), as_of=date(2026, 1, 8))
        for receipt, verdict in ((early, "read early"), (closed, "not met")):
            with self.subTest(verdict=verdict):
                sentence = render(
                    rule, days_sample(), "faster", receipt=receipt, reads_path=self.reads, as_of=date(2026, 1, 8)
                )
                self.assertTrue(sentence.startswith(f"faster: {verdict}; one-sided (greater) sign test"), sentence)
                self.assertEqual(sentence.count(" met;"), int(verdict == "not met"))
                # Only a not-met verdict carries the MDE, so on an early read it would give the verdict away.
                self.assertEqual("MDE at 80% power" in sentence, verdict == "not met", sentence)

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

    def test_a_malformed_line_anywhere_in_the_reads_file_refuses(self):
        rule = self.rule()
        receipt = self.read(rule, sample())
        with self.reads.open("a", encoding="utf-8") as reads:
            reads.write('{"schema": "read/1"}\n')
        with self.assertRaisesRegex(PreregError, "line 2 of .* is not a read/2 line"):
            render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads)

    def test_a_sentence_that_would_span_lines_is_refused(self):
        # E1: the sentence stays one line, and load accepts any name that is not blank, so render refuses a name, a
        # family, or a file stem holding any break str.splitlines makes, which is where assert_quoted splits a document.
        marks = ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
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
            with self.subTest(name=name, file_name=file_name):
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


# Words every sentence of the record holds outside its hypothesis's name: the template's, and a family's.
TEMPLATE_WORDS = ("warnings", "power", "data", "sign", "exact", "units", "prereg", "onus", "Holm", "primary")


class QuoteTest(Reads):
    """assert_quoted fails unless every line quoting a rendered sentence's result holds that sentence exactly."""

    def setUp(self):
        super().setUp()
        self.layout = self.rule()
        receipt = self.read(self.layout, sample())
        self.sentences = {
            name: render(self.layout, sample(), name, receipt=receipt, reads_path=self.reads)
            for name in ("faster", "clearer", "completes")
        }
        self.sentence = self.sentences["faster"]

    def test_a_document_quoting_each_sentence_on_its_own_line_passes(self):
        # Another record's hypothesis of the same name, quoted in the same document, is another result.
        other = self.rule(record(experiment="another synthetic experiment"), name="other.json")
        other_receipt = self.read(other, sample_b())
        elsewhere = render(other, sample_b(), "faster", receipt=other_receipt, reads_path=self.reads)
        self.assertNotEqual(other.id, self.layout.id)
        lines = [
            "# Results",
            "",
            f"- {self.sentences['faster']}",
            f"> {self.sentences['clearer']}",
            self.sentences["completes"],
            f"The same question in another experiment: {elsewhere}",
            "Prose about the faster layout, which names no record.",
        ]
        for newline in ("\n", "\r\n"):
            doc = newline.join(lines) + newline
            for name, sentence in self.sentences.items():
                with self.subTest(name=name, newline=newline):
                    assert_quoted(doc, sentence)
        assert_quoted("\n".join(lines), elsewhere)

    def test_every_kind_of_rendered_sentence_is_recognised(self):
        days, window = self.rule(days_record(), name="window.json"), date(2026, 1, 8)
        self.reads = self.folder / "window.jsonl"
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            early = self.read(days, days_sample(), as_of=window)
        early_sentence = render(days, days_sample(), "faster", receipt=early, reads_path=self.reads, as_of=window)
        self.reads = self.folder / "re-read.jsonl"
        first = self.read(self.layout, sample())
        again = self.read(self.layout, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        sentences = [
            early_sentence,
            render(self.layout, sample_b(), "faster", receipt=again, reads_path=self.reads),
            *self.sentences.values(),
        ]
        self.assertEqual([s.split(";")[0] for s in sentences[:2]], ["faster: read early", "faster: met"])
        self.assertIn("; re-read on different data; first read ", sentences[1])
        for sentence in sentences:
            with self.subTest(sentence=sentence[:40]):
                assert_quoted(f"- {sentence}\n", sentence)

    def quote_each(self, content: dict[str, Any], data: list[dict[str, Any]], name: str) -> tuple[Rule, dict[str, str]]:
        """Load ``content`` as the record ``name``, read ``data`` into a reads file of its own, and render each one."""
        rule = self.rule(content, name=name)
        self.reads = self.folder / f"{name}.reads.jsonl"
        receipt = self.read(rule, data)
        return rule, {
            h.name: render(rule, data, h.name, receipt=receipt, reads_path=self.reads) for h in rule.hypotheses
        }

    def test_a_word_of_another_sentence_does_not_name_this_hypothesis(self):
        # Each document quotes every sentence of its record once, exactly, one to a line, so each check passes. Each
        # name is a word another sentence holds: the template's, a family's, a longer name's, or the file stem's.
        cases = {word: ({"completes": word}, f"record{i}.json") for i, word in enumerate(TEMPLATE_WORDS)}
        cases["fast"] = ({"clearer": "fast"}, "beside.json")
        cases["faster"] = ({}, "faster.json")
        for word, (names, file_name) in cases.items():
            with self.subTest(word=word):
                content, data = renamed(names)
                rule, sentences = self.quote_each(content, data, file_name)
                self.assertTrue(any(word in s for name, s in sentences.items() if name != word), "a word another holds")
                # A line naming the record alone names no hypothesis, though the stem "faster" is a hypothesis's name.
                lines = [f"- {s}" for s in sentences.values()] + [f"All three are pre-registered in {rule.id}."]
                doc = "\n".join(lines) + "\n"
                for sentence in sentences.values():
                    assert_quoted(doc, sentence)

    def test_a_prereg_id_inside_another_names_another_record(self):
        # The same record under two file names, layout@X and old_layout@X, whose id holds the first as text.
        older = self.rule(name="old_layout.json")
        self.reads = self.folder / "old_layout.jsonl"
        old = render(older, sample(), "faster", receipt=self.read(older, sample()), reads_path=self.reads)
        self.assertIn(self.layout.id, older.id)
        doc = "\n".join([f"- {self.sentence}", f"- {old}", f"The older record, {older.id}, found faster too.", ""])
        assert_quoted(doc, self.sentence)
        # The prose names old_layout's "faster" beside its id, so it is that record's result in other words.
        with self.assertRaisesRegex(
            AssertionError, f"^line 3 of the document quotes 'faster' of {re.escape(older.id)}"
        ):
            assert_quoted(doc, old)

    def test_a_verdict_in_prose_does_not_hide_what_follows_it(self):
        # A body runs from a verdict to the next provenance only when no other verdict comes between, so a verdict-like
        # phrase in prose cannot swallow a mention of the result that stands before another sentence on its line.
        line = f"Shortened: met; faster held under {self.layout.id} at p = 0.016; in full, {self.sentences['clearer']}"
        doc = "\n".join([f"- {self.sentence}", line, ""])
        with self.assertRaisesRegex(AssertionError, "^line 2 of the document quotes 'faster'"):
            assert_quoted(doc, self.sentence)
        assert_quoted(doc, self.sentences["clearer"])

    def test_a_stale_copy_of_the_result_anywhere_in_the_document_fails(self):
        stale = self.sentence.replace("p = 0.01562", "p = 0.016")
        paraphrase = f"faster was met under {self.layout.id} (p = 0.016)."
        for label, line in (("a stale copy", stale), ("a paraphrase", paraphrase)):
            for before in (True, False):
                with self.subTest(label, before=before):
                    quoted = [f"- {line}", f"- {self.sentence}"] if before else [f"- {self.sentence}", f"- {line}"]
                    doc = "\n".join(["# Results", *quoted, ""])
                    number = 2 if before else 3
                    with self.assertRaisesRegex(
                        AssertionError,
                        rf"^line {number} of the document quotes 'faster' of {re.escape(self.layout.id)} other than as"
                        rf" rendered: {re.escape(repr(f'- {line}'))}",
                    ):
                        assert_quoted(doc, self.sentence)

    def test_a_document_quoting_a_read_and_the_re_read_that_superseded_it_fails_for_each(self):
        self.reads = self.folder / "re-read.jsonl"
        first = self.read(self.layout, sample())
        again = self.read(self.layout, sample_b(), supersedes=first.line_sha256, reason="p6 was recorded wrongly")
        both = [
            render(self.layout, data, "faster", receipt=receipt, reads_path=self.reads)
            for data, receipt in ((sample(), first), (sample_b(), again))
        ]
        self.assertNotEqual(both[0], both[1])
        doc = "\n".join(both)
        for i, sentence in enumerate(both):
            with self.subTest(read=i):
                with self.assertRaisesRegex(AssertionError, f"^line {2 - i} of the document quotes 'faster'"):
                    assert_quoted(doc, sentence)

    def test_a_changed_figure_a_wrapped_line_or_a_missing_sentence_fails(self):
        cases = {
            "a rounded figure": (self.sentence.replace("0.01562", "0.016"), "line 1 of the document quotes 'faster'"),
            "an older rendering": (self.sentence.replace(f"onus {VERSION}.", "onus 0.0.0-dev."), "line 1 of"),
            "a wrapped line": (self.sentence.replace("sign test, ", "sign test,\n"), "the document does not quote"),
            "another hypothesis only": (self.sentences["clearer"], "the document does not quote the rendered sentence"),
            "nothing": ("", "the document does not quote the rendered sentence: no line of it names both 'faster' and"),
        }
        self.assertNotIn("faster", self.sentence.split("sign test, ")[1])
        for label, (doc, message) in cases.items():
            with self.subTest(label):
                self.assertNotEqual(doc, self.sentence)
                with self.assertRaisesRegex(AssertionError, f"^{re.escape(message)}"):
                    assert_quoted(doc, self.sentence)

    def test_only_text_and_a_rendered_sentence_are_compared(self):
        with self.assertRaisesRegex(TypeError, "compares text, not bytes and str"):
            assert_quoted(self.sentence.encode(), self.sentence)  # type: ignore[arg-type]
        exploratory = render_exploratory(sign_test(6, 0, ties=0, alternative="greater", method="exact"))
        unrendered = {
            "an empty sentence": "",
            "an exploratory sentence": exploratory,
            "a sentence cut short of its provenance": self.sentence.split("; prereg ")[0],
            "a sentence with its line break": self.sentence + "\n",
        }
        for label, sentence in unrendered.items():
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, "checks a sentence render returned, which names its"):
                    assert_quoted(f"{sentence}\n{self.sentence}\n", sentence)

    def test_a_sentence_that_spans_lines_is_not_one_render_returned(self):
        # render refuses one (RenderTest); built by hand, a sentence whose name holds a break str.splitlines makes is
        # refused here too, rather than failed as a document that does not quote it.
        for mark in ("\r", "\x0c", "\x85", "\u2028"):
            with self.subTest(mark=mark):
                spanning = self.sentence.replace("faster", f"fast{mark}er", 1)
                self.assertIsNotNone(RENDERED.fullmatch(spanning))
                with self.assertRaisesRegex(
                    ValueError, "checks a sentence render returned, which is one line; .* spans 2"
                ):
                    assert_quoted(f"- {spanning}\n", spanning)
