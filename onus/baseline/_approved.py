"""Tier-1 approval: a producer's scrubbed output compared with a committed file, re-recorded only on request."""

import difflib
import hashlib
import importlib
import inspect
import json
import os
import re
import tempfile
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path
from unittest import mock

from onus.scrub import Scrubber

SCHEMA = "approved/1"
# Set by `make approve` to the top level of the checkout it was run in; recording happens nowhere else.
APPROVE_ROOT = "ONUS_APPROVE_ROOT"
_LABEL = re.compile(r"[A-Za-z0-9_-]*\Z")
_EXT = re.compile(r"\.[a-z0-9]+\Z")
_MARK = ".approved"
_META = ".approved.meta.json"


def _named(producer: object) -> str:
    """Return the module and qualified name ``producer`` is recorded under.

    Raises:
        TypeError: ``producer`` has none, as a mock, a ``functools.partial``, or an instance has none.
    """
    module, qualname = getattr(producer, "__module__", None), getattr(producer, "__qualname__", None)
    if isinstance(producer, mock.NonCallableMock) or not isinstance(module, str) or not isinstance(qualname, str):
        raise TypeError(f"a producer is a named function of the code under test, not {producer!r}")
    return f"{module}.{qualname}"


def _resolved(name: str) -> object:
    """Return the object the dotted ``name`` names: the longest importable module, then its attributes.

    Raises:
        LookupError: no module on the path starts the name, or the module has no such attribute.
    """
    parts = name.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            found: object = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attribute in parts[cut:]:
            try:
                found = getattr(found, attribute)
            except AttributeError:
                raise LookupError(f"{'.'.join(parts[:cut])} has no {'.'.join(parts[cut:])}") from None
        return found
    raise LookupError(f"no module on the path starts the name {name!r}")


def unreal(name: str, tests: Path) -> str | None:
    """Return why the producer recorded as ``name`` is not real code under test, or None when it is.

    A real producer is a callable that importing its name gives back, that is no mock, and whose module's file
    lies outside ``tests``, the folder holding the tests and their approved files. A function written inside the
    tests, or a mock, can produce any text a baseline wants, so its baseline shows nothing about the code.
    """
    try:
        found = _resolved(name)
    except LookupError as error:
        return f"it cannot be imported: {error}"
    if isinstance(found, mock.NonCallableMock):
        return "it is a mock"
    if not callable(found):
        return "it is not callable"
    try:
        source = Path(inspect.getfile(inspect.unwrap(found))).resolve()
    except TypeError:
        return "it has no source file, so nothing shows it is not a built-in or made up at run time"
    if source.is_relative_to(tests.resolve()):
        return f"it is defined among the tests, in {source.name}"
    return None


