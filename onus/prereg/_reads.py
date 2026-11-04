"""The reads file's format: one ``read/3`` JSON line per recorded read, read back with every field checked.

``record_read`` appends the lines, and ``onus.report`` reads them back to bind a rendered verdict to its read. A
``read/2`` line, written before amendments existed, is still read, as a read of a rule with no amendment and no
hypothesis labelled post hoc. A line that is not exactly a read/3 or read/2 line is refused wherever the file is
read, never skipped: a reads file that cannot be trusted whole can neither seal a read nor bind a render.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from onus.prereg._rule import PreregError, base_stem, iso_date

READ_SCHEMA = "read/3"
SHA256 = re.compile(r"[0-9a-f]{64}")
_PREREG_ID = re.compile(r".+@[0-9a-f]{12}", re.DOTALL)
LABELS = ("met", "not met")


def text_field(value: object) -> bool:
    """Return whether ``value`` is non-blank text that UTF-8 can hold (so no lone surrogate)."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _instant(value: object) -> bool:
    """Return whether ``value`` is an ISO 8601 timestamp in UTC, as ``record_read`` writes its read time."""
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() == timedelta(0)
    except ValueError:
        return False


def _day(value: object) -> bool:
    """Return whether ``value`` is a real date written YYYY-MM-DD."""
    try:
        iso_date(value, "as_of")
    except PreregError:
        return False
    return True


def _sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _names(value: object) -> bool:
    """Return whether ``value`` is a list of distinct names, sorted, as ``post_hoc`` lists them."""
    return isinstance(value, list) and all(text_field(name) for name in value) and value == sorted(set(value))


# Every key a read/2 line holds, and what its value must be; a line holding any other key, or lacking one, is refused.
FIELDS_2: dict[str, Callable[[Any], bool]] = {
    "schema": lambda value: value == "read/2",
    "prereg": lambda value: isinstance(value, str) and _PREREG_ID.fullmatch(value) is not None,
    "experiment": text_field,
    "data_sha256": _sha256,
    "n": lambda value: type(value) is int and value > 0,
    "labels": lambda value: (
        isinstance(value, dict) and bool(value) and all(text_field(k) and v in LABELS for k, v in value.items())
    ),
    "at": _instant,
    "as_of": lambda value: value is None or _day(value),
    "early": lambda value: type(value) is bool,
    "supersedes": lambda value: value is None or _sha256(value),
    "reason": lambda value: value is None or text_field(value),
    "onus": text_field,
}
# A read/3 line adds the ids of the amendments its rule was loaded with, oldest first, and the hypotheses labelled
# post hoc: those an amendment touched that was signed after the hypothesis was first read.
FIELDS: dict[str, Callable[[Any], bool]] = {
    **FIELDS_2,
    "schema": lambda value: value == READ_SCHEMA,
    "amendments": lambda value: (
        isinstance(value, list) and all(isinstance(each, str) and _PREREG_ID.fullmatch(each) for each in value)
    ),
    "post_hoc": _names,
}


@dataclass(frozen=True)
class ReadLine:
    """One checked line of a reads file.

    Attributes:
        text: the line as written, without its newline.
        sha256: the sha256 of ``text``, which is what a receipt names.
        prereg: the ``prereg_id`` of the rule that was read.
        experiment: the rule's experiment.
        data_sha256: the evaluation's ``data_sha256``.
        n: how many units the evaluation used.
        labels: each hypothesis's label, "met" or "not met", by name.
        at: when the read was recorded, from ``record_read``'s own clock.
        as_of: the day the evaluation was made as of, for a days horizon; None when none was given.
        early: whether the read was recorded before its days window had closed in every time zone.
        supersedes: for a re-read on different data or with other labels, the line sha256 of the first read it
            supersedes.
        reason: why such a re-read was recorded; None when ``supersedes`` is.
        onus: the onus version that recorded the read.
        schema: "read/3", or "read/2" for a line written before amendments existed.
        amendments: the ids of the amendments the rule was loaded with, oldest first; empty on a read/2 line.
        post_hoc: the hypotheses labelled post hoc, sorted by name; empty on a read/2 line.
    """

    text: str
    sha256: str
    prereg: str
    experiment: str
    data_sha256: str
    n: int
    labels: dict[str, str]
    at: datetime
    as_of: date | None
    early: bool
    supersedes: str | None
    reason: str | None
    onus: str
    schema: str = READ_SCHEMA
    amendments: tuple[str, ...] = ()
    post_hoc: tuple[str, ...] = ()

    @property
    def stem(self) -> str:
        """The stem of the rule's record file: its ``prereg_id`` without the hash, and without an amendment's day."""
        return base_stem(self.prereg.rpartition("@")[0])


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise PreregError(f"it gives a key more than once: {repeated}")
    return dict(pairs)


