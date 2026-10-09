"""Tier-2 sign-offs: a hash-chained ledger of approvals that only a person at a terminal can extend."""

import difflib
import enum
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import onus

SCHEMA = "signoff/1"
KEYS = ("artifact", "at", "bound", "bytes", "prev", "reviewed_by", "schema", "sha256", "supersedes", "tool")
# Exact ids only: a namespace, a colon, and a name. No glob can be written in one.
ARTIFACT_ID = re.compile(r"[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._/-]+\Z")
# Variables an agent session or an unattended job sets. Named exactly, or by prefix so a tool's next variable
# is caught too; ANTHROPIC_* and a bare CLAUDE_* are left out, since a person's own shell profile may set them.
SESSION_NAMES = frozenset({"CLAUDECODE", "AI_AGENT", "CI", "GITHUB_ACTIONS"})
SESSION_PREFIXES = ("CLAUDE_CODE_", "CODEX_", "CURSOR_", "AIDER_", "GEMINI_CLI", "COPILOT_")
# The controlling terminal: what a person types here reaches the process from no pipe, file, or script's stdin.
_TTY = "/dev/tty"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PREFIX = 8


class SignoffError(ValueError):
    """A ledger, an artifact id, or a request that onus.signoff refuses."""


class CorruptLedgerError(SignoffError):
    """A ledger that holds a malformed line, a broken chain, or a kept copy that is not what was signed.

    Nothing in such a ledger can be relied on, and onus offers no repair, which every message says.
    """

    def __init__(self, problem: str) -> None:
        """Keep ``problem`` and say what clears it, since no command here does."""
        super().__init__(
            f"{problem}. onus does not repair a ledger: restore it, and the copies kept beside it, from version "
            "control, and read what changed"
        )


class SignoffRefused(SignoffError):
    """A sign-off or revocation refused before the terminal was reached, or not confirmed there."""


class Status(enum.Enum):
    """What a ledger says of an artifact."""

    SIGNED = "signed"
    UNSIGNED = "unsigned"
    CHANGED = "changed"
    REVOKED = "revoked"
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class Line:
    """One checked line of a ledger."""

    text: str
    line_sha256: str
    artifact: str
    sha256: str | None
    bytes: int | None
    bound: Mapping[str, str]
    supersedes: str | None
    reviewed_by: str
    at: datetime
    tool: str
    prev: str | None

    @property
    def revokes(self) -> bool:
        """Whether this line revokes a sign-off: it names one and signs no content."""
        return self.sha256 is None


