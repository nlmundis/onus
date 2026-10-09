"""onus.signoff: a hash-chained ledger that fails closed, extended only by a person at a terminal.

Every ledger here is a scratch file in a temporary folder, and the terminal is a pseudo-terminal the test holds
both ends of. No test writes a line to a ledger anyone relies on.
"""

import contextlib
import hashlib
import io
import json
import os
import pathlib
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest import mock

import onus
import onus.signoff
from onus.signoff import (
    CorruptLedgerError,
    SignoffError,
    SignoffRefused,
    Status,
    _ledger,
    check_signoff,
    record,
    revoke,
)
from onus.signoff.__main__ import main

ARTIFACT = "truth:labels/batch-1.json"
FIRST = b'{"a": "cat"}\n'
SECOND = b'{"a": "dog"}\n'
START = datetime(2026, 1, 8, 11, 0, tzinfo=UTC)


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


class Terminal:
    """A pseudo-terminal standing in for /dev/tty: the test types at one end and reads what the other was shown."""

    def __init__(self) -> None:
        """Open both ends, and start reading what the far end is shown."""
        self.master, self.slave = os.openpty()
        self.name = os.ttyname(self.slave)
        self.inode = os.fstat(self.slave).st_ino
        self._shown = b""
        self._closing = threading.Event()
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self) -> None:
        # Read as the library writes, so a long diff never fills the terminal's buffer and blocks the write.
        while not self._closing.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.02)
            if ready:
                self._shown += os.read(self.master, 65536)

    def type(self, text: str) -> None:
        os.write(self.master, (text + "\n").encode("utf-8"))

    def shown(self) -> str:
        self._closing.set()
        self._reader.join()
        while select.select([self.master], [], [], 0.05)[0]:
            self._shown += os.read(self.master, 65536)
        return self._shown.decode("utf-8").replace("\r\n", "\n")

    def close(self) -> None:
        self._closing.set()
        self._reader.join()
        os.close(self.master)
        os.close(self.slave)


class Desk(unittest.TestCase):
    """A scratch folder with a ledger and a file to sign, a terminal, a clock, and no session variable set."""

    def setUp(self) -> None:
        self.folder = pathlib.Path(tempfile.mkdtemp(prefix="onus-signoff-")).resolve()
        self.addCleanup(shutil.rmtree, self.folder)
        self.ledger = self.folder / "ledger.jsonl"
        self.truth = self.folder / "batch-1.json"
        self.truth.write_bytes(FIRST)
        self.terminal = Terminal()
        self.addCleanup(self.terminal.close)
        # A test that expects a refusal types nothing; were the refusal gone, the library would wait at the
        # terminal for ever. This answer, typed every few seconds and confirming nothing, turns that wait into a
        # failure.
        done = threading.Event()

        def answer_when_nobody_does() -> None:
            while not done.wait(5):
                self.terminal.type("no answer was typed")

        unanswered = threading.Thread(target=answer_when_nobody_does, daemon=True)
        unanswered.start()
        self.addCleanup(unanswered.join)
        self.addCleanup(done.set)
        self.ticks = 0
        for patch in (
            mock.patch.object(_ledger, "_TTY", self.terminal.name),
            mock.patch.object(_ledger, "_now", self.tick),
            mock.patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=True),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def tick(self) -> datetime:
        self.ticks += 1
        return START + timedelta(minutes=self.ticks - 1)

    def sign(self, typed: str | None = None, **kwargs: object) -> _ledger.Line:
        self.terminal.type(sha(self.truth.read_bytes())[:8] if typed is None else typed)
        return record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer", **kwargs)  # type: ignore[arg-type]

    def lines(self) -> list[str]:
        return self.ledger.read_text(encoding="utf-8").splitlines() if self.ledger.exists() else []

    def write(self, *records: dict[str, object] | str, chained: bool = True) -> list[str]:
        """Write a ledger by hand: each record with its ``prev`` set to the line before it, unless it gives one."""
        texts: list[str] = []
        for each in records:
            if isinstance(each, dict) and chained and "prev" not in each:
                each = {**each, "prev": sha(texts[-1]) if texts else None}
            texts.append(each if isinstance(each, str) else json.dumps(each, sort_keys=True, separators=(",", ":")))
        self.ledger.write_text("".join(text + "\n" for text in texts), encoding="utf-8")
        return texts

    def signed(self, content: bytes = FIRST, **changes: object) -> dict[str, object]:
        return {
            "schema": "signoff/1",
            "artifact": ARTIFACT,
            "sha256": sha(content),
            "bytes": len(content),
            "bound": {},
            "supersedes": None,
            "reviewed_by": "A Reviewer",
            "at": "2026-01-08T11:00:00+00:00",
            "tool": "onus 0.0.0",
            **changes,
        }

    def status(self, artifact: str = ARTIFACT) -> Status:
        return check_signoff(self.ledger, artifact, self.truth).status


