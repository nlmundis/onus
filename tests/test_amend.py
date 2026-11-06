"""onus.prereg amendments: files bound by sign-offs, what each one touches, and the post hoc label it leaves.

Every ledger here is a scratch file written by hand in a temporary folder, as tests/test_signoff.py writes some, and
no test writes a line to a ledger anyone relies on.
"""

import dataclasses
import hashlib
import json
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any
from unittest import mock

from onus.prereg import Amendment, PreregError, ReadReceipt, Rule, _rule, evaluate, load, prereg_id, record_read
from onus.prereg._reads import parse_line
from onus.report import receipt_from_line, render
from onus.report._render import COUNT_HORIZON
from onus.signoff import Check, check_signoff
from tests.test_prereg import Folder, at, days_record, days_sample, record, sample

BEFORE_READ = "2026-01-09T10:00:00+00:00"
READ = "2026-01-10T10:00:00+00:00"
AFTER_READ = "2026-01-11T10:00:00+00:00"
REMOVED = object()


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def amendment(amends: str, content: dict[str, Any], reason: str = "a synthetic correction") -> dict[str, Any]:
    return {"schema": "amend/1", "amends": amends, "reason": reason, "record": content}


def with_hypothesis(content: dict[str, Any], which: str, **changes: object) -> dict[str, Any]:
    """``content`` with the fields of its hypothesis ``which`` changed."""
    hypotheses = [{**h, **changes} if h["name"] == which else h for h in content["hypotheses"]]
    return {**content, "hypotheses": hypotheses}


class Amended(Folder):
    """A folder with a record, a scratch ledger signed by hand, and ways to write and sign amendments beside it."""

    def setUp(self):
        super().setUp()
        self.ledger = self.folder / "ledger.jsonl"
        self.ledger_lines: list[str] = []
        self.reads = self.folder / "reads.jsonl"
        self.base = self.write(record())

    def sign(
        self,
        path: Path,
        when: str,
        *,
        artifact: str | None = None,
        content: bytes | None = None,
        bound: dict[str, str] | None = None,
    ) -> None:
        """Append a signoff/1 line signing ``path``'s content (or ``content``) at ``when``, as record would."""
        artifact = artifact or f"prereg:{path.name}"
        earlier = [json.loads(line) for line in self.ledger_lines if json.loads(line)["artifact"] == artifact]
        data = path.read_bytes() if content is None else content
        line = {
            "schema": "signoff/1",
            "artifact": artifact,
            "sha256": sha(data),
            "bytes": len(data),
            "bound": bound or {},
            "supersedes": sha(json.dumps(earlier[-1], sort_keys=True, separators=(",", ":"))) if earlier else None,
            "reviewed_by": "A Reviewer",
            "at": when,
            "tool": "onus 0.0.0",
            "prev": sha(self.ledger_lines[-1]) if self.ledger_lines else None,
        }
        self.ledger_lines.append(json.dumps(line, sort_keys=True, separators=(",", ":")))
        self.ledger.write_text("".join(text + "\n" for text in self.ledger_lines), encoding="utf-8")

    def amend(
        self, content: dict[str, Any], day: str = "2026-01-10", *, signed: str | None = AFTER_READ, amends: str = ""
    ) -> Path:
        """Write ``content`` as the amendment of the newest rule, dated ``day``, and sign it at ``signed``."""
        path = self.write(amendment(amends or self.newest_id(), content), name=f"layout.amend-{day}.json")
        if signed is not None:
            self.sign(path, signed)
        return path

    def reset(self) -> None:
        """Remove every amendment and the ledger, so a subtest starts from the record alone."""
        for stale in self.folder.glob("layout.amend-*"):
            stale.unlink()
        self.ledger.unlink(missing_ok=True)
        self.ledger_lines = []

    def newest_id(self) -> str:
        names = sorted(p.name for p in self.folder.glob("layout.amend-*.json"))
        return prereg_id(self.folder / names[-1]) if names else prereg_id(self.base)

    def loaded(self) -> Rule:
        return load(self.base, ledger=self.ledger)

    def read(
        self, rule: Rule, when: str = READ, data: list[dict[str, Any]] | None = None, **kwargs: str
    ) -> ReadReceipt:
        with mock.patch("onus.prereg._evaluate._now", return_value=at(when)):
            return record_read(
                rule, evaluate(rule, sample() if data is None else data), reads_path=self.reads, **kwargs
            )

    def last_line(self) -> dict[str, Any]:
        line: dict[str, Any] = json.loads(self.reads.read_text(encoding="utf-8").splitlines()[-1])
        return line