def _inputs_sha256(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    """Return the sha256 of the canonical JSON of a producer's arguments.

    Raises:
        TypeError: an argument is not JSON-serializable, so its value could not be recorded.
    """
    try:
        text = json.dumps(
            {"args": list(args), "kwargs": kwargs}, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise TypeError(
            f"a producer's arguments must be JSON-serializable, so their hash can be recorded: {error}"
        ) from None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _received_path(approved: Path) -> Path:
    """Return where a mismatching output is written: under the temporary folder, never beside the approved file."""
    folder = hashlib.sha256(str(approved.parent).encode("utf-8")).hexdigest()[:8]
    return Path(tempfile.gettempdir()) / "onus-received" / folder / approved.name.replace(_MARK, ".received", 1)


class ApprovedMixin:
    """Gives a ``unittest.TestCase`` ``assertApproved``, which holds a producer's output to a committed file.

    Approved files live in ``approved_dir``, by default the folder ``approved`` beside the test's own file.
    """

    approved_dir: Path | None = None

    def assertApproved(
        self,
        producer: Callable[..., str],
        *args: object,
        scrubbers: Iterable[Scrubber] = (),
        label: str = "",
        ext: str = ".md",
        forbid: Iterable[str] = (),
        **kwargs: object,
    ) -> None:
        """Fail unless ``producer(*args, **kwargs)``, scrubbed, is the approved file byte for byte.

        The approved file is ``<module>.<Class>.<method>[.<label>].approved<ext>``, and beside it stands
        ``....approved.meta.json``, recording the producer's name, the sha256 of its arguments, and the
        scrubbers' names. A missing approved file fails, and so does one whose record no longer matches the
        call. On a mismatch the received text is written under the temporary folder and the failure shows the
        diff; nothing is written into the checkout.

        Recording happens only when the environment variable ``ONUS_APPROVE_ROOT`` is set, as ``make approve``
        sets it, to a git work tree that holds the approved file. Then the output is written as the new approved
        file, unless it matches one of the ``forbid`` regexes, which name what must never be approved, such as a
        path or a token the scrubbers should have replaced.

        The producer's own keyword arguments cannot be named ``scrubbers``, ``label``, ``ext``, or ``forbid``.

        Raises:
            TypeError: this is not a ``unittest.TestCase``; the producer has no name to record, did not return a
                text, or took an argument that is not JSON-serializable; or a scrubber is not a ``Scrubber``.
            ValueError: the producer is not real code under test; or ``label`` or ``ext`` cannot stand in a file
                name.
        """
        if not isinstance(self, unittest.TestCase):
            raise TypeError("ApprovedMixin is mixed into a unittest.TestCase")
        if not _LABEL.match(label) or not _EXT.match(ext):
            raise ValueError(
                "a label is letters, digits, _ or -, and an ext a dot then lower-case letters or digits: "
                f"not {label!r}, {ext!r}"
            )
        scrubbers = tuple(scrubbers)
        if not all(isinstance(scrubber, Scrubber) for scrubber in scrubbers):
            raise TypeError("assertApproved takes its scrubbers as Scrubbers; wrap a plain function with redactor")
        folder = (self.approved_dir or Path(inspect.getfile(type(self))).parent / "approved").resolve()
        name = _named(producer)
        reason = unreal(name, folder.parent)
        if reason is not None:
            raise ValueError(f"{name} is not a producer to approve: {reason}")
        if _resolved(name) is not producer:
            raise ValueError(f"importing {name} does not give back the producer, so the record could not be checked")
        record = {
            "schema": SCHEMA,
            "producer": name,
            "inputs_sha256": _inputs_sha256(args, kwargs),
            "scrubbers": [scrubber.name for scrubber in scrubbers],
        }
        received = producer(*args, **kwargs)
        if not isinstance(received, str):
            raise TypeError(f"{name} must return a text to approve, not {type(received).__name__}")
        for scrubber in scrubbers:
            received = scrubber(received)
        stem = ".".join(
            part
            for part in (type(self).__module__.rpartition(".")[2], type(self).__qualname__, self._testMethodName, label)
            if part
        )
        approved = folder / f"{stem}{_MARK}{ext}"
        meta = folder / f"{stem}{_META}"
        meta_text = json.dumps(record, indent=2, sort_keys=True) + "\n"
        root = os.environ.get(APPROVE_ROOT)
        if root is not None:
            self._record(Path(root), approved, received, meta, meta_text, tuple(forbid))
            return
        if not approved.is_file() or not meta.is_file():
            self.fail(
                f"{approved.name} has no approved file, or no record beside it, in {folder}. Read the output, then "
                "record it with `make approve`."
            )
        if approved.read_bytes() != received.encode("utf-8"):
            expected = approved.read_bytes().decode("utf-8", "replace")
            target = _received_path(approved)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(received.encode("utf-8"))
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True), received.splitlines(keepends=True), approved.name, target.name
                )
            )
            self.fail(
                f"{name}'s output differs from {approved.name}. The received text is at {target}. If the change is "
                f"intended, record it with `make approve`.\n{diff}"
            )
        if meta.read_bytes() != meta_text.encode("utf-8"):
            self.fail(
                f"{meta.name} no longer records this call (its producer, its arguments' hash, or its scrubbers "
                f"changed), though the output matches. Record it again with `make approve`.\nNow:\n{meta_text}"
            )

    def _record(
        self, root: Path, approved: Path, received: str, meta: Path, meta_text: str, forbid: tuple[str, ...]
    ) -> None:
        """Write ``received`` as the approved file, and its record, when ``root`` and ``forbid`` allow it."""
        assert isinstance(self, unittest.TestCase)
        if not root.is_absolute():
            self.fail(
                f"{APPROVE_ROOT} is {str(root)!r}, not an absolute path: nothing is recorded on a guess at the checkout"
            )
        root = root.resolve()
        if not (root / ".git").exists():
            self.fail(
                f"{APPROVE_ROOT} is {root}, which is not the top of a git work tree: nothing is recorded outside one"
            )
        if not approved.is_relative_to(root):
            self.fail(
                f"{approved} is outside {APPROVE_ROOT}, {root}: `make approve` records only into the checkout it was "
                "run in"
            )
        for pattern in forbid:
            found = re.search(pattern, received)
            if found is not None:
                self.fail(
                    f"the output holds {found[0]!r}, which the forbid pattern {pattern!r} names: nothing was recorded"
                )
        approved.parent.mkdir(parents=True, exist_ok=True)
        for path, text in ((approved, received), (meta, meta_text)):
            if not path.is_file() or path.read_bytes() != text.encode("utf-8"):
                path.write_bytes(text.encode("utf-8"))


class ApprovedProducersAreReal:
    """Mixed into a ``unittest.TestCase``, checks every record in ``approved_dir`` names real code under test.

    ``assertApproved`` refuses a mock or test-local producer when it runs; this reads the records themselves, so
    one edited by hand, or left behind by a test that no longer exists, is found too.
    """

    approved_dir: Path

    def test_every_approved_file_records_a_real_producer(self) -> None:
        """Fail on a record that names no real producer, and on an approved file or a record without the other."""
        assert isinstance(self, unittest.TestCase)
        folder = self.approved_dir.resolve()
        metas = sorted(folder.glob(f"*{_META}"))
        stems = {path.name.removesuffix(_META) for path in metas}
        outputs = {
            path.name.partition(_MARK)[0] for path in folder.glob(f"*{_MARK}.*") if not path.name.endswith(_META)
        }
        self.assertEqual(
            sorted(stems), sorted(outputs), "each approved file has one record beside it, and each record one file"
        )
        for path in metas:
            with self.subTest(record=path.name):
                record = json.loads(path.read_bytes())
                self.assertEqual(sorted(record), ["inputs_sha256", "producer", "schema", "scrubbers"])
                self.assertEqual(record["schema"], SCHEMA)
                self.assertIsInstance(record["producer"], str)
                reason = unreal(record["producer"], folder.parent)
                self.assertIsNone(reason, f"{record['producer']}: {reason}")