class RecordTest(Desk):
    def test_a_confirmed_sign_off_writes_one_exact_line_and_keeps_the_content(self):
        line = self.sign()
        expected = json.dumps(
            {
                "artifact": ARTIFACT,
                "at": "2026-01-08T11:00:00+00:00",
                "bound": {},
                "bytes": len(FIRST),
                "prev": None,
                "reviewed_by": "A Reviewer",
                "schema": "signoff/1",
                "sha256": sha(FIRST),
                "supersedes": None,
                "tool": f"onus {onus.__version__}",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(self.ledger.read_bytes(), (expected + "\n").encode("utf-8"))
        self.assertEqual((line.text, line.line_sha256), (expected, sha(expected)))
        blob = self.folder / "ledger.jsonl.blobs" / sha(FIRST)
        self.assertEqual(blob.read_bytes(), FIRST)
        self.assertEqual(stat.S_IMODE(blob.stat().st_mode), 0o444)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_the_terminal_shows_what_is_being_signed_before_it_asks(self):
        self.sign()
        shown = self.terminal.shown()
        for part in (
            f"Sign-off of {ARTIFACT}\n",
            "  reviewed by: A Reviewer\n",
            f"  sha256: {sha(FIRST)}\n",
            f"  bytes: {len(FIRST)}\n",
            "  first sign-off of this artifact\n",
            '+{"a": "cat"}\n',
            "Type the first 8 hex digits of the content's sha256 to confirm",
        ):
            self.assertIn(part, shown)
        self.assertLess(shown.index('+{"a": "cat"}'), shown.index("Type the first 8"))

    def test_anything_but_the_first_eight_hex_digits_refuses_and_writes_nothing(self):
        digest = sha(FIRST)
        padded = (" " + digest[:8], digest[:8] + " ", digest[:8] + "\t")
        for typed in (
            "",
            "y",
            "yes",
            digest[:7],
            digest[:9],
            digest,
            digest[:8].upper(),
            digest[1:9],
            "00000000",
            *padded,
        ):
            with self.subTest(typed=typed):
                with self.assertRaisesRegex(SignoffRefused, "not confirmed"):
                    self.sign(typed)
                self.assertEqual(self.lines(), [])
                self.assertFalse((self.folder / "ledger.jsonl.blobs").exists())
                self.assertEqual(self.status(), Status.UNSIGNED)

    def reading(self, pieces: list[bytes]) -> contextlib.AbstractContextManager[object]:
        """Patch os.read so the library's terminal gives ``pieces`` in turn, then ends; the test's own end is real."""
        real, left = os.read, iter(pieces)

        def read(fd: int, size: int) -> bytes:
            return real(fd, size) if fd == self.terminal.master else next(left, b"")

        return mock.patch.object(os, "read", side_effect=read)

    def test_a_terminal_that_ends_without_a_line_refuses(self):
        with self.reading([]), self.assertRaisesRegex(SignoffRefused, "not confirmed"):
            record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
        self.assertEqual(self.lines(), [])

    def test_an_answer_that_arrives_in_pieces_is_read_to_its_line_end(self):
        digest = sha(FIRST)
        with self.reading([digest[:3].encode(), digest[3:8].encode(), b"\n"]):
            record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_write_the_terminal_takes_in_pieces_is_finished(self):
        real = os.write

        def three_at_a_time(fd: int, data: bytes) -> int:
            return real(fd, data) if fd == self.terminal.master else real(fd, bytes(data[:3]))

        with mock.patch.object(os, "write", side_effect=three_at_a_time):
            self.sign()
        self.assertIn("to confirm, or anything else to refuse: ", self.terminal.shown())

    def test_a_changed_content_is_signed_over_the_line_before_with_its_diff_shown(self):
        first = self.sign()
        self.truth.write_bytes(SECOND)
        self.assertEqual(self.status(), Status.CHANGED)
        second = self.sign()
        self.assertEqual((second.supersedes, second.prev), (first.line_sha256, first.line_sha256))
        self.assertEqual(second.at, START + timedelta(minutes=1))
        shown = self.terminal.shown()
        self.assertIn(f"  supersedes: {first.line_sha256}\n", shown)
        self.assertIn('-{"a": "cat"}\n+{"a": "dog"}\n', shown)
        self.assertEqual(self.status(), Status.SIGNED)
        self.assertEqual(
            sorted(path.name for path in (self.folder / "ledger.jsonl.blobs").iterdir()),
            sorted([sha(FIRST), sha(SECOND)]),
        )

    def test_the_same_content_is_not_signed_twice(self):
        self.sign()
        with self.assertRaisesRegex(SignoffError, "already signed with this content") as raised:
            self.sign()
        self.assertNotIsInstance(raised.exception, SignoffRefused)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.terminal.shown().count("Type the first"), 1)

    def test_content_signed_again_after_another_keeps_one_copy(self):
        self.sign()
        self.truth.write_bytes(SECOND)
        self.sign()
        self.truth.write_bytes(FIRST)
        third = self.sign()
        self.assertEqual(third.sha256, sha(FIRST))
        self.assertEqual(len(self.lines()), 3)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_each_session_variable_refuses_before_the_terminal_is_touched(self):
        names = (
            "CLAUDECODE",
            "AI_AGENT",
            "CI",
            "GITHUB_ACTIONS",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_CODE_",
            "CODEX_HOME",
        )
        for name in (*names, "CURSOR_TRACE_ID", "AIDER_MODEL", "GEMINI_CLI", "GEMINI_CLI_IDE", "COPILOT_AGENT"):
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: ""}):
                with mock.patch.object(_ledger, "_open_terminal", side_effect=AssertionError("opened")):
                    with self.assertRaisesRegex(SignoffRefused, f"the environment variable {name} is set") as raised:
                        record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
                self.assertIn("run it from a terminal where that variable is not set", str(raised.exception))
                self.assertFalse(self.ledger.exists())

    def test_a_variable_a_persons_own_profile_may_set_does_not_refuse(self):
        profile = {
            "ANTHROPIC_API_KEY": "x",
            "CLAUDE_CONFIG_DIR": "x",
            "CLAUDECODEX": "1",
            "MY_CI": "1",
            "CIRCLE": "1",
            "ci": "1",
        }
        with mock.patch.dict(os.environ, profile):
            self.sign()
        self.assertEqual(self.status(), Status.SIGNED)

    def test_with_no_terminal_to_open_it_refuses_whatever_standard_input_holds(self):
        reading, writing = os.pipe()
        os.write(writing, (sha(FIRST)[:8] + "\n").encode("utf-8"))
        os.close(writing)
        saved = os.dup(0)
        self.addCleanup(os.close, saved)
        self.addCleanup(os.dup2, saved, 0)
        os.dup2(reading, 0)
        os.close(reading)
        with (
            mock.patch.object(_ledger, "_TTY", str(self.folder / "no-terminal")),
            mock.patch.object(sys, "stdin", io.StringIO(sha(FIRST)[:8] + "\n")),
        ):
            with self.assertRaisesRegex(SignoffRefused, "no-terminal cannot be opened"):
                record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
        self.assertEqual(self.lines(), [])

    def test_a_file_in_place_of_the_terminal_is_refused_though_it_holds_the_answer(self):
        answer = self.folder / "answer"
        answer.write_text(sha(FIRST)[:8] + "\n", encoding="utf-8")
        with (
            mock.patch.object(_ledger, "_TTY", str(answer)),
            self.assertRaisesRegex(SignoffRefused, "is not a terminal"),
        ):
            record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
        self.assertEqual(self.lines(), [])

    def test_an_id_that_is_not_exact_is_refused(self):
        for artifact in (
            "truth:*",
            "truth:labels/*.json",
            "truth:a b",
            "Truth:x",
            "truth",
            ":x",
            "truth:",
            "truth:x?",
            "truth:[ab]",
            "truth:x\n",
            "-truth:x",
            7,
        ):
            with self.subTest(artifact=artifact):
                with self.assertRaisesRegex(SignoffError, "an artifact id is exact"):
                    record(self.ledger, artifact, self.truth, reviewed_by="A Reviewer")  # type: ignore[arg-type]
                with self.assertRaisesRegex(SignoffError, "an artifact id is exact"):
                    check_signoff(self.ledger, artifact, self.truth)  # type: ignore[arg-type]
        self.assertFalse(self.ledger.exists())

    def test_a_reviewer_is_a_name_on_one_line_and_never_an_address(self):
        for name in ("", "  ", "a@example.org", "A Reviewer\nsigned: yes", "A\rB", None, "\ud800"):
            with self.subTest(name=name), self.assertRaisesRegex(SignoffError, "reviewed_by is a name on one line"):
                record(self.ledger, ARTIFACT, self.truth, reviewed_by=name)  # type: ignore[arg-type]
        self.assertFalse(self.ledger.exists())

    def test_what_is_not_a_file_cannot_be_signed(self):
        with self.assertRaisesRegex(SignoffError, "is not a file to sign"):
            record(self.ledger, ARTIFACT, self.folder / "missing.json", reviewed_by="A Reviewer")
        self.assertEqual(self.lines(), [])

    def test_a_ledger_that_cannot_be_relied_on_is_not_extended(self):
        self.ledger.write_text("not a line\n", encoding="utf-8")
        with self.assertRaises(CorruptLedgerError):
            self.sign()
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), "not a line\n")

    def test_without_a_file_lock_it_refuses_before_the_terminal_is_touched(self):
        with mock.patch.dict(sys.modules, {"fcntl": None}):
            with mock.patch.object(_ledger, "_open_terminal", side_effect=AssertionError("opened")):
                with self.assertRaisesRegex(NotImplementedError, "this platform has no fcntl"):
                    record(self.ledger, ARTIFACT, self.truth, reviewed_by="A Reviewer")
        self.assertFalse(self.ledger.exists())

    def test_the_line_is_appended_under_the_ledgers_lock_and_flushed_to_disk(self):
        import fcntl

        calls: list[str] = []

        def which(fd: int) -> str:
            inode = os.fstat(fd).st_ino
            return (
                "ledger" if inode == self.ledger.stat().st_ino else "terminal" if inode == self.terminal.inode else "?"
            )

        def locked(fd: int, how: int) -> None:
            calls.append(f"flock {which(fd)} {how == fcntl.LOCK_EX}")

        def read(raw: bytes, path: pathlib.Path) -> list[_ledger.Line]:
            calls.append("read")
            return []

        def synced(fd: int) -> None:
            calls.append(f"fsync {which(fd)} {len(self.lines())}")

        with mock.patch.object(fcntl, "flock", side_effect=locked), mock.patch.object(os, "fsync", side_effect=synced):
            with mock.patch.object(_ledger, "parse_ledger", side_effect=read):
                self.sign()
        self.assertEqual(calls, ["flock ledger True", "read", "fsync ledger 1"])

    def test_the_ledger_may_be_named_from_the_folder_the_command_runs_in(self):
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.folder)
        self.terminal.type(sha(FIRST)[:8])
        record("ledger.jsonl", ARTIFACT, "batch-1.json", reviewed_by="A Reviewer")
        os.chdir(here)
        self.assertEqual(self.status(), Status.SIGNED)
        self.assertTrue((self.folder / "ledger.jsonl.blobs" / sha(FIRST)).is_file())

    def test_what_the_terminal_would_obey_is_shown_as_its_escape(self):
        self.truth.write_bytes(b"shown\n\x1b[1A\x1b[2Khidden\rover\x07\x00\ttab \xc3\xa9\n")
        self.sign()
        shown = self.terminal.shown()
        self.assertIn("+\\x1b[1A\\x1b[2Khidden\\rover\\x07\\x00\ttab \u00e9\n", shown)
        self.assertNotIn("\x1b", shown)
        self.assertNotIn("\x07", shown)

    def test_content_that_is_not_text_is_signed_and_its_bytes_shown(self):
        self.truth.write_bytes(b"\xff\xfe one\n")
        self.sign()
        self.truth.write_bytes(b"\xff\xfd one\n")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        assert check.diff is not None
        self.assertIn("-\\xff\\xfe one\n+\\xff\\xfd one\n", check.diff)
        self.sign()
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_last_line_with_no_newline_is_marked_not_run_into_the_next(self):
        self.truth.write_bytes(b"one\ntwo")
        self.sign()
        self.truth.write_bytes(b"one\nthree")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        assert check.diff is not None
        self.assertIn("-two\n\\ no newline at the end\n+three\n\\ no newline at the end\n", check.diff)

    def test_the_whole_content_is_shown_again_when_no_signed_copy_is_kept(self):
        self.sign()
        shutil.rmtree(self.folder / "ledger.jsonl.blobs")
        self.truth.write_bytes(SECOND)
        self.sign()
        shown = self.terminal.shown()
        self.assertEqual(shown.count('-{"a": "cat"}'), 0)
        self.assertIn('+{"a": "dog"}\n', shown)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_kept_copy_that_is_not_what_was_signed_stops_the_next_sign_off(self):
        self.sign()
        blob = self.folder / "ledger.jsonl.blobs" / sha(FIRST)
        blob.chmod(0o644)
        blob.write_bytes(b"tampered\n")
        self.truth.write_bytes(SECOND)
        with self.assertRaisesRegex(CorruptLedgerError, "is not the content its name says was signed"):
            self.sign()
        self.assertEqual(len(self.lines()), 1)

    def test_a_wrong_file_already_under_the_contents_hash_is_not_taken_for_the_kept_copy(self):
        blobs = self.folder / "ledger.jsonl.blobs"
        blobs.mkdir()
        (blobs / sha(FIRST)).write_bytes(b"cut sh")
        with self.assertRaisesRegex(CorruptLedgerError, "is not the content its name says was signed"):
            self.sign()
        self.assertEqual(self.lines(), [])

    def test_the_kept_copy_is_written_whole_or_not_at_all(self):
        blobs = self.folder / "ledger.jsonl.blobs"
        blobs.mkdir()
        left_behind = blobs / (sha(FIRST) + ".partial")
        left_behind.write_bytes(b"cut sh")
        left_behind.chmod(0o444)
        names: list[str] = []
        real = os.replace

        def replace(source: pathlib.Path, target: pathlib.Path) -> None:
            names.append(
                f"{pathlib.Path(source).name} -> {pathlib.Path(target).name} {pathlib.Path(source).read_bytes()!r}"
            )
            real(source, target)

        with mock.patch.object(os, "replace", side_effect=replace):
            self.sign()
        self.assertEqual(names, [f"{sha(FIRST)}.partial -> {sha(FIRST)} {FIRST!r}"])
        self.assertEqual([path.name for path in blobs.iterdir()], [sha(FIRST)])