class LoadTest(Amended):
    """load applies each signed amendment beside a record, in order, and refuses on any doubt about one."""

    def test_a_record_with_no_amendment_loads_as_before_with_or_without_a_ledger(self):
        self.assertEqual(load(self.base, ledger=self.ledger), load(self.base))
        self.assertEqual(load(self.base).amendments, ())

    def test_a_signed_amendment_gives_the_rule_its_record_and_its_id(self):
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        rule = self.loaded()
        self.assertEqual(rule.id, prereg_id(path))
        self.assertEqual(rule.sha256, sha(path.read_bytes()))
        self.assertEqual(rule.raw, self.base.read_bytes())
        self.assertEqual(rule.hypotheses[2].alpha, Fraction(1, 20))
        self.assertEqual(
            rule.amendments,
            (
                Amendment(
                    name=path.name,
                    id=prereg_id(path),
                    reason="a synthetic correction",
                    signed_at=datetime.fromisoformat(AFTER_READ),
                    touches=("completes",),
                    raw=path.read_bytes(),
                ),
            ),
        )

    def test_amendments_apply_oldest_first_each_naming_the_one_before(self):
        first = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), "2026-01-10")
        second = self.amend(with_hypothesis(record(), "completes", alpha="0.02"), "2026-01-12")
        rule = self.loaded()
        self.assertEqual(rule.id, prereg_id(second))
        self.assertEqual([a.name for a in rule.amendments], [first.name, second.name])
        self.assertEqual(str(rule.hypotheses[2].alpha), "1/50")

    def test_an_amendment_that_names_another_rule_than_the_one_before_it_is_refused(self):
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), "2026-01-10")
        self.amend(with_hypothesis(record(), "completes", alpha="0.02"), "2026-01-12", amends=prereg_id(self.base))
        with self.assertRaisesRegex(
            PreregError, r"amends 'layout@[0-9a-f]{12}', but the rule before it is 'layout\.amend-2026-01-10@"
        ):
            self.loaded()

    def test_without_a_ledger_a_record_with_an_amendment_beside_it_is_refused(self):
        self.amend(record(provenance={"author": "another"}))
        with self.assertRaisesRegex(
            PreregError, "has the amendment layout.amend-2026-01-10.json beside it: load it with ledger="
        ):
            load(self.base)

    def test_an_amendment_not_signed_is_refused_whatever_the_ledger_says_instead(self):
        content = with_hypothesis(record(), "completes", alpha="0.05")
        cases = {
            "UNSIGNED": lambda path: None,
            "CHANGED": lambda path: self.sign(path, AFTER_READ, content=b"what was signed\n"),
            "UNSIGNED as another artifact": lambda path: self.sign(path, AFTER_READ, artifact="prereg:other.json"),
            "CORRUPT": lambda path: self.ledger.write_text("not a ledger\n", encoding="utf-8"),
        }
        for status, prepare in cases.items():
            with self.subTest(status):
                self.reset()
                path = self.amend(content, signed=None)
                prepare(path)
                with self.assertRaisesRegex(PreregError, f"is not signed: .* says {status.split()[0]} for 'prereg:"):
                    self.loaded()

    def test_a_revoked_amendment_is_refused(self):
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        signed = self.ledger_lines[-1]
        revocation = {
            **json.loads(signed),
            "sha256": None,
            "bytes": None,
            "supersedes": sha(signed),
            "at": "2026-01-12T10:00:00+00:00",
            "prev": sha(signed),
        }
        self.ledger_lines.append(json.dumps(revocation, sort_keys=True, separators=(",", ":")))
        self.ledger.write_text("".join(text + "\n" for text in self.ledger_lines), encoding="utf-8")
        with self.assertRaisesRegex(PreregError, f"{path.name} is not signed: .* says REVOKED"):
            self.loaded()

    def test_an_amendment_changed_after_its_sign_off_is_refused(self):
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        path.write_text(json.dumps(amendment(prereg_id(self.base), record(provenance={"author": "edited"}))))
        with self.assertRaisesRegex(PreregError, "says CHANGED"):
            self.loaded()

    def test_an_amendment_outside_the_ledgers_folder_is_refused(self):
        self.amend(record(provenance={"author": "another"}))
        elsewhere = self.folder / "elsewhere"
        elsewhere.mkdir()
        with self.assertRaisesRegex(PreregError, "is not inside .*elsewhere, the folder of the ledger that signs it"):
            load(self.base, ledger=elsewhere / "ledger.jsonl")

    def test_a_file_named_as_an_amendment_is_but_not_one_is_refused_not_passed_over(self):
        for name in ("layout.amend-later.json", "layout.amend-2026-01-10.txt", "layout.amend-2026-02-30.json"):
            with self.subTest(name):
                stray = self.folder / name
                stray.write_text("{}")
                with self.assertRaisesRegex(PreregError, f"{name}"):
                    self.loaded()
                stray.unlink()

    def test_an_amendment_dated_before_its_record_was_registered_is_refused(self):
        self.amend(record(provenance={"author": "another"}), "2026-01-04")
        with self.assertRaisesRegex(PreregError, "is dated before 'layout@[0-9a-f]{12}' was registered, on 2026-01-05"):
            self.loaded()

    def test_an_amendment_is_not_loaded_as_a_record_of_its_own(self):
        path = self.amend(record(provenance={"author": "another"}))
        with self.assertRaisesRegex(PreregError, "is an amendment: load the record it amends"):
            load(path, ledger=self.ledger)

    def test_a_malformed_amendment_is_refused_and_named(self):
        good = amendment(prereg_id(self.base), record())
        cases: dict[str, object] = {
            "another schema": {**good, "schema": "amend/2"},
            "an extra key": {**good, "note": "x"},
            "a missing key": {k: v for k, v in good.items() if k != "reason"},
            "a blank reason": {**good, "reason": " "},
            "a reason on two lines": {**good, "reason": "one\ntwo"},
            "a record load refuses": {**good, "record": record(cluster_key="site")},
            "a float": json.dumps(good).replace('"0.05"', "0.05", 1),
            "not an object": [],
        }
        for label, content in cases.items():
            with self.subTest(label):
                self.reset()
                text = content if isinstance(content, str) else json.dumps(content)
                path = self.write(text, name="layout.amend-2026-01-10.json")
                self.sign(path, AFTER_READ)
                with self.assertRaisesRegex(PreregError, "layout.amend-2026-01-10.json"):
                    self.loaded()

    def test_a_rule_whose_amendments_were_replaced_no_longer_matches_its_files(self):
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        rule = self.loaded()
        changed = {
            "no amendments": dataclasses.replace(rule, amendments=()),
            "other touches": dataclasses.replace(
                rule, amendments=(dataclasses.replace(rule.amendments[0], touches=()),)
            ),
            "the base record's id": dataclasses.replace(rule, id=prereg_id(self.base)),
        }
        for label, wrong in changed.items():
            with self.subTest(label), self.assertRaisesRegex(PreregError, "no longer matches"):
                evaluate(wrong, sample())
        self.assertEqual(evaluate(rule, sample()).prereg, rule.id)
        renamed = dataclasses.replace(rule.amendments[0], name="other.amend-2026-01-10.json")
        with self.assertRaisesRegex(PreregError, "is not named as an amendment of 'layout' is"):
            evaluate(dataclasses.replace(rule, amendments=(renamed,)), sample())