@dataclass(frozen=True)
class Check:
    """What ``check_signoff`` found: the status, why, the newest line for the artifact, and a diff when one exists."""

    status: Status
    detail: str
    line: Line | None = None
    diff: str | None = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _one_line(value: object) -> bool:
    """Return whether ``value`` is non-blank text on one line that UTF-8 can hold."""
    if not isinstance(value, str) or not value.strip() or value.splitlines() != [value]:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _instant(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _hash_or_none(value: object) -> bool:
    return value is None or (isinstance(value, str) and _SHA256.match(value) is not None)


def _bound(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(path, str) and _inside(path) and isinstance(digest, str) and _SHA256.match(digest)
        for path, digest in value.items()
    )


def _inside(path: str) -> bool:
    """Return whether ``path`` is a relative path that stays inside the folder it is read from."""
    parts = path.split("/")
    return bool(path) and not path.startswith("/") and all(part not in ("", ".", "..") for part in parts)


FIELDS = {
    "schema": lambda value: value == SCHEMA,
    "artifact": lambda value: isinstance(value, str) and ARTIFACT_ID.match(value) is not None,
    "sha256": _hash_or_none,
    "bytes": lambda value: value is None or (type(value) is int and value >= 0),
    "bound": _bound,
    "supersedes": _hash_or_none,
    "reviewed_by": lambda value: _one_line(value) and "@" not in str(value),
    "at": _instant,
    "tool": _one_line,
    "prev": _hash_or_none,
}


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("it gives a key more than once")
    return dict(pairs)


def _parse_line(text: str, where: str) -> Line:
    """Return the signoff/1 line ``text``, checked field by field.

    Raises:
        CorruptLedgerError: ``text`` is not JSON, gives a key twice, is not an object with exactly signoff/1's
            keys, holds a field of the wrong kind, signs content without its size or a size without content, or
            is a revocation that names no line or binds a file.
    """
    try:
        record = json.loads(text, object_pairs_hook=_no_repeats)
    except (ValueError, RecursionError) as error:
        raise CorruptLedgerError(f"{where} is not a {SCHEMA} line: {error}") from None
    if not isinstance(record, dict) or sorted(record) != sorted(KEYS):
        raise CorruptLedgerError(f"{where} is not a {SCHEMA} line: its keys must be exactly {sorted(KEYS)}")
    wrong = [key for key in KEYS if not FIELDS[key](record[key])]
    if (record["sha256"] is None) != (record["bytes"] is None):
        wrong.append("sha256 and bytes, which come together")
    if record["sha256"] is None and (record["supersedes"] is None or record["bound"]):
        wrong.append("a revocation, which names the line it revokes and binds nothing")
    if wrong:
        raise CorruptLedgerError(f"{where} is not a {SCHEMA} line: it holds malformed {wrong}")
    return Line(
        text=text,
        line_sha256=_sha256(text.encode("utf-8")),
        artifact=record["artifact"],
        sha256=record["sha256"],
        bytes=record["bytes"],
        bound=dict(record["bound"]),
        supersedes=record["supersedes"],
        reviewed_by=record["reviewed_by"],
        at=datetime.fromisoformat(record["at"]),
        tool=record["tool"],
        prev=record["prev"],
    )


def parse_ledger(raw: bytes, path: Path) -> list[Line]:
    """Return every line of a ledger's bytes, checked, in the order written.

    Raises:
        CorruptLedgerError: the bytes do not end in a newline (the last write was cut short) or are not UTF-8; a
            line is not a signoff/1 line; a line's ``prev`` is not the hash of the line before it; or a line's
            ``supersedes`` is not the newest earlier line for its artifact, which a re-signing and a revocation
            must name, and a revocation must find to be a sign-off.
    """
    if raw and not raw.endswith(b"\n"):
        raise CorruptLedgerError(f"{path} does not end in a newline: its last write was cut short")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CorruptLedgerError(f"{path} is not UTF-8, so it is no ledger onus wrote") from None
    lines: list[Line] = []
    newest: dict[str, Line] = {}
    for number, each in enumerate(text.split("\n")[:-1], start=1):
        where = f"line {number} of {path}"
        line = _parse_line(each, where)
        if line.prev != (lines[-1].line_sha256 if lines else None):
            raise CorruptLedgerError(f"{where} does not follow the line before it: the chain is broken")
        earlier = newest.get(line.artifact)
        if line.supersedes != (earlier.line_sha256 if earlier else None):
            raise CorruptLedgerError(f"{where} does not name the newest earlier line for {line.artifact!r}")
        if line.revokes and (earlier is None or earlier.revokes):
            raise CorruptLedgerError(f"{where} revokes what is not a sign-off")
        lines.append(line)
        newest[line.artifact] = line
    return lines


def _newest(lines: Iterable[Line], artifact: str) -> Line | None:
    found = None
    for line in lines:
        if line.artifact == artifact:
            found = line
    return found


def _blobs(ledger: Path) -> Path:
    """Return the folder beside ``ledger`` that keeps the content each sign-off signed, named by its sha256."""
    return ledger.with_name(ledger.name + ".blobs")


def _kept(ledger: Path, digest: str) -> bytes | None:
    """Return the copy kept beside ``ledger`` of the content whose sha256 is ``digest``, or None when none is kept.

    Raises:
        CorruptLedgerError: a copy is kept under that name and is not that content.
    """
    blob = _blobs(ledger) / digest
    if not blob.is_file():
        return None
    data = blob.read_bytes()
    if _sha256(data) != digest:
        raise CorruptLedgerError(f"{blob} is not the content its name says was signed")
    return data


def _lines(data: bytes) -> list[str]:
    """Return ``data`` as lines to compare: read as UTF-8, with each byte that is not UTF-8 written as its escape."""
    parts = data.decode("utf-8", "backslashreplace").split("\n")
    last = [parts[-1] + "\n\\ no newline at the end\n"] if parts[-1] else []
    return [part + "\n" for part in parts[:-1]] + last


def _diff(before: bytes, after: bytes, before_name: str, after_name: str) -> str:
    """Return a unified diff of two contents, a last line with no newline marked as one."""
    return "".join(difflib.unified_diff(_lines(before), _lines(after), before_name, after_name))


def _visible(text: str) -> str:
    """Return ``text`` with each character a terminal would obey, not show, written as its escape.

    Content under review is written to the reviewer's terminal; a carriage return or an escape sequence in it
    could otherwise overwrite or hide the lines being confirmed.
    """
    return "".join(
        each if each in "\n\t" or each.isprintable() else each.encode("unicode_escape").decode("ascii") for each in text
    )


def _valid_id(artifact: str) -> str:
    if not isinstance(artifact, str) or not ARTIFACT_ID.match(artifact):
        raise SignoffError(
            f"an artifact id is exact, such as 'truth:labels/batch-1.json', with no glob: not {artifact!r}"
        )
    return artifact


def _bound_now(ledger: Path, bound: Mapping[str, str]) -> list[str]:
    """Return each bound file that is missing or no longer has the sha256 the sign-off recorded."""
    changed = []
    for relative, digest in sorted(bound.items()):
        path = ledger.parent / relative
        if not path.is_file() or _sha256(path.read_bytes()) != digest:
            changed.append(relative)
    return changed


def check_signoff(ledger: str | os.PathLike[str], artifact: str, path: str | os.PathLike[str]) -> Check:
    """Return what the ledger at ``ledger`` says of ``artifact``, whose content is the file at ``path``.

    SIGNED: the newest line for the artifact signs exactly this content, and every file it bound is unchanged.
    UNSIGNED: no line names the artifact, or there is no ledger. CHANGED: the content, or a bound file, differs
    from what was signed, or is missing; ``diff`` shows the content's change when the signed copy is kept beside
    the ledger. REVOKED: the newest line revokes the sign-off. CORRUPT: the ledger cannot be relied on, because a
    line is malformed, the chain is broken, or the kept copy of the content this artifact's newest line signed is
    not that content. It fails closed: one bad line anywhere makes every artifact CORRUPT.

    Raises:
        SignoffError: ``artifact`` is not an exact id.
    """
    ledger, path = Path(ledger).resolve(), Path(path)
    _valid_id(artifact)
    try:
        lines = parse_ledger(ledger.read_bytes() if ledger.is_file() else b"", ledger)
    except CorruptLedgerError as error:
        return Check(Status.CORRUPT, str(error))
    line = _newest(lines, artifact)
    if line is None:
        return Check(Status.UNSIGNED, f"no line of {ledger} names {artifact!r}")
    if line.sha256 is None:
        return Check(Status.REVOKED, f"revoked by {line.reviewed_by} at {line.at.isoformat()}", line)
    try:
        signed = _kept(ledger, line.sha256)
    except CorruptLedgerError as error:
        return Check(Status.CORRUPT, str(error), line)
    if not path.is_file():
        return Check(Status.CHANGED, f"{path} is missing", line)
    content = path.read_bytes()
    if _sha256(content) != line.sha256:
        if signed is None:
            return Check(Status.CHANGED, f"{path} is not the content signed; the signed copy is not kept", line)
        return Check(
            Status.CHANGED, f"{path} is not the content signed", line, _diff(signed, content, "signed", str(path))
        )
    changed = _bound_now(ledger, line.bound)
    if changed:
        return Check(Status.CHANGED, f"bound files changed or missing since the sign-off: {changed}", line)
    return Check(Status.SIGNED, f"signed by {line.reviewed_by} at {line.at.isoformat()}", line)


def session_variable(environ: Mapping[str, str]) -> str | None:
    """Return the name of a variable in ``environ`` that an agent session or an unattended job sets, or None."""
    for name in sorted(environ):
        if name in SESSION_NAMES or name.startswith(SESSION_PREFIXES):
            return name
    return None


def _now() -> datetime:
    """Return the time now; the one clock a ledger line reads, so that tests can set it."""
    return datetime.now(UTC)


def _open_terminal() -> int:
    """Return a descriptor of the controlling terminal, open to read and write.

    Raises:
        SignoffRefused: there is none, or what opened is not a terminal.
    """
    try:
        terminal = os.open(_TTY, os.O_RDWR | os.O_NOCTTY)
    except OSError as error:
        raise SignoffRefused(f"no terminal to confirm at: {_TTY} cannot be opened ({error.strerror})") from None
    if not os.isatty(terminal):
        os.close(terminal)
        raise SignoffRefused(f"no terminal to confirm at: {_TTY} is not a terminal")
    return terminal


def _confirmed(terminal: int, shown: str, expected: str, what: str) -> None:
    """Show ``shown`` at the terminal and read back the first eight hex digits of ``expected``.

    Raises:
        SignoffRefused: what was typed is not those digits.
    """
    prompt = f"Type the first {_PREFIX} hex digits of {what} to confirm, or anything else to refuse: "
    unwritten = memoryview((_visible(shown) + prompt).encode("utf-8"))
    while unwritten:
        unwritten = unwritten[os.write(terminal, unwritten) :]
    answer = b""
    while not answer.endswith(b"\n"):
        more = os.read(terminal, 1024)
        if not more:
            break
        answer += more
    typed = answer.decode("utf-8", "replace").removesuffix("\n")
    if typed != expected[:_PREFIX]:
        raise SignoffRefused(f"not confirmed: what was typed is not the first {_PREFIX} hex digits of {what}")


def _append(
    ledger: str | os.PathLike[str],
    artifact: str,
    reviewed_by: str,
    build: Callable[[Path, list[Line], Line | None], tuple[dict[str, Any], str, str, str, bytes | None]],
) -> Line:
    """Append one line to the ledger, under its lock, once a person at the terminal has confirmed it.

    ``build(ledger, lines, newest)`` returns the new line's content fields, what to show, the digest whose first
    digits must be typed and what to call it, and the blob to keep, or raises.

    Raises:
        SignoffRefused: a session variable is set, there is no terminal, or the confirmation was not typed.
        SignoffError: the id or the reviewer's name is refused, or ``build`` refused.
        CorruptLedgerError: the ledger cannot be relied on, so nothing is added to it.
        NotImplementedError: this platform has no fcntl, so no lock to hold while the ledger is read and extended.
    """
    variable = session_variable(os.environ)
    if variable is not None:
        raise SignoffRefused(
            f"the environment variable {variable} is set, which an agent session or an unattended job sets: a "
            "sign-off is a person's, made from their own terminal. If you are that person, run it from a terminal "
            "where that variable is not set"
        )
    _valid_id(artifact)
    if not FIELDS["reviewed_by"](reviewed_by):
        raise SignoffError(
            f"reviewed_by is a name on one line, with no '@' (a ledger is no place for an address): not {reviewed_by!r}"
        )
    try:
        import fcntl  # here, not at the top, so that onus.signoff imports, and checks, where there is no fcntl
    except ImportError:
        raise NotImplementedError(
            "a sign-off holds fcntl.flock on the ledger while it reads and extends it, and this platform has no fcntl"
        ) from None
    ledger = Path(ledger).resolve()
    terminal = _open_terminal()
    try:
        with ledger.open("a+b") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            file.seek(0)
            lines = parse_ledger(file.read(), ledger)
            fields, shown, expected, what, blob = build(ledger, lines, _newest(lines, artifact))
            _confirmed(terminal, shown, expected, what)
            if blob is not None and _kept(ledger, _sha256(blob)) is None:
                # Written whole under another name first, so a write cut short never stands under the hash.
                kept = _blobs(ledger) / _sha256(blob)
                kept.parent.mkdir(exist_ok=True)
                partial = kept.with_name(kept.name + ".partial")
                partial.unlink(missing_ok=True)
                partial.write_bytes(blob)
                partial.chmod(0o444)
                os.replace(partial, kept)
            record = {
                "schema": SCHEMA,
                "artifact": artifact,
                "reviewed_by": reviewed_by,
                "at": _now().astimezone(UTC).isoformat(),
                "tool": f"onus {onus.__version__}",
                "prev": lines[-1].line_sha256 if lines else None,
                **fields,
            }
            text = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            file.write((text + "\n").encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
    finally:
        os.close(terminal)
    return _parse_line(text, "the line written")


def record(
    ledger: str | os.PathLike[str],
    artifact: str,
    path: str | os.PathLike[str],
    *,
    reviewed_by: str,
    bind: Iterable[str | os.PathLike[str]] = (),
) -> Line:
    """Sign ``artifact``, whose content is the file at ``path``, into the ledger, and return the line written.

    It refuses when a variable an agent session or an unattended job sets is in the environment, and when there
    is no controlling terminal. Then it shows, at the terminal, the artifact, the reviewer, the content's sha256
    and size, the files bound, and the diff from what was signed before (the whole content, the first time), and
    reads back the first eight hex digits of the content's sha256 from the terminal, never from standard input.
    It holds the ledger's lock from before it reads the ledger until the line is on disk, the time the person
    takes to answer included, so a second sign-off on the same ledger waits. Once confirmed, it keeps a
    read-only copy of the content beside the ledger and appends the line, flushed to disk. What it shows has
    every control character written as its escape. The whole content is shown as added whenever no signed copy
    is there to compare with: the first time, after a revocation, and when the copy is not kept. These are
    tripwires against a mistake, not a control against a process set on forging a sign-off.

    ``bind`` names other files the approval depends on, inside the ledger's folder; ``check_signoff`` reports
    CHANGED when one of them changes. A re-signing names the line it supersedes itself, and binds only what
    this call binds: a file the line before bound and this one does not is shown as no longer bound.

    Raises:
        SignoffRefused: a session variable is set, there is no terminal, or the confirmation was not typed.
        SignoffError: the id or ``reviewed_by`` is refused; ``path`` is no file; a bound file is missing, outside
            the ledger's folder, or the ledger or one of its kept copies; or the artifact's newest line already
            signs this content with these files bound.
        CorruptLedgerError: the ledger, or the kept copy of what was signed before, cannot be relied on.
        NotImplementedError: this platform has no fcntl.
    """
    path = Path(path)
    bind = tuple(bind)

    def build(ledger: Path, lines: list[Line], newest: Line | None) -> tuple[dict[str, Any], str, str, str, bytes]:
        if not path.is_file():
            raise SignoffError(f"{path} is not a file to sign")
        content = path.read_bytes()
        digest = _sha256(content)
        bound: dict[str, str] = {}
        for each in bind:
            file = Path(each).resolve()
            if not file.is_file() or not file.is_relative_to(ledger.parent):
                raise SignoffError(
                    f"{each} is not a file inside the ledger's folder, {ledger.parent}, so it cannot be bound"
                )
            if file == ledger or file.is_relative_to(_blobs(ledger)):
                raise SignoffError(
                    f"{each} is the ledger or a copy it keeps, which signing changes: it cannot be bound"
                )
            bound[file.relative_to(ledger.parent).as_posix()] = _sha256(file.read_bytes())
        if newest is not None and (newest.sha256, dict(newest.bound)) == (digest, bound):
            raise SignoffError(f"{artifact!r} is already signed with this content and these bound files")
        signed_before = b""
        if newest is not None and newest.sha256 is not None:
            signed_before = _kept(ledger, newest.sha256) or b""
        unbound = sorted(set(newest.bound) - set(bound)) if newest else []
        shown = (
            f"\nSign-off of {artifact}\n  reviewed by: {reviewed_by}\n  content: {path}\n  sha256: {digest}\n"
            f"  bytes: {len(content)}\n"
            + "".join(f"  bound: {name} {value}\n" for name, value in sorted(bound.items()))
            + "".join(f"  no longer bound: {name}\n" for name in unbound)
            + (f"  supersedes: {newest.line_sha256}\n" if newest else "  first sign-off of this artifact\n")
            + _diff(signed_before, content, "signed before", str(path))
            + "\n"
        )
        fields = {
            "sha256": digest,
            "bytes": len(content),
            "bound": bound,
            "supersedes": newest.line_sha256 if newest else None,
        }
        return fields, shown, digest, "the content's sha256", content

    return _append(ledger, artifact, reviewed_by, build)


def revoke(ledger: str | os.PathLike[str], artifact: str, *, reviewed_by: str) -> Line:
    """Revoke the newest sign-off of ``artifact`` in the ledger, and return the line written.

    It makes the same refusals as ``record``, shows the line it would revoke, and reads back the first eight hex
    digits of that line's sha256 from the terminal. The ledger only grows: the revocation is a line that names
    the sign-off, and a later ``record`` signs the artifact again.

    Raises:
        SignoffRefused: a session variable is set, there is no terminal, or the confirmation was not typed.
        SignoffError: the id or ``reviewed_by`` is refused, or the artifact's newest line is not a sign-off.
        CorruptLedgerError: the ledger cannot be relied on.
        NotImplementedError: this platform has no fcntl.
    """

    def build(ledger: Path, lines: list[Line], newest: Line | None) -> tuple[dict[str, Any], str, str, str, None]:
        if newest is None or newest.revokes:
            raise SignoffError(f"{artifact!r} has no sign-off in {ledger} to revoke")
        shown = (
            f"\nRevocation of the sign-off of {artifact}\n  reviewed by: {reviewed_by}\n"
            f"  revokes line: {newest.line_sha256}\n  signed by: {newest.reviewed_by} at {newest.at.isoformat()}\n"
            f"  content sha256: {newest.sha256}\n\n"
        )
        fields: dict[str, Any] = {"sha256": None, "bytes": None, "bound": {}, "supersedes": newest.line_sha256}
        return fields, shown, newest.line_sha256, "the revoked line's sha256", None

    return _append(ledger, artifact, reviewed_by, build)