class BoundTest(Desk):
    def setUp(self) -> None:
        super().setUp()
        self.rubric = self.folder / "rubrics" / "v3.md"
        self.rubric.parent.mkdir()
        self.rubric.write_text("be fair\n", encoding="utf-8")

    def test_a_bound_file_is_recorded_by_its_path_from_the_ledgers_folder(self):
        line = self.sign(bind=[self.rubric])
        self.assertEqual(dict(line.bound), {"rubrics/v3.md": sha("be fair\n")})
        digest = sha("be fair\n")
        self.assertIn(f"  bound: rubrics/v3.md {digest}\n", self.terminal.shown())
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_bound_file_that_changes_or_goes_missing_makes_the_artifact_changed(self):
        self.sign(bind=[self.rubric])
        self.rubric.write_text("be harsh\n", encoding="utf-8")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual((check.status, check.diff), (Status.CHANGED, None))
        self.assertIn("['rubrics/v3.md']", check.detail)
        self.rubric.unlink()
        self.assertEqual(self.status(), Status.CHANGED)

    def test_the_same_content_is_signed_again_when_what_it_is_bound_to_changed(self):
        self.sign(bind=[self.rubric])
        self.rubric.write_text("be harsh\n", encoding="utf-8")
        again = self.sign(bind=[self.rubric])
        self.assertEqual(dict(again.bound), {"rubrics/v3.md": sha("be harsh\n")})
        self.assertEqual(self.status(), Status.SIGNED)
        with self.assertRaisesRegex(SignoffError, "already signed"):
            self.sign(bind=[self.rubric])

    def test_each_bound_file_is_recorded_and_each_is_checked(self):
        second = self.folder / "rubrics" / "notes.md"
        second.write_text("notes\n", encoding="utf-8")
        line = self.sign(bind=[self.rubric, second])
        self.assertEqual(dict(line.bound), {"rubrics/notes.md": sha("notes\n"), "rubrics/v3.md": sha("be fair\n")})
        for changed in (self.rubric, second):
            with self.subTest(changed=changed.name):
                kept = changed.read_bytes()
                changed.write_bytes(b"changed\n")
                check = check_signoff(self.ledger, ARTIFACT, self.truth)
                self.assertEqual((check.status, check.line), (Status.CHANGED, line))
                self.assertIn(f"['rubrics/{changed.name}']", check.detail)
                changed.write_bytes(kept)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_file_the_line_before_bound_and_this_one_does_not_is_shown_as_unbound(self):
        self.sign(bind=[self.rubric])
        self.truth.write_bytes(SECOND)
        line = self.sign()
        self.assertEqual(dict(line.bound), {})
        self.assertIn("  no longer bound: rubrics/v3.md\n", self.terminal.shown())

    def test_the_ledger_and_its_kept_copies_cannot_be_bound(self):
        self.sign()
        self.truth.write_bytes(SECOND)
        for bound in (self.ledger, self.folder / "ledger.jsonl.blobs" / sha(FIRST)):
            with self.subTest(bound=bound.name), self.assertRaisesRegex(SignoffError, "which signing changes"):
                self.sign(bind=[bound])
        self.assertEqual(len(self.lines()), 1)

    def test_a_file_outside_the_ledgers_folder_or_missing_cannot_be_bound(self):
        outside = pathlib.Path(tempfile.mkdtemp(prefix="onus-signoff-out-")).resolve()
        self.addCleanup(shutil.rmtree, outside)
        (outside / "rubric.md").write_text("elsewhere\n", encoding="utf-8")
        for bound in (
            outside / "rubric.md",
            self.folder / "rubrics" / ".." / ".." / outside.name / "rubric.md",
            self.folder / "none.md",
            self.folder / "rubrics",
        ):
            with self.subTest(bound=bound.name), self.assertRaisesRegex(SignoffError, "cannot be bound"):
                self.sign(bind=[bound])
        self.assertEqual(self.lines(), [])