class LoadMoreTest(Amended):
    """load's refusals the first review found unpinned: case, the sign-off's path, bound files, and exact bytes."""

    def test_a_ledger_that_cannot_be_read_refuses_the_amendment_as_a_prereg_error(self):
        self.amend(record())
        self.ledger.unlink()
        self.ledger.mkdir()
        with self.assertRaisesRegex(PreregError, "cannot be checked against the ledger"):
            load(self.base, ledger=self.ledger)

    def test_a_ledger_in_a_symlink_loop_refuses_the_amendment_as_a_prereg_error(self):
        self.amend(record())
        self.ledger.unlink()
        self.ledger.symlink_to(self.ledger)
        with self.assertRaisesRegex(PreregError, "cannot be checked against the ledger"):
            load(self.base, ledger=self.ledger)
        with (
            mock.patch.object(Path, "resolve", side_effect=RuntimeError("Symlink loop")),
            self.assertRaisesRegex(PreregError, "cannot be checked against the ledger"),
        ):
            load(self.base, ledger=self.ledger)

    def test_an_amendment_cannot_move_the_day_its_record_was_registered(self):
        self.amend(record(registered="2026-01-06"))
        with self.assertRaisesRegex(PreregError, "an amendment cannot move the day a record was registered"):
            self.loaded()

    def test_a_record_opened_in_another_case_finds_its_amendments_and_refuses_them(self):
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        # Where the file system ignores case this names the record itself; where it does not, it is a copy, as the
        # same bytes under the other spelling. Either way the amendments are found and refused, on every machine.
        (self.folder / "LAYOUT.json").write_bytes(self.base.read_bytes())
        with self.assertRaisesRegex(PreregError, "layout.amend-2026-01-10.json beside LAYOUT.json is named as"):
            load(self.folder / "LAYOUT.json", ledger=self.ledger)

    def test_an_amendment_in_another_unicode_normal_form_is_seen_not_passed_over(self):
        decomposed, composed = "cafe\u0301", "caf\u00e9"
        base = self.write(record(), name=f"{decomposed}.json")
        self.write(
            amendment(prereg_id(base), record(provenance={"author": "another"})),
            name=f"{composed}.amend-2026-01-10.json",
        )
        with self.assertRaisesRegex(PreregError, "amend-2026-01-10.json"):
            load(base, ledger=self.ledger)

    def test_a_record_with_no_amendment_loads_under_either_unicode_normal_form(self):
        decomposed, composed = "cafe\u0301", "caf\u00e9"
        self.write(record(), name=f"{decomposed}.json")
        # Where the file system ignores normal form this opens the record by its other spelling, which a check on
        # the spelling would refuse; where it does not, it is a copy under that spelling. It loads on every machine.
        self.write(record(), name=f"{composed}.json")
        self.assertEqual(load(self.folder / f"{composed}.json").amendments, ())

    def test_an_amendment_named_in_another_case_is_refused_as_misnamed(self):
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        path.rename(self.folder / "Layout.amend-2026-01-10.json")
        with self.assertRaisesRegex(PreregError, "Layout.amend-2026-01-10.json beside layout.json is named as"):
            self.loaded()

    def test_the_sign_off_names_the_amendments_path_from_the_ledgers_folder(self):
        sub = self.folder / "sub"
        sub.mkdir()
        self.base = sub / "layout.json"
        self.base.write_text(json.dumps(record()))
        path = sub / "layout.amend-2026-01-10.json"
        path.write_text(
            json.dumps(amendment(prereg_id(self.base), with_hypothesis(record(), "completes", alpha="0.05")))
        )
        self.sign(path, AFTER_READ, artifact="prereg:layout.amend-2026-01-10.json")
        with self.assertRaisesRegex(PreregError, "says UNSIGNED for 'prereg:sub/layout.amend-2026-01-10.json'"):
            self.loaded()
        self.sign(path, AFTER_READ, artifact="prereg:sub/layout.amend-2026-01-10.json")
        self.assertEqual(self.loaded().id, prereg_id(path))

    def test_an_amendment_whose_bound_file_changed_since_its_sign_off_is_refused(self):
        bound = self.folder / "bound.txt"
        bound.write_bytes(b"synthetic\n")
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=None)
        self.sign(path, AFTER_READ, bound={"bound.txt": sha(b"synthetic\n")})
        self.assertEqual(len(self.loaded().amendments), 1)
        bound.write_bytes(b"changed\n")
        with self.assertRaisesRegex(PreregError, "says CHANGED"):
            self.loaded()

    def test_a_sign_off_of_other_bytes_than_those_read_is_refused(self):
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"))
        real = check_signoff(self.ledger, f"prereg:{path.name}", path)
        assert real.line is not None
        other = Check(real.status, real.detail, dataclasses.replace(real.line, sha256=sha(b"other bytes\n")))
        with mock.patch("onus.signoff.check_signoff", return_value=other):
            with self.assertRaisesRegex(PreregError, "is not signed: .* says SIGNED"):
                self.loaded()


