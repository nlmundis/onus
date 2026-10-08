"""onus.baseline: a producer's output held to a committed file, recorded only under make approve."""

import contextlib
import functools
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import textwrap
import unittest
from collections.abc import Iterator
from typing import Any
from unittest import mock

import onus.baseline
from onus.baseline import APPROVE_ROOT, ApprovedMixin, ApprovedProducersAreReal
from onus.scrub import iso_dates, pattern, uuids

PRODUCT = textwrap.dedent("""
    from unittest import mock

    LIMIT = 3
    mocked = mock.Mock()


    def receipt(order, *, total="0.00"):
        return f"order {order}\\ntotal {total}\\nprinted 2026-01-08\\n"


    def count():
        return 3


    class Slip:
        def text(self):
            return "slip"
""")
AMONG_THE_TESTS = "def canned():\n    return 'whatever the baseline wants'\n"
RECEIPT = "order 7\ntotal 0.00\nprinted 2026-01-08\n"
STEM = "test_baseline.Case.test_it"


class Sandbox(unittest.TestCase):
    """A scratch checkout: a product package, a tests folder with its approved files, and its own temporary folder."""

    def setUp(self) -> None:
        self.top = pathlib.Path(tempfile.mkdtemp(prefix="onus-baseline-")).resolve()
        self.addCleanup(shutil.rmtree, self.top)
        self.repo = self.top / "repo"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "onus_sandbox_shop").mkdir()
        (self.repo / "onus_sandbox_shop" / "__init__.py").write_text(PRODUCT, encoding="utf-8")
        self.checks = self.repo / "onus_sandbox_checks"
        self.checks.mkdir()
        (self.checks / "__init__.py").write_text(AMONG_THE_TESTS, encoding="utf-8")
        self.approved = self.checks / "approved"
        self.scratch = self.top / "scratch"
        self.scratch.mkdir()
        for patch in (
            mock.patch.object(sys, "path", [str(self.repo), *sys.path]),
            mock.patch.object(sys, "dont_write_bytecode", True),
            mock.patch.object(tempfile, "tempdir", str(self.scratch)),
            mock.patch.dict(os.environ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(APPROVE_ROOT, None)
        self.addCleanup(lambda: [sys.modules.pop(name, None) for name in ("onus_sandbox_shop", "onus_sandbox_checks")])
        import onus_sandbox_checks  # type: ignore[import-not-found]
        import onus_sandbox_shop  # type: ignore[import-not-found]

        self.shop: Any = onus_sandbox_shop
        self.checks_module: Any = onus_sandbox_checks

    def case(self, approved_dir: pathlib.Path | None = None) -> ApprovedMixin:
        """Return a test case that keeps its approved files in the sandbox, as a test method would see itself."""

        class Case(ApprovedMixin, unittest.TestCase):
            def test_it(self) -> None: ...

        Case.__qualname__ = "Case"
        Case.approved_dir = approved_dir or self.approved
        return Case("test_it")

    @contextlib.contextmanager
    def approving(self, root: pathlib.Path | str | None = None) -> Iterator[None]:
        with mock.patch.dict(os.environ, {APPROVE_ROOT: str(self.repo if root is None else root)}):
            yield

    def record(self, *args: object, **kwargs: object) -> None:
        with self.approving():
            self.case().assertApproved(self.shop.receipt, *(args or (7,)), **kwargs)  # type: ignore[arg-type]

    def files(self) -> list[str]:
        return sorted(path.relative_to(self.top).as_posix() for path in self.top.rglob("*") if path.is_file())


class RecordingTest(Sandbox):
    def test_nothing_is_recorded_unless_make_approve_asks(self):
        before = self.files()
        try:
            with self.assertRaisesRegex(AssertionError, "has no approved file, or no record beside it"):
                self.case().assertApproved(self.shop.receipt, 7)
        except unittest.SkipTest:
            self.fail("a missing approved file skipped the test; it must fail it")
        self.assertEqual(self.files(), before)

    def test_a_differing_approved_file_is_never_overwritten_by_a_plain_run(self):
        self.record()
        (self.approved / f"{STEM}.approved.md").write_text("order 7\ntotal 9.99\n", encoding="utf-8")
        with self.assertRaises(AssertionError):
            self.case().assertApproved(self.shop.receipt, 7)
        self.assertEqual((self.approved / f"{STEM}.approved.md").read_text(encoding="utf-8"), "order 7\ntotal 9.99\n")

    def test_make_approve_records_the_output_and_its_record(self):
        self.record(7, total="12.50", scrubbers=[iso_dates(), uuids()])
        self.assertEqual(
            sorted(path.name for path in self.approved.iterdir()), [f"{STEM}.approved.md", f"{STEM}.approved.meta.json"]
        )
        self.assertEqual(
            (self.approved / f"{STEM}.approved.md").read_bytes(), b"order 7\ntotal 12.50\nprinted <date-1>\n"
        )
        inputs = hashlib.sha256(b'{"args":[7],"kwargs":{"total":"12.50"}}').hexdigest()
        self.assertEqual(
            (self.approved / f"{STEM}.approved.meta.json").read_text(encoding="utf-8"),
            "{\n"
            f'  "inputs_sha256": "{inputs}",\n'
            '  "producer": "onus_sandbox_shop.receipt",\n'
            '  "schema": "approved/1",\n'
            '  "scrubbers": [\n    "iso_dates",\n    "uuids"\n  ]\n'
            "}\n",
        )
        self.case().assertApproved(self.shop.receipt, 7, total="12.50", scrubbers=[iso_dates(), uuids()])

    def test_make_approve_replaces_what_was_approved_before(self):
        self.record()
        self.record(8)
        self.assertEqual((self.approved / f"{STEM}.approved.md").read_text(encoding="utf-8"), RECEIPT.replace("7", "8"))
        self.case().assertApproved(self.shop.receipt, 8)

    def test_recording_the_same_output_again_writes_nothing(self):
        self.record()
        for path in self.approved.iterdir():
            path.chmod(0o444)
        self.approved.chmod(0o555)
        self.addCleanup(self.approved.chmod, 0o755)
        self.record()

    def test_nothing_is_recorded_outside_the_checkout_make_approve_ran_in(self):
        other = self.top / "other"
        (other / ".git").mkdir(parents=True)
        before = self.files()
        with (
            self.approving(other),
            self.assertRaisesRegex(AssertionError, "records only into the checkout it was run in"),
        ):
            self.case().assertApproved(self.shop.receipt, 7)
        self.assertEqual(self.files(), before)

    def test_nothing_is_recorded_under_a_root_that_is_no_git_work_tree(self):
        shutil.rmtree(self.repo / ".git")
        before = self.files()
        with self.approving(), self.assertRaisesRegex(AssertionError, "not the top of a git work tree"):
            self.case().assertApproved(self.shop.receipt, 7)
        self.assertEqual(self.files(), before)

    def test_a_git_file_marks_a_work_tree_as_a_folder_does(self):
        shutil.rmtree(self.repo / ".git")
        (self.repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        self.record()
        self.case().assertApproved(self.shop.receipt, 7)

    def test_an_empty_or_relative_root_is_not_read_as_the_current_folder(self):
        before = self.files()
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.repo)
        for root in ("", ".", "onus_sandbox_checks/.."):
            with (
                self.subTest(root=root),
                self.approving(root),
                self.assertRaisesRegex(AssertionError, "not an absolute path"),
            ):
                self.case().assertApproved(self.shop.receipt, 7)
        self.assertEqual(self.files(), before)

    def test_a_forbidden_text_is_never_recorded(self):
        before = self.files()
        with self.approving(), self.assertRaisesRegex(AssertionError, r"holds '2026-01-08', which the forbid pattern"):
            self.case().assertApproved(self.shop.receipt, 7, forbid=[r"no such text", r"\d{4}-\d{2}-\d{2}"])
        self.assertEqual(self.files(), before)

    def test_forbid_reads_the_scrubbed_output(self):
        self.record(scrubbers=[iso_dates()], forbid=[r"\d{4}-\d{2}-\d{2}"])
        self.assertEqual(
            (self.approved / f"{STEM}.approved.md").read_text(encoding="utf-8"),
            RECEIPT.replace("2026-01-08", "<date-1>"),
        )


class ComparingTest(Sandbox):
    def test_a_mismatch_fails_with_a_diff_and_writes_the_received_text_outside_the_checkout(self):
        self.record()
        before = self.files()
        with self.assertRaises(AssertionError) as raised:
            self.case().assertApproved(self.shop.receipt, 7, total="9.99")
        message = str(raised.exception)
        folder = hashlib.sha256(str(self.approved).encode("utf-8")).hexdigest()[:8]
        received = self.scratch / "onus-received" / folder / f"{STEM}.received.md"
        self.assertEqual(received.read_bytes(), b"order 7\ntotal 9.99\nprinted 2026-01-08\n")
        self.assertEqual(self.files(), sorted([*before, received.relative_to(self.top).as_posix()]))
        self.assertIn(f"The received text is at {received}", message)
        self.assertIn(f"--- {STEM}.approved.md\n+++ {STEM}.received.md\n", message)
        self.assertIn("-total 0.00\n+total 9.99\n", message)
        self.assertIn("`make approve`", message)

    def test_a_match_writes_nothing(self):
        self.record()
        before = self.files()
        self.case().assertApproved(self.shop.receipt, 7)
        self.assertEqual(self.files(), before)

    def test_an_approved_file_that_is_not_text_fails_as_a_mismatch(self):
        self.record()
        (self.approved / f"{STEM}.approved.md").write_bytes(b"\xff\xfe order 7\n")
        with self.assertRaisesRegex(AssertionError, "output differs from"):
            self.case().assertApproved(self.shop.receipt, 7)

    def test_bytes_are_compared_not_lines(self):
        self.record()
        (self.approved / f"{STEM}.approved.md").write_bytes(RECEIPT.replace("\n", "\r\n").encode("utf-8"))
        with self.assertRaises(AssertionError):
            self.case().assertApproved(self.shop.receipt, 7)

    def test_an_approved_file_or_a_record_missing_fails(self):
        for missing in (f"{STEM}.approved.md", f"{STEM}.approved.meta.json"):
            with self.subTest(missing=missing):
                self.record()
                (self.approved / missing).unlink()
                with self.assertRaisesRegex(AssertionError, "has no approved file, or no record beside it"):
                    self.case().assertApproved(self.shop.receipt, 7)

    def test_a_record_that_no_longer_matches_the_call_fails_though_the_output_matches(self):
        self.record()
        nothing_to_scrub = pattern("no such text", "none")
        calls: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
            ((7,), {"total": "0.00"}),
            ((7,), {"scrubbers": [nothing_to_scrub]}),
        )
        for args, kwargs in calls:
            with (
                self.subTest(kwargs=sorted(kwargs)),
                self.assertRaisesRegex(AssertionError, "no longer records this call"),
            ):
                self.case().assertApproved(self.shop.receipt, *args, **kwargs)

    def test_scrubbers_run_in_the_order_given(self):
        day, digits = pattern(r"\d{4}-\d{2}-\d{2}", "day"), pattern(r"\d{4}", "digits")
        self.record(scrubbers=[day, digits])
        self.assertIn("printed <day-1>\n", (self.approved / f"{STEM}.approved.md").read_text(encoding="utf-8"))
        self.record(scrubbers=[digits, day])
        self.assertIn("printed <digits-1>-01-08\n", (self.approved / f"{STEM}.approved.md").read_text(encoding="utf-8"))

    def test_the_label_and_the_ext_name_the_file(self):
        self.record(label="short", ext=".txt")
        self.assertEqual(
            sorted(path.name for path in self.approved.iterdir()),
            [f"{STEM}.short.approved.meta.json", f"{STEM}.short.approved.txt"],
        )
        self.case().assertApproved(self.shop.receipt, 7, label="short", ext=".txt")
        for label, ext in (
            ("a/b", ".md"),
            ("a.b", ".md"),
            ("a b", ".md"),
            ("", "md"),
            ("", ".MD"),
            ("", "."),
            ("", ".m/d"),
            ("x\n", ".md"),
            ("", ".md\n"),
        ):
            with self.subTest(label=label, ext=ext), self.assertRaisesRegex(ValueError, "a label is letters"):
                self.case().assertApproved(self.shop.receipt, 7, label=label, ext=ext)

    def test_the_approved_folder_is_beside_the_tests_own_file_unless_named(self):
        class Case(ApprovedMixin, unittest.TestCase):
            def test_it(self) -> None: ...

        with self.assertRaises(AssertionError) as raised:
            Case("test_it").assertApproved(json.dumps, [1])
        self.assertIn(f" in {pathlib.Path(__file__).resolve().parent / 'approved'}.", str(raised.exception))

    def test_what_cannot_be_recorded_is_refused_before_anything_runs(self):
        with self.assertRaisesRegex(TypeError, "mixed into a unittest.TestCase"):
            ApprovedMixin().assertApproved(self.shop.receipt, 7)
        with self.assertRaisesRegex(TypeError, "takes its scrubbers as Scrubbers"):
            self.case().assertApproved(self.shop.receipt, 7, scrubbers=[str.upper])  # type: ignore[list-item]
        for argument in (object(), float("nan"), {1, 2}, b"7"):
            with self.subTest(argument=argument), self.assertRaisesRegex(TypeError, "must be JSON-serializable"):
                self.case().assertApproved(self.shop.receipt, argument)
        with (
            self.approving(),
            self.assertRaisesRegex(TypeError, "onus_sandbox_shop.count must return a text to approve, not int"),
        ):
            self.case().assertApproved(self.shop.count)
        self.assertFalse(self.approved.exists())


class ProducerTest(Sandbox):
    def test_a_mock_is_refused(self):
        with self.assertRaisesRegex(TypeError, "a named function of the code under test"):
            self.case().assertApproved(mock.Mock(return_value=RECEIPT))
        with mock.patch("onus_sandbox_shop.receipt", autospec=True, return_value=RECEIPT) as patched:
            with self.approving(), self.assertRaisesRegex(TypeError, "a named function of the code under test"):
                self.case().assertApproved(patched, 7)
        self.assertFalse(self.approved.exists())

    def test_what_has_no_name_is_refused(self):
        for nameless in (functools.partial(self.shop.receipt, 7), self.shop.Slip(), None):
            with (
                self.subTest(nameless=nameless),
                self.assertRaisesRegex(TypeError, "a named function of the code under test"),
            ):
                self.case().assertApproved(nameless)  # type: ignore[arg-type]

    def test_a_function_written_among_the_tests_is_refused(self):
        with self.approving(), self.assertRaisesRegex(ValueError, "defined among the tests, in __init__.py"):
            self.case().assertApproved(self.checks_module.canned)
        self.assertFalse(self.approved.exists())

    def test_a_function_that_importing_its_name_does_not_give_is_refused(self):
        def local() -> str:
            return RECEIPT

        with self.assertRaisesRegex(ValueError, "it cannot be imported"):
            self.case().assertApproved(local)
        with self.assertRaisesRegex(ValueError, "it cannot be imported"):
            self.case().assertApproved(lambda: RECEIPT)
        local.__module__, local.__qualname__ = "onus_sandbox_shop", "receipt"
        with self.approving(), self.assertRaisesRegex(ValueError, "does not give back the producer"):
            self.case().assertApproved(local)
        self.assertFalse(self.approved.exists())

    def test_a_bound_method_is_not_the_function_its_name_gives(self):
        with self.assertRaisesRegex(ValueError, "does not give back the producer"):
            self.case().assertApproved(self.shop.Slip().text)

    def test_what_has_no_source_file_is_refused(self):
        with self.assertRaisesRegex(ValueError, "it has no source file"):
            self.case().assertApproved(str, 7)

    def test_code_outside_the_tests_is_real_wherever_it_lives(self):
        with self.approving():
            self.case().assertApproved(json.dumps, [1, 2], ext=".json")
        self.assertEqual((self.approved / f"{STEM}.approved.json").read_text(encoding="utf-8"), "[1, 2]")


class ApprovedProducersAreRealTest(Sandbox):
    def check(self) -> unittest.TestResult:
        class Check(ApprovedProducersAreReal, unittest.TestCase):
            approved_dir = self.approved

        result = unittest.TestResult()
        Check("test_every_approved_file_records_a_real_producer").run(result)
        self.assertEqual(result.errors, [])
        return result

    def rewrite(self, **changes: object) -> None:
        path = self.approved / f"{STEM}.approved.meta.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(changes)
        path.write_text(
            json.dumps({key: value for key, value in record.items() if value is not None}), encoding="utf-8"
        )

    def test_recorded_files_pass(self):
        self.record()
        self.record(label="second", scrubbers=[iso_dates()])
        result = self.check()
        self.assertEqual((result.testsRun, result.failures), (1, []))

    def test_a_record_that_names_no_real_producer_fails(self):
        cases = {
            "onus_sandbox_shop.mocked": "it is a mock",
            "onus_sandbox_checks.canned": "it is defined among the tests",
            "onus_sandbox_shop.LIMIT": "it is not callable",
            "onus_sandbox_shop.gone": "it cannot be imported: onus_sandbox_shop has no gone",
            "onus_sandbox_shop.Slip.gone": "it cannot be imported: onus_sandbox_shop has no Slip.gone",
            "no_such_package_anywhere.thing": "it cannot be imported: no module on the path starts the name",
            "receipt": "it cannot be imported: no module on the path starts the name",
            "builtins.len": "it has no source file",
        }
        self.record()
        for producer, reason in cases.items():
            with self.subTest(producer=producer):
                self.rewrite(producer=producer)
                (failure,) = self.check().failures
                self.assertIn(f"{producer}: {reason}", failure[1])

    def test_a_record_of_another_shape_fails(self):
        self.record()
        for changes in ({"schema": "approved/2"}, {"at": "2026-01-08"}, {"scrubbers": None}, {"producer": 7}):
            with self.subTest(changes=changes):
                self.record()
                self.rewrite(**changes)
                self.assertEqual(len(self.check().failures), 1)

    def test_an_approved_file_without_its_record_fails_and_a_record_without_its_file(self):
        for orphaned in (f"{STEM}.approved.md", f"{STEM}.approved.meta.json"):
            with self.subTest(orphaned=orphaned):
                self.record()
                (self.approved / orphaned).unlink()
                (failure,) = self.check().failures
                self.assertIn("each approved file has one record beside it", failure[1])

    def test_a_method_of_a_class_under_test_is_real(self):
        self.record()
        self.rewrite(producer="onus_sandbox_shop.Slip.text")
        self.assertEqual(self.check().failures, [])


class SurfaceTest(unittest.TestCase):
    def test_the_package_exports_the_mixins_and_the_variable_make_approve_sets(self):
        self.assertEqual(sorted(onus.baseline.__all__), ["APPROVE_ROOT", "ApprovedMixin", "ApprovedProducersAreReal"])
        self.assertEqual(APPROVE_ROOT, "ONUS_APPROVE_ROOT")


if __name__ == "__main__":
    unittest.main()