def parse_line(text: str, where: str) -> ReadLine:
    """Return the read/3 or read/2 line ``text``, checked field by field.

    Raises:
        PreregError: ``text`` is not JSON, not an object with exactly the keys of the schema it names, or holds a
            field of the wrong kind; gives ``supersedes`` without ``reason`` or the other way round; or labels
            post hoc a hypothesis it holds no label for.
    """
    try:
        record = json.loads(text, object_pairs_hook=_no_repeats)
    except (ValueError, RecursionError) as error:  # a PreregError from _no_repeats is a ValueError too
        raise PreregError(f"{where} is not a {READ_SCHEMA} line: {error}") from None
    fields = FIELDS_2 if isinstance(record, dict) and record.get("schema") == "read/2" else FIELDS
    named = "read/2" if fields is FIELDS_2 else READ_SCHEMA
    if not isinstance(record, dict) or sorted(record) != sorted(fields):
        raise PreregError(f"{where} is not a {named} line: its keys must be exactly {sorted(fields)}")
    wrong = [key for key, valid in fields.items() if not valid(record[key])]
    if (record["supersedes"] is None) != (record["reason"] is None):
        wrong.append("supersedes and reason, which come together")
    if "post_hoc" in fields and "post_hoc" not in wrong and "labels" not in wrong:
        if not set(record["post_hoc"]) <= set(record["labels"]):
            wrong.append("post_hoc, which names only hypotheses it labels")
    if wrong:
        raise PreregError(f"{where} is not a {named} line: it holds malformed {wrong}")
    return ReadLine(
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        prereg=record["prereg"],
        experiment=record["experiment"],
        data_sha256=record["data_sha256"],
        n=record["n"],
        labels=record["labels"],
        at=datetime.fromisoformat(record["at"]),
        as_of=None if record["as_of"] is None else date.fromisoformat(record["as_of"]),
        early=record["early"],
        supersedes=record["supersedes"],
        reason=record["reason"],
        onus=record["onus"],
        schema=record["schema"],
        amendments=tuple(record.get("amendments", ())),
        post_hoc=tuple(record.get("post_hoc", ())),
    )


def parse_reads(raw: bytes, path: Path) -> list[ReadLine]:
    """Return every line of a reads file's bytes, checked, in the order written.

    Raises:
        PreregError: the file does not end in a newline (its last write was cut short), is not UTF-8, or holds a
            line that is not a read/3 or read/2 line.
    """
    if raw and not raw.endswith(b"\n"):
        raise PreregError(f"{path} does not end in a newline: its last write was cut short; repair it")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PreregError(f"{path} is not UTF-8, so it holds no read line onus wrote") from None
    return [parse_line(line, f"line {i} of {path}") for i, line in enumerate(text.split("\n")[:-1], start=1)]


def read_file(path: Path) -> list[ReadLine]:
    """Return every line of the reads file at ``path``, checked.

    Raises:
        PreregError: there is no file at ``path``, or ``parse_reads`` refuses it.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise PreregError(f"there is no reads file at {path}, so no read was recorded there") from None
    return parse_reads(raw, path)


def related_reads(lines: list[ReadLine], experiment: str, stem: str) -> list[ReadLine]:
    """Return those of ``lines`` that are reads of ``experiment``, or of a record whose file stem is ``stem``.

    These are the reads the seal holds a new read to, and the ones a re-read is sorted by: an edited record, which
    gets a new id, is related to the one it replaced by its stem even when its experiment was renamed, and a copy
    of a record under another file name by its experiment.
    """
    return [line for line in lines if line.experiment == experiment or line.stem == stem]


def find_line(lines: list[ReadLine], line_sha256: str, path: Path) -> ReadLine:
    """Return the line whose sha256 is ``line_sha256``.

    Raises:
        PreregError: no line has it, so no read with that receipt was recorded in ``path``.
    """
    for line in lines:
        if line.sha256 == line_sha256:
            return line
    raise PreregError(f"no line of {path} has sha256 {line_sha256!r}: no read with that receipt was recorded there")