class TouchesTest(Amended):
    """What an amendment touches: a hypothesis's own fields, its family, and the fields every result depends on."""

    def setUp(self):
        super().setUp()
        (self.folder / "notes.txt").write_bytes(b"synthetic notes\n")

    def test_every_field_of_a_rule_is_classified(self):
        # A field added to Rule must be placed here, in what touches every hypothesis or in what touches none, so
        # that _touches never passes over a change it was not told about.
        shared = set(_rule._SHARED)
        per_hypothesis = {"hypotheses", "families"}
        touches_none = {"experiment", "provenance"}
        not_record_fields = {"id", "sha256", "raw", "amendments"}
        fields = {field.name for field in dataclasses.fields(Rule)}
        self.assertEqual(fields, shared | per_hypothesis | touches_none | not_record_fields)
        self.assertEqual(len(fields), len(shared) + len(per_hypothesis) + len(touches_none) + len(not_record_fields))

    def touches(self, content: dict[str, Any]) -> tuple[str, ...]:
        self.amend(content)
        return self.loaded().amendments[-1].touches

    def test_each_kind_of_change_touches_what_it_should(self):
        everyone = ("faster", "clearer", "completes")
        cases: dict[str, tuple[dict[str, Any], tuple[str, ...]]] = {
            "a hypothesis's alpha": (with_hypothesis(record(), "completes", alpha="0.05"), ("completes",)),
            "a hypothesis's alternative": (with_hypothesis(record(), "faster", alternative="two-sided"), ("faster",)),
            "a family's correction": (
                record(
                    families={
                        "primary": {"correction": "benjamini-hochberg"},
                        "guard": {"correction": "benjamini-hochberg"},
                    }
                ),
                ("faster", "clearer"),
            ),
            "a family's members": (
                with_hypothesis(record(), "clearer", family="guard", alpha="0.1"),
                ("faster", "clearer", "completes"),
            ),
            "a renamed hypothesis": (with_hypothesis(record(), "completes", name="finishes"), ("finishes",)),
            "the horizon": (record(horizon={"kind": "count", "n": 7}, looks=[7]), everyone),
            "the order key": (record(order_key="joined"), everyone),
            "the unit": (record(unit="person"), everyone),
            "a bound artifact": (record(bound_artifacts={"notes.txt": sha(b"synthetic notes\n")}), everyone),
            "the experiment's name": (record(experiment="a renamed synthetic comparison"), ()),
            "the provenance": (record(provenance={"author": "another synthetic example"}), ()),
            "the hypotheses' order": ({**record(), "hypotheses": record()["hypotheses"][::-1]}, ()),
        }
        for label, (content, expected) in cases.items():
            with self.subTest(label):
                self.reset()
                self.assertEqual(set(self.touches(content)), set(expected))


