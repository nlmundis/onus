"""onus.prereg: records refused on any doubt, evaluation that is pure and bounded by its horizon, and reads."""

import copy
import dataclasses
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from unittest import mock

import onus
from onus.prereg import (
    BoundArtifactError,
    Evaluation,
    Horizon,
    HorizonNotReachedError,
    PreregError,
    Rule,
    evaluate,
    load,
    prereg_id,
    record_read,
    status,
)
from onus.stats import binomial_test, holm, sign_test


def record(**changes: object) -> dict[str, Any]:
    """A valid synthetic prereg/1 record: two sign tests in a Holm family, a binomial test alone."""
    base: dict[str, Any] = {
        "schema": "prereg/1",
        "experiment": "synthetic layout comparison",
        "registered": "2026-01-05",
        "hypotheses": [
            {
                "name": "faster",
                "test": "sign_test",
                "alternative": "greater",
                "method": "exact",
                "alpha": "0.05",
                "family": "primary",
            },
            {
                "name": "clearer",
                "test": "sign_test",
                "alternative": "two-sided",
                "method": "exact",
                "alpha": "0.05",
                "family": "primary",
            },
            {
                "name": "completes",
                "test": "binomial_test",
                "alternative": "greater",
                "method": "exact",
                "alpha": "0.1",
                "family": "guard",
                "p0": "1/2",
            },
        ],
        "families": {"primary": {"correction": "holm"}, "guard": {"correction": "benjamini-hochberg"}},
        "unit": "participant",
        "cluster_key": None,
        "order_key": "enrolled",
        "horizon": {"kind": "count", "n": 6},
        "looks": [6],
        "bound_artifacts": {},
        "provenance": {"author": "a synthetic example"},
    }
    base.update(changes)
    return base


def unit(
    ident: str | int, order: str | int, faster: str, clearer: str, completes: str, **extra: object
) -> dict[str, Any]:
    return {
        "participant": ident,
        "enrolled": order,
        "outcomes": {"faster": faster, "clearer": clearer, "completes": completes},
        **extra,
    }


def sample() -> list[dict[str, Any]]:
    # Listed out of order on purpose; by "enrolled", the first six are 1..6, and 7 and 8 come after.
    return [
        unit("p8", 8, "loss", "loss", "failure"),
        unit("p3", 3, "win", "loss", "success"),
        unit("p1", 1, "win", "win", "success"),
        unit("p6", 6, "win", "tie", "success"),
        unit("p2", 2, "win", "win", "success"),
        unit("p7", 7, "loss", "loss", "failure"),
        unit("p5", 5, "win", "win", "failure"),
        unit("p4", 4, "win", "win", "success"),
    ]


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="onus-prereg-"))
        self.addCleanup(shutil.rmtree, self.folder)

    def write(self, content: dict[str, Any] | str | bytes, name: str = "layout.json") -> Path:
        path = self.folder / name
        if isinstance(content, dict):
            content = json.dumps(content)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path