class RevokeTest(Desk):
    def test_a_revocation_is_a_line_that_names_the_sign_off_and_signs_nothing(self):
        signed = self.sign()
        self.terminal.type(signed.line_sha256[:8])
        revoked = revoke(self.ledger, ARTIFACT, reviewed_by="B Reviewer")
        self.assertEqual((revoked.sha256, revoked.bytes, dict(revoked.bound)), (None, None, {}))
        self.assertEqual((revoked.supersedes, revoked.prev), (signed.line_sha256, signed.line_sha256))
        self.assertTrue(revoked.revokes)
        self.assertFalse(signed.revokes)
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual(
            (check.status, check.detail), (Status.REVOKED, "revoked by B Reviewer at 2026-01-08T11:01:00+00:00")
        )
        shown = self.terminal.shown()
        self.assertIn(f"Revocation of the sign-off of {ARTIFACT}\n", shown)
        self.assertIn(f"  revokes line: {signed.line_sha256}\n", shown)
        self.assertIn("Type the first 8 hex digits of the revoked line's sha256", shown)

    def test_the_digits_typed_are_the_revoked_lines_not_the_contents(self):
        self.sign()
        self.terminal.type(sha(FIRST)[:8])
        with self.assertRaisesRegex(SignoffRefused, "not confirmed"):
            revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_a_revoked_artifact_can_be_signed_again(self):
        signed = self.sign()
        self.terminal.type(signed.line_sha256[:8])
        revoked = revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        again = self.sign()
        self.assertEqual(again.supersedes, revoked.line_sha256)
        self.assertEqual(self.status(), Status.SIGNED)

    def test_only_a_sign_off_can_be_revoked(self):
        with self.assertRaisesRegex(SignoffError, "has no sign-off"):
            revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        signed = self.sign()
        self.terminal.type(signed.line_sha256[:8])
        revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        with self.assertRaisesRegex(SignoffError, "has no sign-off"):
            revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        self.assertEqual(len(self.lines()), 2)

    def test_a_session_variable_refuses_a_revocation_too(self):
        signed = self.sign()
        self.terminal.type(signed.line_sha256[:8])
        with (
            mock.patch.dict(os.environ, {"CLAUDECODE": "1"}),
            self.assertRaisesRegex(SignoffRefused, "CLAUDECODE is set"),
        ):
            revoke(self.ledger, ARTIFACT, reviewed_by="A Reviewer")
        self.assertEqual(self.status(), Status.SIGNED)