class PostHocTest(Amended):
    """A hypothesis an amendment touched that was signed after the hypothesis was first read is labelled post hoc."""

    def test_an_amendment_signed_after_a_read_labels_what_it_touches_post_hoc(self):
        self.read(load(self.base))
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        line = self.last_line()
        self.assertEqual(
            (line["schema"], line["amendments"], line["post_hoc"]), ("read/3", [prereg_id(path)], ["completes"])
        )

    def test_an_amendment_signed_before_any_read_labels_nothing(self):
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=BEFORE_READ)
        self.read(self.loaded())
        self.assertEqual(self.last_line()["post_hoc"], [])

    def test_the_first_read_decides_and_not_the_latest(self):
        # Read before the amendment, then twice after it: the latest earlier read applied it, the first did not.
        self.read(load(self.base), READ)
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        self.read(self.loaded(), "2026-01-13T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], ["completes"])

    def test_a_hypothesis_added_after_a_read_counts_the_experiments_first_read_as_its_own(self):
        first = self.read(load(self.base))
        self.amend(with_hypothesis(record(), "completes", name="finishes"), signed=AFTER_READ)
        data = [
            {**u, "outcomes": {("finishes" if k == "completes" else k): v for k, v in u["outcomes"].items()}}
            for u in sample()
        ]
        # Its labels name another hypothesis, so the seal holds it to the first read.
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00", data=data, supersedes=first.line_sha256, reason="renamed")
        self.assertEqual(self.last_line()["post_hoc"], ["finishes"])
        # And on every later read, whose first read of "finishes" would otherwise be the read just above.
        receipt = self.read(
            self.loaded(), "2026-01-13T10:00:00+00:00", data=data, supersedes=first.line_sha256, reason="again"
        )
        self.assertEqual(self.last_line()["post_hoc"], ["finishes"])
        self.assertIn("post hoc", render(self.loaded(), data, "finishes", receipt=receipt, reads_path=self.reads))

    def test_an_amendment_that_touches_nothing_labels_nothing(self):
        self.read(load(self.base))
        self.amend(record(provenance={"author": "another synthetic example"}), signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], [])

    def test_a_read_of_another_experiment_does_not_count_as_a_first_read(self):
        other = load(self.write(record(experiment="another synthetic experiment"), name="other.json"))
        self.read(other)
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], [])

    def test_render_says_post_hoc_and_names_the_amendment(self):
        self.read(load(self.base))
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        rule = self.loaded()
        receipt = self.read(rule, "2026-01-12T10:00:00+00:00")
        sentence = render(rule, sample(), "completes", receipt=receipt, reads_path=self.reads)
        self.assertTrue(
            sentence.startswith(f"completes: not met; post hoc: amended by {prereg_id(path)} after its first read; "),
            sentence,
        )
        self.assertNotIn("post hoc", render(rule, sample(), "faster", receipt=receipt, reads_path=self.reads))

    def test_render_refuses_a_line_whose_post_hoc_or_amendments_were_edited(self):
        self.read(load(self.base))
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        rule = self.loaded()
        self.read(rule, "2026-01-12T10:00:00+00:00")
        lines = self.reads.read_text(encoding="utf-8").splitlines()
        for field, value in dict[str, list[str]]({"post_hoc": [], "amendments": []}).items():
            with self.subTest(field):
                edited = json.dumps({**json.loads(lines[-1]), field: value}, sort_keys=True, separators=(",", ":"))
                self.reads.write_text(lines[0] + "\n" + edited + "\n", encoding="utf-8")
                receipt = receipt_from_line(self.reads, sha(edited))
                with self.assertRaisesRegex(PreregError, rf"its \['{field}'\] differ"):
                    render(rule, sample(), "completes", receipt=receipt, reads_path=self.reads)

    def test_an_early_read_still_says_it_is_post_hoc(self):
        # The window closes everywhere at 2026-01-08 12:00 UTC, so both reads here are early.
        self.base = self.write(days_record())
        as_of = date(2026, 1, 8)
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T09:00:00+00:00")):
            rule = load(self.base)
            record_read(rule, evaluate(rule, days_sample(), as_of=as_of), reads_path=self.reads)
        path = self.amend(with_hypothesis(days_record(), "completes", alpha="0.05"), signed="2026-01-08T10:00:00+00:00")
        rule = self.loaded()
        with mock.patch("onus.prereg._evaluate._now", return_value=at("2026-01-08T11:00:00+00:00")):
            receipt = record_read(rule, evaluate(rule, days_sample(), as_of=as_of), reads_path=self.reads)
        sentence = render(rule, days_sample(), "completes", receipt=receipt, reads_path=self.reads, as_of=as_of)
        self.assertTrue(
            sentence.startswith(
                "completes: read early (read at 2026-01-08T11:00:00+00:00; window closed at 2026-01-08T12:00:00+00:00);"
                f" post hoc: amended by {prereg_id(path)} after its first read; prereg {rule.id}"
            ),
            sentence,
        )
        self.assertNotIn(COUNT_HORIZON, sentence)