class RecordTest(Folder):
    """A record is loaded only when every field is one prereg/1 defines, of the kind it defines."""

    def test_a_valid_record_loads_with_every_field_read(self):
        path = self.write(record())
        rule = load(path)
        self.assertEqual(rule.id, prereg_id(path))
        self.assertRegex(rule.id, r"^layout@[0-9a-f]{12}$")
        self.assertEqual(rule.id, f"layout@{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}")
        self.assertEqual(rule.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(rule.registered, date(2026, 1, 5))
        self.assertEqual([h.name for h in rule.hypotheses], ["faster", "clearer", "completes"])
        self.assertEqual(rule.hypotheses[0].alpha, Fraction(1, 20))
        self.assertEqual(rule.hypotheses[2].p0, Fraction(1, 2))
        self.assertIsNone(rule.hypotheses[0].p0)
        self.assertEqual(dict(rule.families), {"primary": "holm", "guard": "benjamini-hochberg"})
        self.assertEqual((rule.horizon.kind, rule.horizon.size, rule.horizon.start), ("count", 6, None))
        self.assertIsNone(rule.horizon.end)
        self.assertEqual(rule.looks, (6,))
        self.assertEqual((rule.unit, rule.order_key), ("participant", "enrolled"))

    def test_any_edit_gives_the_record_a_new_id(self):
        first = prereg_id(self.write(record()))
        self.assertNotEqual(first, prereg_id(self.write(record(experiment="synthetic layout comparison, v2"))))

    def test_a_key_prereg_1_does_not_define_is_refused_at_every_level(self):
        cases: dict[str, dict[str, Any]] = {
            "the record": record(notes="free text"),
            "hypotheses[0]": record(hypotheses=[{**record()["hypotheses"][0], "power": "0.8"}]),
            "families.primary": record(
                hypotheses=record()["hypotheses"][:2], families={"primary": {"correction": "holm", "note": "x"}}
            ),
            "horizon": record(horizon={"kind": "count", "n": 6, "start": "2026-01-05"}),
        }
        for where, content in cases.items():
            with self.subTest(where=where):
                with self.assertRaisesRegex(PreregError, f"^{re.escape(where)} has keys prereg/1 does not"):
                    load(self.write(content))

    def test_a_missing_key_is_refused(self):
        for key in ("registered", "cluster_key", "looks", "provenance"):
            content = record()
            del content[key]
            with self.subTest(key=key):
                with self.assertRaisesRegex(PreregError, rf"the record lacks \['{key}'\]"):
                    load(self.write(content))
        hypothesis = dict(record()["hypotheses"][0])
        del hypothesis["method"]
        with self.assertRaisesRegex(PreregError, r"hypotheses\[0\] lacks \['method'\]"):
            load(self.write(record(hypotheses=[hypothesis, *record()["hypotheses"][1:]])))

    def test_a_float_a_non_number_or_a_repeated_key_is_refused(self):
        cases: dict[str, str | bytes] = {
            "the float 0.05": '{"alpha": 0.05}',
            "holds NaN": '{"alpha": NaN}',
            r"gives a key more than once: \['schema'\]": '{"schema": "prereg/1", "schema": "prereg/1"}',
            "not JSON onus can read: Expecting": "{",
            "is not UTF-8": b"\xff",
            r"the float 0\.05": json.dumps(record()).replace('"alpha": "0.05"', '"alpha": 0.05', 1),
            "Exceeds the limit": '{"n": ' + "9" * 5000 + "}",
            # Each interpreter words its limit differently (3.14 reports a stack overflow), so match onus's words.
            "the record is not JSON onus can read": "[" * 200000,
            # Deeper than Python's recursion limit: 3.11's parser refuses it, 3.13's accepts it and the walk must not.
            "the record must be an object|the record is not JSON onus can read": "[" * 3000 + "]" * 3000,
            "not valid Unicode": json.dumps(record(experiment="\ud800")),
        }
        for message, text in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregError, message):
                    load(self.write(text))

    def test_each_field_must_be_of_its_kind(self):
        hypotheses = record()["hypotheses"]
        cases: dict[str, dict[str, Any]] = {
            "schema must be 'prereg/1'": record(schema="prereg/2"),
            "must be an object": record(horizon=[6]),
            "experiment must be a non-empty string": record(experiment=" "),
            "registered must be a date written YYYY-MM-DD": record(registered="20260105"),
            "registered is not a real date": record(registered="2026-02-30"),
            "hypotheses must be a non-empty list": record(hypotheses=[]),
            r"hypotheses\[0\] must be an object": record(hypotheses=["faster"]),
            r"test must be one of \('sign_test', 'binomial_test'\)": record(
                hypotheses=[{**hypotheses[0], "test": "t_test"}, *hypotheses[1:]]
            ),
            "alternative must be one of": record(hypotheses=[{**hypotheses[0], "alternative": "up"}, *hypotheses[1:]]),
            r"method must be one of \('exact',\)": record(
                hypotheses=[{**hypotheses[0], "method": "normal"}, *hypotheses[1:]]
            ),
            "alpha must be an exact number written as a string": record(
                hypotheses=[{**hypotheses[0], "alpha": 1}, *hypotheses[1:]]
            ),
            r"alpha must lie in \(0, 1\)": record(hypotheses=[{**hypotheses[0], "alpha": "1"}, *hypotheses[1:]]),
            "must have distinct names": record(
                hypotheses=[hypotheses[0], {**hypotheses[1], "name": "faster"}, hypotheses[2]]
            ),
            "families must be a non-empty object": record(families={}),
            "correction must be one of": record(
                families={"primary": {"correction": "bonferroni"}, "guard": {"correction": "holm"}}
            ),
            "family 'spare' is declared but no hypothesis belongs to it": record(
                families={**record()["families"], "spare": {"correction": "holm"}}
            ),
            r"name families that are not declared: \['guard'\]": record(families={"primary": {"correction": "holm"}}),
            "decided at one alpha": record(hypotheses=[{**hypotheses[0], "alpha": "0.01"}, *hypotheses[1:]]),
            "three different fields": record(order_key="participant"),
            "unit must be a non-empty string": record(unit=3),
            "cluster_key must be null": record(cluster_key="site"),
            'kind is "count" or "days"': record(horizon={"kind": "weeks", "n": 6}),
            "horizon.n must be a positive int": record(horizon={"kind": "count", "n": 0}, looks=[0]),
            r"looks must be \[6\], the horizon alone": record(looks=[3, 6]),
            "provenance must be an object of strings": record(provenance={"version": 2}),
            r"looks must be \[1\]": record(horizon={"kind": "count", "n": 1}, looks=[True]),
            "not '\u0660.\u0660\u0665'": record(
                hypotheses=[{**hypotheses[0], "alpha": "\u0660.\u0660\u0665"}, *hypotheses[1:]]
            ),
            "exact number written as a string, such as": record(
                hypotheses=[{**hypotheses[0], "alpha": "0.0_5"}, *hypotheses[1:]]
            ),
            "runs past the last date there is": record(
                horizon={"kind": "days", "days": 10**9, "start": "2026-01-05"}, looks=[10**9]
            ),
            "before the record was registered on 2026-03-01": record(
                registered="2026-03-01", horizon={"kind": "days", "days": 3, "start": "2026-01-05"}, looks=[3]
            ),
        }
        for message, content in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregError, message):
                    load(self.write(content))

    def test_a_binomial_test_states_p0_and_a_sign_test_does_not(self):
        hypotheses = record()["hypotheses"]
        no_p0 = {k: v for k, v in hypotheses[2].items() if k != "p0"}
        cases = {
            "must state p0": [*hypotheses[:2], no_p0],
            "takes no p0": [{**hypotheses[0], "p0": "1/2"}, *hypotheses[1:]],
            r"defined only at p0 = 1/2, not 1/3": [
                *hypotheses[:2],
                {**hypotheses[2], "alternative": "two-sided", "p0": "1/3"},
            ],
            r"p0 must lie in \(0, 1\)": [*hypotheses[:2], {**hypotheses[2], "p0": "0"}],
        }
        for message, value in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregError, message):
                    load(self.write(record(hypotheses=value)))
        one_sided = load(self.write(record(hypotheses=[*hypotheses[:2], {**hypotheses[2], "p0": "1/3"}])))
        self.assertEqual(one_sided.hypotheses[2].p0, Fraction(1, 3))

    def test_a_days_horizon_states_its_start_and_its_looks_count_days(self):
        rule = load(self.write(record(horizon={"kind": "days", "days": 14, "start": "2026-01-05"}, looks=[14])))
        self.assertEqual((rule.horizon.kind, rule.horizon.size), ("days", 14))
        self.assertEqual((rule.horizon.start, rule.horizon.end), (date(2026, 1, 5), date(2026, 1, 19)))
        with self.assertRaisesRegex(PreregError, r"horizon lacks \['start'\]"):
            load(self.write(record(horizon={"kind": "days", "days": 14}, looks=[14])))

    def test_a_bound_artifact_must_be_unchanged_and_inside_the_folder(self):
        analysis = self.folder / "plan.md"
        analysis.write_text("the synthetic analysis plan\n", encoding="utf-8")
        digest = hashlib.sha256(analysis.read_bytes()).hexdigest()
        rule = load(self.write(record(bound_artifacts={"plan.md": digest})))
        self.assertEqual(dict(rule.bound_artifacts), {"plan.md": digest})
        self.assertEqual(evaluate(rule, sample()).n, 6)  # an intact rule with bound files is evaluated as it is
        analysis.write_text("the synthetic analysis plan, edited after registering\n", encoding="utf-8")
        with self.assertRaisesRegex(BoundArtifactError, "'plan.md' has changed"):
            load(self.write(record(bound_artifacts={"plan.md": digest})))
        with self.assertRaisesRegex(BoundArtifactError, "'gone.md' is missing"):
            load(self.write(record(bound_artifacts={"gone.md": digest})))
        for name in ("/etc/plan.md", "../plan.md", "sub\\plan.md", "", "./plan.md", "sub//plan.md"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(PreregError, "must be a plain relative path inside the record's folder"):
                    load(self.write(record(bound_artifacts={name: digest})))
        outside = Path(tempfile.mkdtemp(prefix="onus-prereg-outside-"))
        self.addCleanup(shutil.rmtree, outside)
        (outside / "plan.md").write_bytes(analysis.read_bytes())
        (self.folder / "linked.md").symlink_to(outside / "plan.md")
        linked = hashlib.sha256(analysis.read_bytes()).hexdigest()
        with self.assertRaisesRegex(PreregError, "'linked.md' must be a plain relative path inside"):
            load(self.write(record(bound_artifacts={"linked.md": linked})))
        # A symlink loop: Path.resolve raises RuntimeError on 3.11 and OSError from 3.13.
        for error in (RuntimeError("Symlink loop from 'loop.md'"), OSError(40, "Too many levels of symbolic links")):
            with self.subTest(error=type(error).__name__), mock.patch.object(Path, "resolve", side_effect=error):
                with self.assertRaisesRegex(BoundArtifactError, "'plan.md' cannot be resolved"):
                    load(self.write(record(bound_artifacts={"plan.md": linked})))
        with self.assertRaisesRegex(PreregError, "must name a lowercase hex sha256"):
            load(self.write(record(bound_artifacts={"plan.md": digest.upper()})))
        with self.assertRaisesRegex(PreregError, "bound_artifacts must be an object"):
            load(self.write(record(bound_artifacts=["plan.md"])))


class EvaluateTest(Folder):
    """evaluate is pure, refuses before the horizon, and uses exactly the units the horizon names."""

    def rule(self, **changes: object) -> Rule:
        return load(self.write(record(**changes)))

    def data(self) -> list[dict[str, Any]]:
        return sample()

    def test_exactly_the_first_n_units_in_order_are_used(self):
        rule = self.rule()
        result = evaluate(rule, self.data())
        self.assertEqual(result.n, 6)
        faster, clearer, completes = result.hypotheses
        # Units 1..6: faster has 6 wins; clearer 4 wins, 1 loss, 1 tie; completes 5 successes of 6.
        self.assertEqual(faster.result, sign_test(6, 0, ties=0, alternative="greater", method="exact"))
        self.assertEqual(clearer.result, sign_test(4, 1, ties=1, alternative="two-sided", method="exact"))
        self.assertEqual(completes.result, binomial_test(5, 6, p="1/2", alternative="greater", method="exact"))
        used = [
            {"unit": f"p{i}", "order": i, "outcomes": dict(unit_["outcomes"])}
            for i in range(1, 7)
            for unit_ in self.data()
            if unit_["participant"] == f"p{i}"
        ]
        canonical = json.dumps(used, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(result.data_sha256, hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual((result.prereg, result.experiment), (rule.id, rule.experiment))

    def test_each_family_is_adjusted_by_its_own_correction(self):
        result = evaluate(self.rule(), self.data())
        faster, clearer, completes = result.hypotheses
        expected = holm([faster.result.p_exact, clearer.result.p_exact])
        self.assertEqual([faster.adjusted_p, clearer.adjusted_p], expected)
        # faster's raw p is 1/64, clearer's 3/8; Holm doubles the smaller, so faster is met at 1/32 <= 0.05.
        self.assertEqual(faster.adjusted_p, Fraction(1, 32))
        self.assertTrue(faster.met)
        self.assertEqual(completes.adjusted_p, completes.result.p_exact)
        self.assertEqual(result.labels(), {"faster": "met", "clearer": "not met", "completes": "not met"})

    def test_a_family_is_decided_on_its_adjusted_p_value_not_the_raw_one(self):
        # Two members at raw 1/32 each: raw, each would be met at 0.05; Holm makes both 1/16, so neither is.
        hypotheses = record()["hypotheses"]
        data = [unit(f"p{i}", i, "win", "win", "success") for i in range(1, 7)]
        rule = self.rule(
            hypotheses=[hypotheses[0], {**hypotheses[1], "alternative": "greater"}, hypotheses[2]],
            horizon={"kind": "count", "n": 5},
            looks=[5],
        )
        faster, clearer, _ = evaluate(rule, data).hypotheses
        self.assertEqual((faster.result.p_exact, clearer.result.p_exact), (Fraction(1, 32), Fraction(1, 32)))
        self.assertEqual((faster.adjusted_p, clearer.adjusted_p), (Fraction(1, 16), Fraction(1, 16)))
        self.assertEqual((faster.met, clearer.met), (False, False))

    def test_a_count_horizon_refuses_too_few_units(self):
        with self.assertRaisesRegex(HorizonNotReachedError, "the horizon is 6 units; the data holds 5"):
            evaluate(self.rule(), self.data()[:5])
        self.assertEqual(
            status(self.rule(), self.data()[:5]), {"faster": "pending", "clearer": "pending", "completes": "pending"}
        )
        self.assertEqual(status(self.rule(), self.data()), evaluate(self.rule(), self.data()).labels())

    def test_a_count_horizon_needs_one_unambiguous_order(self):
        data = self.data()
        data[0] = unit("p8", 1, "loss", "loss", "failure")
        with self.assertRaisesRegex(PreregError, "'enrolled' has repeated values"):
            evaluate(self.rule(), data)
        data[0] = unit("p8", "8", "loss", "loss", "failure")
        with self.assertRaisesRegex(PreregError, "all ints or all strings"):
            evaluate(self.rule(), data)

    def test_a_days_horizon_waits_for_its_window_and_uses_the_units_inside_it(self):
        rule = self.rule(horizon={"kind": "days", "days": 3, "start": "2026-01-05"}, looks=[3])
        data = [
            unit("early", "2026-01-04", "loss", "loss", "failure"),
            unit("a", "2026-01-05", "win", "win", "success"),
            unit(7, "2026-01-07", "win", "loss", "success"),
            unit("b", "2026-01-06", "win", "win", "failure"),
            unit("late", "2026-01-08", "loss", "loss", "failure"),
        ]
        with self.assertRaisesRegex(PreregError, "needs as_of"):
            evaluate(rule, data)
        with self.assertRaisesRegex(HorizonNotReachedError, r"runs to 2026-01-08 \(exclusive\); as_of is 2026-01-07"):
            evaluate(rule, data, as_of=date(2026, 1, 7))
        self.assertEqual(set(status(rule, data, as_of=date(2026, 1, 7)).values()), {"pending"})
        result = evaluate(rule, data, as_of=date(2026, 1, 8))
        self.assertEqual(result.n, 3)
        self.assertEqual(result.hypotheses[0].result, sign_test(3, 0, ties=0, alternative="greater", method="exact"))
        self.assertEqual(
            result.hypotheses[2].result, binomial_test(2, 3, p="1/2", alternative="greater", method="exact")
        )
        data.append(unit("c", "2026-1-06", "win", "win", "success"))
        with self.assertRaisesRegex(PreregError, "must be a date written YYYY-MM-DD"):
            evaluate(rule, data, as_of=date(2026, 1, 8))

    def test_a_malformed_unit_is_refused(self):
        good = self.data()
        cases: dict[str, list[Any]] = {
            "unit 0 must be a mapping": [["p1", 1]] + good,
            "unit 0 lacks the field 'enrolled'": [{"participant": "p9", "outcomes": {}}] + good,
            r"unit 0's 'participant' must be a string or an int": [unit(True, 9, "win", "win", "success")] + good,
            "must be distinct": [unit("p1", 9, "win", "win", "success")] + good,
            r"must record an outcome for exactly \['clearer', 'completes', 'faster'\]": [
                {**unit("p0", 0, "win", "win", "success"), "outcomes": {"faster": "win"}}
            ]
            + good,
            r"records 'success' for 'faster', a sign_test": [unit("p0", 0, "success", "win", "success")] + good,
            r"records 'win' for 'completes', a binomial_test": [unit("p0", 0, "win", "win", "win")] + good,
        }
        for message, data in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(PreregError, message):
                    evaluate(self.rule(), data)

    def test_only_the_used_units_outcomes_are_checked_and_hashed(self):
        data = self.data()
        data[0] = unit("p8", 8, "unrecorded", "unrecorded", "unrecorded", note="after the horizon")
        data[1] = unit("p3", 3, "win", "loss", "success", note="a field the rule does not read")
        self.assertEqual(evaluate(self.rule(), data), evaluate(self.rule(), self.data()))

    def test_a_rule_changed_after_loading_is_refused(self):
        rule = self.rule()
        with self.assertRaises(TypeError):
            rule.families["primary"] = "benjamini-hochberg"  # type: ignore[index]
        widened = dataclasses.replace(rule, horizon=Horizon("count", 8, None), looks=(8,))
        with self.assertRaisesRegex(PreregError, f"rule '{rule.id}' no longer matches the record"):
            evaluate(widened, self.data())
        renamed = dataclasses.replace(rule, id="layout@000000000000")
        with self.assertRaisesRegex(PreregError, "no longer matches the record"):
            evaluate(renamed, self.data())

    def test_a_unit_s_text_and_a_days_as_of_are_checked(self):
        with self.assertRaisesRegex(PreregError, "is not valid Unicode"):
            evaluate(self.rule(), [unit("\ud800", 0, "win", "win", "success"), *self.data()])
        with self.assertRaisesRegex(PreregError, "as a mapping by hypothesis name"):
            evaluate(self.rule(), [{**unit("p0", 0, "win", "win", "success"), "outcomes": {1: "win"}}, *self.data()])
        rule = self.rule(horizon={"kind": "days", "days": 3, "start": "2026-01-05"}, looks=[3])
        with self.assertRaisesRegex(PreregError, "as_of must be a date"):
            evaluate(rule, [], as_of=datetime(2026, 1, 9, tzinfo=UTC))

    def test_a_days_evaluation_does_not_depend_on_how_same_day_units_are_listed(self):
        rule = self.rule(horizon={"kind": "days", "days": 1, "start": "2026-01-05"}, looks=[1])
        data = [
            unit("a", "2026-01-05", "win", "win", "success"),
            unit(2, "2026-01-05", "loss", "win", "failure"),
            unit("c", "2026-01-05", "win", "tie", "success"),
        ]
        forward = evaluate(rule, data, as_of=date(2026, 1, 6))
        self.assertEqual(evaluate(rule, list(reversed(data)), as_of=date(2026, 1, 6)), forward)

    def test_evaluate_changes_nothing_it_is_given_and_writes_nothing(self):
        rule, data = self.rule(), self.data()
        before, files = copy.deepcopy(data), sorted(self.folder.iterdir())
        evaluate(rule, data)
        self.assertEqual(data, before)
        self.assertEqual(sorted(self.folder.iterdir()), files)


class ReadTest(Folder):
    """record_read appends one line per read and returns its receipt."""

    def test_a_reads_file_whose_last_write_was_cut_short_is_not_appended_to(self):
        rule = load(self.write(record()))
        result = evaluate(rule, sample())
        reads = self.folder / "reads.jsonl"
        reads.write_text('{"schema":"read/1","prereg":', encoding="utf-8")
        with self.assertRaisesRegex(PreregError, "does not end in a newline"):
            record_read(rule, result, reads_path=reads)
        self.assertEqual(reads.read_text(encoding="utf-8"), '{"schema":"read/1","prereg":')

    def test_each_read_appends_a_line_and_its_receipt_names_it(self):
        rule = load(self.write(record()))
        result = evaluate(rule, sample())
        reads = self.folder / "reads.jsonl"
        when = datetime(2026, 1, 20, 9, 30, tzinfo=timezone(timedelta(hours=2)))
        first = record_read(rule, result, reads_path=reads, now=when)
        second = record_read(rule, result, reads_path=reads, now=when + timedelta(days=1))
        lines = reads.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            json.loads(lines[0]),
            {
                "schema": "read/1",
                "prereg": rule.id,
                "experiment": rule.experiment,
                "data_sha256": result.data_sha256,
                "n": 6,
                "labels": {"faster": "met", "clearer": "not met", "completes": "not met"},
                "at": "2026-01-20T07:30:00+00:00",
                "onus": onus.__version__,
            },
        )
        self.assertEqual(first.line_sha256, hashlib.sha256(lines[0].encode()).hexdigest())
        self.assertEqual(second.line_sha256, hashlib.sha256(lines[1].encode()).hexdigest())
        self.assertEqual((first.prereg, first.data_sha256, first.reads_path), (rule.id, result.data_sha256, reads))
        self.assertEqual(first.at, datetime(2026, 1, 20, 7, 30, tzinfo=UTC))

    def test_a_read_is_recorded_only_against_its_own_rule_and_a_timezone(self):
        rule = load(self.write(record()))
        result = evaluate(rule, sample())
        other = load(self.write(record(experiment="another synthetic experiment"), name="other.json"))
        reads = self.folder / "reads.jsonl"
        with self.assertRaisesRegex(PreregError, rf"the evaluation is of '{rule.id}', not of '{other.id}'"):
            record_read(other, result, reads_path=reads)
        with self.assertRaisesRegex(ValueError, "must carry its timezone"):
            record_read(rule, result, reads_path=reads, now=datetime(2026, 1, 20, 9, 30))
        self.assertFalse(reads.exists())
        tampered = dataclasses.replace(rule, experiment="a different synthetic experiment")
        with self.assertRaisesRegex(PreregError, "no longer matches the record"):
            record_read(tampered, result, reads_path=reads)
        forged = Evaluation(rule.id, rule.experiment, 0, "0" * 64, ())
        with self.assertRaisesRegex(PreregError, "does not hold a result for each"):
            record_read(rule, forged, reads_path=reads)
        flipped = dataclasses.replace(
            result, hypotheses=tuple(dataclasses.replace(h, met=not h.met) for h in result.hypotheses)
        )
        with self.assertRaisesRegex(PreregError, "'faster' is labelled 'not met', which its adjusted p-value"):
            record_read(rule, flipped, reads_path=reads)
        moved = dataclasses.replace(
            result, hypotheses=(dataclasses.replace(result.hypotheses[0], alpha=Fraction(1, 2)), *result.hypotheses[1:])
        )
        with self.assertRaisesRegex(PreregError, "'faster' states a family or alpha"):
            record_read(rule, moved, reads_path=reads)
        self.assertFalse(reads.exists())
        receipt = record_read(rule, result, reads_path=reads)
        self.assertEqual(receipt.at.tzinfo, UTC)
        self.assertLess(abs(datetime.now(UTC) - receipt.at), timedelta(minutes=5))