class CheckTest(Desk):
    def test_no_ledger_or_no_line_for_the_artifact_is_unsigned(self):
        self.assertEqual(self.status(), Status.UNSIGNED)
        self.sign()
        check = check_signoff(self.ledger, "truth:other", self.truth)
        self.assertEqual((check.status, check.line), (Status.UNSIGNED, None))

    def test_changed_content_comes_with_its_diff_from_the_signed_copy(self):
        line = self.sign()
        self.truth.write_bytes(SECOND)
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual((check.status, check.line), (Status.CHANGED, line))
        assert check.diff is not None
        self.assertIn(f'--- signed\n+++ {self.truth}\n@@ -1 +1 @@\n-{{"a": "cat"}}\n+{{"a": "dog"}}\n', check.diff)

    def test_a_missing_file_is_changed(self):
        self.sign()
        self.truth.unlink()
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual((check.status, check.diff), (Status.CHANGED, None))
        self.assertIn("is missing", check.detail)

    def test_changed_content_with_no_signed_copy_kept_has_no_diff(self):
        self.sign()
        shutil.rmtree(self.folder / "ledger.jsonl.blobs")
        self.truth.write_bytes(SECOND)
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual((check.status, check.diff), (Status.CHANGED, None))
        self.assertIn("the signed copy is not kept", check.detail)

    def test_a_signed_copy_that_is_not_what_was_signed_is_corrupt(self):
        self.sign()
        blob = self.folder / "ledger.jsonl.blobs" / sha(FIRST)
        blob.chmod(0o644)
        blob.write_bytes(b"tampered\n")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual(check.status, Status.CORRUPT)  # though the content itself still matches the line
        self.assertIn("onus does not repair a ledger: restore it", check.detail)
        self.truth.write_bytes(SECOND)
        self.assertEqual(self.status(), Status.CORRUPT)
        self.assertEqual(self.status("truth:other"), Status.UNSIGNED)

    def test_a_ledger_written_by_hand_to_the_schema_reads_as_signed(self):
        self.write(self.signed())
        self.assertEqual(self.status(), Status.SIGNED)

    def test_one_malformed_line_makes_every_artifact_corrupt(self):
        good = self.signed()
        malformed: dict[str, dict[str, object] | str] = {
            "not json": "{",
            "a list": "[]",
            "a number": "7",
            "a text": '"signoff/1"',
            "nothing": "null",
            "blank": "",
            "a key missing": {key: value for key, value in good.items() if key != "tool"},
            "a key added": {**good, "note": "x"},
            "a key twice": json.dumps({**good, "prev": None})[:-1] + ',"schema":"signoff/1"}',
            "another schema": {**good, "schema": "signoff/2"},
            "a glob id": {**good, "artifact": "truth:*"},
            "a short hash": {**good, "sha256": sha(FIRST)[:63]},
            "an upper-case hash": {**good, "sha256": sha(FIRST).upper()},
            "a negative size": {**good, "bytes": -1},
            "a true size": {**good, "bytes": True},
            "content without size": {**good, "bytes": None},
            "size without content": {**good, "sha256": None, "supersedes": sha("x")},
            "bound not a mapping": {**good, "bound": []},
            "bound outside": {**good, "bound": {"../x": sha("x")}},
            "bound absolute": {**good, "bound": {"/x": sha("x")}},
            "bound to no hash": {**good, "bound": {"x": "abc"}},
            "bound to a number": {**good, "bound": {"x": 7}},
            "bound to nothing named": {**good, "bound": {"": sha("x")}},
            "bound through this folder": {**good, "bound": {"./x": sha("x")}},
            "bound through no folder": {**good, "bound": {"a//x": sha("x")}},
            "an address": {**good, "reviewed_by": "a@example.org"},
            "two lines of name": {**good, "reviewed_by": "A\nB"},
            "a time with no zone": {**good, "at": "2026-01-08T11:00:00"},
            "a time that is none": {**good, "at": "yesterday"},
            "a time that is no text": {**good, "at": 7},
            "no tool": {**good, "tool": ""},
            "a prev that is no hash": {**good, "prev": "start"},
            "a first line with a prev": {**good, "prev": sha("x")},
            "a first line that supersedes": {**good, "supersedes": sha("x")},
        }
        for name, line in malformed.items():
            with self.subTest(malformed=name):
                self.write(line)
                self.assertEqual(self.status(), Status.CORRUPT)
                self.assertEqual(self.status("truth:never-named"), Status.CORRUPT)
                self.write(good, line, chained=name != "a prev that is no hash")
                self.assertEqual(self.status(), Status.CORRUPT)

    def test_a_deep_line_is_corrupt_not_a_crash(self):
        self.ledger.write_text("[" * 100_000 + "\n", encoding="utf-8")
        self.assertEqual(self.status(), Status.CORRUPT)

    def test_a_broken_chain_makes_every_artifact_corrupt(self):
        first = self.signed()
        other = self.signed(artifact="truth:other")
        texts = self.write(first, other)
        self.assertEqual(self.status(), Status.SIGNED)
        cases = {
            "the first line removed": [texts[1]],
            "the lines swapped": [texts[1], texts[0]],
            "a line repeated": [texts[0], texts[0]],
            "the first line edited": [texts[0].replace("A Reviewer", "B Reviewer"), texts[1]],
            "a line put between": [
                texts[0],
                json.dumps(
                    {**self.signed(artifact="truth:third"), "prev": sha(texts[0])},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                texts[1],
            ],
        }
        for name, lines in cases.items():
            with self.subTest(broken=name):
                self.write(*lines)
                check = check_signoff(self.ledger, ARTIFACT, self.truth)
                self.assertEqual(check.status, Status.CORRUPT)
                self.assertEqual(self.status("truth:never-named"), Status.CORRUPT)

    def test_a_line_must_name_the_newest_earlier_line_for_its_artifact(self):
        first = self.signed()
        (first_text,) = self.write(first)
        again = self.signed(SECOND, supersedes=sha(first_text))
        self.truth.write_bytes(SECOND)
        self.write(first, again)
        self.assertEqual(self.status(), Status.SIGNED)
        for name, supersedes in (("nothing", None), ("another line", sha("x"))):
            with self.subTest(names=name):
                self.write(first, {**again, "supersedes": supersedes})
                self.assertEqual(self.status(), Status.CORRUPT)

    def test_a_revocation_by_hand_must_revoke_a_sign_off_and_bind_nothing(self):
        first = self.signed()
        (first_text,) = self.write(first)
        revocation = self.signed(sha256=None, bytes=None, supersedes=sha(first_text))
        texts = self.write(first, revocation)
        self.assertEqual(self.status(), Status.REVOKED)
        self.write(first, {**revocation, "bound": {"x": sha("x")}})
        self.assertEqual(self.status(), Status.CORRUPT)
        self.write(first, revocation, {**revocation, "supersedes": sha(texts[1])})
        self.assertEqual(self.status(), Status.CORRUPT)
        self.write({**revocation, "supersedes": None})
        self.assertEqual(self.status(), Status.CORRUPT)

    def test_a_ledger_cut_short_or_not_text_is_corrupt(self):
        (text,) = self.write(self.signed())
        self.ledger.write_text(text, encoding="utf-8")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual(check.status, Status.CORRUPT)
        self.assertIn("its last write was cut short", check.detail)
        self.assertIn("onus does not repair a ledger: restore it", check.detail)
        self.assertEqual(check.detail.count("onus does not repair"), 1)
        self.ledger.write_bytes(b"\xff\xfe\n")
        check = check_signoff(self.ledger, ARTIFACT, self.truth)
        self.assertEqual(check.status, Status.CORRUPT)
        self.assertIn("is not UTF-8", check.detail)

    def test_an_empty_ledger_is_unsigned(self):
        self.ledger.write_bytes(b"")
        self.assertEqual(self.status(), Status.UNSIGNED)


class CommandLineTest(Desk):
    @contextlib.contextmanager
    def printed(self) -> Iterator[tuple[io.StringIO, io.StringIO]]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            yield out, err

    def run_check(self) -> tuple[int, str]:
        with self.printed() as (out, _):
            code = main(["check", str(self.ledger), ARTIFACT, str(self.truth)])
        return code, out.getvalue()

    def test_record_revoke_and_check_round_trip_with_their_exit_codes(self):
        self.assertEqual(self.run_check()[0], 10)
        self.terminal.type(sha(FIRST)[:8])
        with self.printed() as (out, _):
            code = main(
                [
                    "record",
                    str(self.ledger),
                    ARTIFACT,
                    str(self.truth),
                    "--reviewed-by",
                    "A Reviewer",
                    "--bind",
                    str(self.truth),
                ]
            )
        (line,) = self.lines()
        self.assertEqual((code, out.getvalue()), (0, f"written: line {sha(line)}\n"))
        self.assertEqual(json.loads(line)["bound"], {"batch-1.json": sha(FIRST)})
        code, text = self.run_check()
        self.assertEqual((code, text), (0, "SIGNED: signed by A Reviewer at 2026-01-08T11:00:00+00:00\n"))
        self.truth.write_bytes(SECOND)
        code, text = self.run_check()
        self.assertEqual(code, 11)
        self.assertTrue(text.startswith("CHANGED: "))
        self.assertTrue(text.endswith('-{"a": "cat"}\n+{"a": "dog"}\n'))
        self.truth.write_bytes(FIRST)
        self.terminal.type(sha(line)[:8])
        with self.printed():
            self.assertEqual(main(["revoke", str(self.ledger), ARTIFACT, "--reviewed-by", "B Reviewer"]), 0)
        self.assertEqual(json.loads(self.lines()[1])["reviewed_by"], "B Reviewer")
        self.assertEqual(self.run_check()[0], 12)
        self.ledger.write_text("broken\n", encoding="utf-8")
        self.assertEqual(self.run_check()[0], 13)

    def test_a_refusal_is_printed_and_has_its_own_exit_code(self):
        with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}), self.printed() as (out, err):
            code = main(["record", str(self.ledger), ARTIFACT, str(self.truth), "--reviewed-by", "A Reviewer"])
        self.assertEqual((code, out.getvalue()), (20, ""))
        self.assertIn("refused: the environment variable CLAUDECODE is set", err.getvalue())
        with self.printed() as (_, err):
            self.assertEqual(main(["check", str(self.ledger), "truth:*", str(self.truth)]), 20)
        with mock.patch.dict(sys.modules, {"fcntl": None}), self.printed() as (_, err):
            self.assertEqual(main(["revoke", str(self.ledger), ARTIFACT, "--reviewed-by", "A Reviewer"]), 20)

    def test_a_ledger_or_content_that_cannot_be_read_is_a_refusal_not_a_crash(self):
        self.ledger.mkdir()
        self.terminal.type(sha(FIRST)[:8])
        with self.printed() as (_, err):
            code = main(["record", str(self.ledger), ARTIFACT, str(self.truth), "--reviewed-by", "A Reviewer"])
        self.assertEqual(code, 20)
        self.assertIn("refused: ", err.getvalue())

    def test_the_exit_code_reaches_the_shell(self):
        environment = {**os.environ, "PYTHONPATH": str(pathlib.Path(onus.__file__).resolve().parents[1])}
        done = subprocess.run(
            [sys.executable, "-B", "-m", "onus.signoff", "check", str(self.ledger), ARTIFACT, str(self.truth)],
            capture_output=True,
            text=True,
            env=environment,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual((done.returncode, done.stdout.split(":")[0]), (10, "UNSIGNED"))

    def test_the_reviewer_has_no_default(self):
        for command in (
            ["record", str(self.ledger), ARTIFACT, str(self.truth)],
            ["revoke", str(self.ledger), ARTIFACT],
        ):
            with self.subTest(command=command[0]), self.printed(), self.assertRaises(SystemExit) as stopped:
                main(command)
            self.assertEqual(stopped.exception.code, 2)

    def test_no_verdict_shares_an_exit_code_with_a_usage_error_or_a_crash(self):
        from onus.signoff.__main__ import EXIT, EXIT_REFUSED

        codes = [*EXIT.values(), EXIT_REFUSED]
        self.assertEqual(sorted(EXIT, key=lambda status: status.name), sorted(Status, key=lambda status: status.name))
        self.assertEqual(len(set(codes)), len(codes))
        self.assertEqual([status for status, code in EXIT.items() if code == 0], [Status.SIGNED])
        self.assertFalse({1, 2} & set(codes))


class SurfaceTest(unittest.TestCase):
    def test_the_real_terminal_is_the_controlling_one(self):
        self.assertEqual(_ledger._TTY, "/dev/tty")

    def test_the_clock_is_utc_and_now(self):
        before = datetime.now(UTC)
        now = _ledger._now()
        self.assertEqual(now.utcoffset(), timedelta(0))
        self.assertLessEqual(before, now)
        self.assertLessEqual(now, datetime.now(UTC))

    def test_the_package_exports_its_names(self):
        self.assertEqual(
            sorted(onus.signoff.__all__),
            [
                "Check",
                "CorruptLedgerError",
                "Line",
                "SignoffError",
                "SignoffRefused",
                "Status",
                "check_signoff",
                "record",
                "revoke",
            ],
        )
        self.assertTrue(issubclass(SignoffRefused, SignoffError) and issubclass(CorruptLedgerError, SignoffError))

    def test_the_variables_refused_are_the_ones_decided(self):
        self.assertEqual(_ledger.SESSION_NAMES, {"CLAUDECODE", "AI_AGENT", "CI", "GITHUB_ACTIONS"})
        self.assertEqual(
            _ledger.SESSION_PREFIXES, ("CLAUDE_CODE_", "CODEX_", "CURSOR_", "AIDER_", "GEMINI_CLI", "COPILOT_")
        )
        self.assertIsNone(_ledger.session_variable({"HOME": "x", "ANTHROPIC_BASE_URL": "x"}))
        self.assertEqual(_ledger.session_variable({"ZED": "1", "CODEX_HOME": "x", "CI": "true"}), "CI")


if __name__ == "__main__":
    unittest.main()