class PostHocMoreTest(Amended):
    """Post hoc is decided by what a hypothesis's first read applied, never by a clock."""

    def test_an_amendment_signed_before_a_read_but_placed_after_it_is_post_hoc(self):
        self.read(load(self.base))
        path = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=BEFORE_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        self.assertEqual(
            (self.last_line()["post_hoc"], self.last_line()["amendments"]), (["completes"], [prereg_id(path)])
        )

    def test_a_backdated_sign_off_time_on_the_rule_does_not_move_the_label(self):
        self.read(load(self.base))
        self.amend(with_hypothesis(record(), "completes", alpha="0.05"), signed=AFTER_READ)
        rule = self.loaded()
        backdated = dataclasses.replace(
            rule.amendments[0], signed_at=datetime.fromisoformat("2000-01-01T00:00:00+00:00")
        )
        self.read(dataclasses.replace(rule, amendments=(backdated,)), "2026-01-12T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], ["completes"])

    def test_labels_are_written_sorted_by_name(self):
        self.read(load(self.base))
        families = {"primary": {"correction": "benjamini-hochberg"}, "guard": {"correction": "benjamini-hochberg"}}
        self.amend(record(families=families), signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-12T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], ["clearer", "faster"])

    def test_the_amendment_named_is_the_oldest_that_made_it_post_hoc(self):
        self.read(load(self.base))
        first = self.amend(with_hypothesis(record(), "completes", alpha="0.05"), "2026-01-10")
        self.amend(with_hypothesis(record(), "completes", alpha="0.02"), "2026-01-12")
        rule = self.loaded()
        receipt = self.read(rule, "2026-01-13T10:00:00+00:00")
        sentence = render(rule, sample(), "completes", receipt=receipt, reads_path=self.reads)
        self.assertIn(f"post hoc: amended by {prereg_id(first)} after its first read", sentence)

    def test_an_amendment_that_renames_the_experiment_is_related_to_the_records_reads_by_its_stem(self):
        # The first read is under one amendment, and a second amendment renames the experiment, so only the record's
        # stem relates the reads: through the rule's id, which names an amendment, and through the earlier line's.
        self.amend(record(provenance={"author": "another synthetic example"}), "2026-01-06", signed=BEFORE_READ)
        self.read(self.loaded())
        renamed = with_hypothesis(record(experiment="a renamed synthetic comparison"), "completes", alpha="0.05")
        self.amend(renamed, "2026-01-12", signed=AFTER_READ)
        self.read(self.loaded(), "2026-01-13T10:00:00+00:00")
        self.assertEqual(self.last_line()["post_hoc"], ["completes"])
        # And the seal holds a read whose labels the renaming amendment changed to the first read.
        self.reset()
        self.reads.unlink()
        self.read(load(self.base))
        loosened = with_hypothesis(record(experiment="a renamed synthetic comparison"), "completes", alpha="0.2")
        self.amend(loosened, "2026-01-12", signed=AFTER_READ)
        with self.assertRaisesRegex(PreregError, "was already read on other data or with other labels"):
            self.read(self.loaded(), "2026-01-13T10:00:00+00:00")


class CountHorizonTest(Amended):
    """Every count-horizon sentence discloses that its units' dates are not checked against registration (E24)."""

    def test_a_count_horizon_sentence_says_so_and_a_days_one_does_not(self):
        rule = load(self.base)
        receipt = self.read(rule)
        for hypothesis in rule.hypotheses:
            with self.subTest(hypothesis.name):
                sentence = render(rule, sample(), hypothesis.name, receipt=receipt, reads_path=self.reads)
                self.assertIn(f"; {COUNT_HORIZON}; prereg {rule.id}", sentence)


class ReadLineTest(Amended):
    """A read/3 line's post_hoc and amendments are checked, and a read/2 line is still read."""

    def good(self) -> dict[str, Any]:
        self.read(load(self.base))
        return self.last_line()

    def test_a_read_2_line_is_read_as_one_with_no_amendment_and_nothing_post_hoc(self):
        old = {k: v for k, v in self.good().items() if k not in ("amendments", "post_hoc")} | {"schema": "read/2"}
        line = parse_line(json.dumps(old), "line 1")
        self.assertEqual((line.schema, line.amendments, line.post_hoc), ("read/2", (), ()))
        self.reads.write_text(json.dumps(old) + "\n", encoding="utf-8")
        self.read(load(self.base), "2026-01-12T10:00:00+00:00")
        self.assertEqual(self.last_line()["schema"], "read/3")

    def test_a_malformed_post_hoc_or_amendments_is_refused(self):
        good = self.good()
        cases: dict[str, dict[str, object]] = {
            "post_hoc naming no label": {"post_hoc": ["unlabelled"]},
            "post_hoc unsorted": {"post_hoc": ["faster", "completes"]},
            "post_hoc repeated": {"post_hoc": ["faster", "faster"]},
            "post_hoc not a list": {"post_hoc": "faster"},
            "amendments not ids": {"amendments": ["layout.amend-2026-01-10"]},
            "a read/2 line with read/3's keys": {"schema": "read/2"},
            "a read/3 line without them": {"amendments": REMOVED},
        }
        for label, edit in cases.items():
            with self.subTest(label):
                bad = {k: v for k, v in {**good, **edit}.items() if v is not REMOVED}
                with self.assertRaisesRegex(PreregError, r"is not a read/[23] line: it holds malformed|keys must be"):
                    parse_line(json.dumps(bad), "line 1")
        # Each case differs from a line that is read, so only its own edit can be what refuses it.
        self.assertEqual(parse_line(json.dumps(good), "line 1").post_hoc, ())
