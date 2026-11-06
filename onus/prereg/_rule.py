"""The pre-registration record: its schema, its id, and loading it with every field checked."""

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, NoReturn

from onus.stats._common import check_alternative, probability
from onus.stats.binomial import HALF, METHODS
from onus.stats.multiplicity import CORRECTIONS

SCHEMA = "prereg/1"
TESTS = ("sign_test", "binomial_test")
# What a unit may record for a hypothesis, by the hypothesis's test.
OUTCOMES = {"sign_test": ("win", "loss", "tie"), "binomial_test": ("success", "failure")}
# Where a unit record keeps its outcomes; the unit and order fields may not take this name.
OUTCOMES_FIELD = "outcomes"
_TOP = (
    "schema",
    "experiment",
    "registered",
    "hypotheses",
    "families",
    "unit",
    "cluster_key",
    "order_key",
    "horizon",
    "looks",
    "bound_artifacts",
    "provenance",
)
_HYPOTHESIS = ("name", "test", "alternative", "method", "alpha", "family")
AMEND_SCHEMA = "amend/1"
_AMEND = ("schema", "amends", "reason", "record")
# What ends an amendment's file stem, after the record's: the day it was written.
_AMEND_STEM = r"\.amend-(\d{4}-\d{2}-\d{2})"
# The fields of a record whose change touches every hypothesis, since each one's result depends on them.
_SHARED = ("registered", "unit", "order_key", "horizon", "looks", "bound_artifacts")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# An exact number as ASCII digits: "0.05", "1", or "1/3"; no signs, exponents, underscores, or other scripts.
_EXACT = re.compile(r"[0-9]+(?:\.[0-9]+)?|[0-9]+/[0-9]+")


class PreregError(ValueError):
    """A pre-registration record, or data evaluated under one, that onus.prereg refuses."""


class HorizonNotReachedError(PreregError):
    """A rule was evaluated before its horizon: too few units, or a window that has not closed."""


class BoundArtifactError(PreregError):
    """A file the record binds by its sha256 is missing, or its content has changed."""


@dataclass(frozen=True)
class Hypothesis:
    """One pre-registered hypothesis.

    Attributes:
        name: how the hypothesis is named in the data's outcomes and in reports.
        test: "sign_test" or "binomial_test".
        alternative: "two-sided", "greater", or "less".
        method: how the test's p-value is computed; "exact" in this release.
        alpha: the level its family's adjusted p-value is decided at.
        family: the declared family it is adjusted in.
        p0: the null success probability of a binomial test; None for a sign test.
    """

    name: str
    test: str
    alternative: str
    method: str
    alpha: Fraction
    family: str
    p0: Fraction | None


@dataclass(frozen=True)
class Horizon:
    """When a rule may be evaluated.

    Attributes:
        kind: "count" (the first ``size`` units in order) or "days" (units dated in a window of ``size`` days).
        size: the number of units, or of days.
        start: the first day of the window; None for a count horizon.
    """

    kind: str
    size: int
    start: date | None

    @property
    def end(self) -> date | None:
        """The first day after a days horizon's window; None for a count horizon."""
        return None if self.start is None else date.fromordinal(self.start.toordinal() + self.size)


@dataclass(frozen=True)
class Amendment:
    """One signed amendment a rule was loaded with.

    Attributes:
        name: its file's name, ``<stem>.amend-YYYY-MM-DD.json``, beside the record.
        id: its file's ``prereg_id``, which the rule takes when it is the newest amendment.
        reason: why the record was amended, as the amendment states it.
        signed_at: when the tier-2 sign-off that binds it was recorded, from the ledger: the one time here that
            the record's author does not type.
        touches: the hypotheses it touches, by name: those whose own fields it changed or added, every member of
            a family whose correction or members it changed, and all of them when it changed a shared field.
        raw: its file's bytes.
    """

    name: str
    id: str
    reason: str
    signed_at: datetime
    touches: tuple[str, ...]
    raw: bytes = field(repr=False)


@dataclass(frozen=True)
class Rule:
    """A loaded pre-registration record, as its newest signed amendment leaves it.

    Attributes:
        id: ``prereg_id`` of the file it was loaded from, or of its newest amendment when it has one.
        sha256: the sha256 of the bytes of the file its id names.
        experiment: what the experiment is called.
        registered: the day it was registered.
        hypotheses: its hypotheses, in the record's order.
        families: each declared family's correction, by family name.
        unit: the field of a unit record that holds the unit's id.
        order_key: the field of a unit record that orders the units.
        horizon: when the rule may be evaluated.
        looks: when its result is planned to be read; in this release, only at the horizon.
        bound_artifacts: the sha256 of each file the record binds, by path relative to the record.
        provenance: free-form notes on where the record came from.
        raw: the record's own bytes, which ``evaluate`` and ``record_read`` check the rule still matches, with its
            amendments' bytes; the bound files and the sign-offs are checked only by ``load``.
        amendments: the signed amendments applied, oldest first; empty for a record never amended.
    """

    id: str
    sha256: str
    experiment: str
    registered: date
    hypotheses: tuple[Hypothesis, ...]
    families: Mapping[str, str]
    unit: str
    order_key: str
    horizon: Horizon
    looks: tuple[int, ...]
    bound_artifacts: Mapping[str, str]
    provenance: Mapping[str, str]
    raw: bytes = field(repr=False)
    amendments: tuple[Amendment, ...] = ()


def base_stem(stem: str) -> str:
    """Return the stem of the record that ``stem`` names: itself, or, for an amendment's, the record's it amends.

    A read under an amended rule is named by the amendment's id, and is related to reads of the record it amends
    by this stem, as an edited record's reads are.
    """
    found = re.fullmatch(rf"(.+?){_AMEND_STEM}", stem, re.DOTALL)
    return stem if found is None else found.group(1)


def _id(stem: str, raw: bytes) -> str:
    return f"{stem}@{hashlib.sha256(raw).hexdigest()[:12]}"


def prereg_id(path: str | Path) -> str:
    """Return ``"<name>@<first 12 hex digits of the file's sha256>"``, where name is the file's stem."""
    path = Path(path)
    return _id(path.stem, path.read_bytes())


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise PreregError(f"the record gives a key more than once: {repeated}")
    return dict(pairs)


def _no_float(text: str) -> NoReturn:
    raise PreregError(f'the record holds the float {text}; write an exact number as a string, such as "0.05"')


def _no_constant(text: str) -> NoReturn:
    raise PreregError(f"the record holds {text}, which is not a number JSON allows")


def _object(value: object, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreregError(f"{where} must be an object, not {value!r}")
    unknown = sorted(set(value) - set(required) - set(optional))
    if unknown:
        raise PreregError(f"{where} has keys prereg/1 does not define: {unknown}")
    missing = [key for key in required if key not in value]
    if missing:
        raise PreregError(f"{where} lacks {missing}")
    return value


def _one_line(value: str, where: str) -> str:
    """Return ``value`` when it holds no character ``str.splitlines`` splits a line at (E10).

    render's sentence names the hypothesis, its family, and the record's file stem, and a document quotes it on
    one line, so a record naming any of them with a line break could be read but never rendered; load refuses it,
    and holds the experiment and the unit and order_key fields to the same rule.

    Raises:
        PreregError: it holds one, such as LF, CR, FF, NEL, or U+2028.
    """
    if value.splitlines() != [value]:
        raise PreregError(f"{where} must be one line, but {value!r} holds a line break")
    return value


def _text(value: object, where: str) -> str:
    """Return ``value``, a name the record gives: text that is not blank, on one line.

    Raises:
        PreregError: it is not.
    """
    if not isinstance(value, str) or not value.strip():
        raise PreregError(f"{where} must be a non-empty string, not {value!r}")
    return _one_line(value, where)


def _positive(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PreregError(f"{where} must be a positive int, not {value!r}")
    return value


def iso_date(value: object, where: str) -> date:
    """Return ``value``, a "YYYY-MM-DD" string, as a date.

    Raises:
        PreregError: it is not one.
    """
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise PreregError(f"{where} must be a date written YYYY-MM-DD, not {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PreregError(f"{where} is not a real date: {value!r}") from None


def _exact_probability(value: object, where: str) -> Fraction:
    if not isinstance(value, str) or not _EXACT.fullmatch(value):
        raise PreregError(f'{where} must be an exact number written as a string, such as "0.05", not {value!r}')
    try:
        return probability(value, where, open_interval=True)
    except ValueError as error:
        raise PreregError(str(error)) from None


def _hypothesis(value: object, where: str) -> Hypothesis:
    record = _object(value, where, _HYPOTHESIS, ("p0",))
    name = _text(record["name"], f"{where}.name")
    test = record["test"]
    if test not in TESTS:
        raise PreregError(f"{where}.test must be one of {TESTS}, not {test!r}")
    try:
        alternative = check_alternative(record["alternative"])
    except ValueError as error:
        raise PreregError(f"{where}.{error}") from None
    if record["method"] not in METHODS:
        raise PreregError(f"{where}.method must be one of {METHODS}, not {record['method']!r}")
    alpha = _exact_probability(record["alpha"], f"{where}.alpha")
    family = _text(record["family"], f"{where}.family")
    p0 = None
    if test == "binomial_test":
        if "p0" not in record:
            raise PreregError(f"{where} is a binomial test and must state p0, its null success probability")
        p0 = _exact_probability(record["p0"], f"{where}.p0")
        if alternative == "two-sided" and p0 != HALF:
            raise PreregError(f"{where} is a two-sided binomial test, defined only at p0 = 1/2, not {p0}")
    elif "p0" in record:
        raise PreregError(f"{where} is a sign test, whose null is fixed at 1/2; it takes no p0")
    return Hypothesis(name, test, alternative, record["method"], alpha, family, p0)


def _horizon(value: object) -> Horizon:
    if not isinstance(value, dict) or value.get("kind") not in ("count", "days"):
        raise PreregError(f'horizon must be an object whose kind is "count" or "days", not {value!r}')
    if value["kind"] == "count":
        record = _object(value, "horizon", ("kind", "n"))
        return Horizon("count", _positive(record["n"], "horizon.n"), None)
    record = _object(value, "horizon", ("kind", "days", "start"))
    horizon = Horizon("days", _positive(record["days"], "horizon.days"), iso_date(record["start"], "horizon.start"))
    try:
        _ = horizon.end
    except (ValueError, OverflowError):
        raise PreregError(f"horizon.days ({horizon.size}) runs past the last date there is") from None
    return horizon


def _bound(value: object, root: Path | None) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PreregError(f"bound_artifacts must be an object of path: sha256, not {value!r}")
    for name, digest in value.items():
        path = PurePosixPath(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
            raise PreregError(f"bound artifact {name!r} must be a plain relative path inside the record's folder")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise PreregError(f"bound artifact {name!r} must name a lowercase hex sha256, not {digest!r}")
        if root is None:
            continue
        target = root / path
        try:
            inside = target.resolve().is_relative_to(root.resolve())
        except (OSError, RuntimeError):  # a symlink loop: RuntimeError on 3.11, OSError from 3.13
            raise BoundArtifactError(f"bound artifact {name!r} cannot be resolved; is it a symlink loop?") from None
        if not inside:
            raise PreregError(f"bound artifact {name!r} must be a plain relative path inside the record's folder")
        if not target.is_file():
            raise BoundArtifactError(f"bound artifact {name!r} is missing from {root}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != digest:
            raise BoundArtifactError(f"bound artifact {name!r} has changed: its sha256 is {actual}, not {digest}")
    return dict(value)


def _unicode(value: object) -> None:
    """Refuse text JSON can carry but UTF-8 cannot: a lone surrogate, from an escape like the one for U+D800.

    The walk keeps its own stack, since json may accept nesting deeper than Python's recursion limit.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise PreregError(f"the record holds text that is not valid Unicode: {item!r}") from None
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _decode(raw: bytes, what: str) -> object:
    """Return the JSON value ``raw`` holds, refusing what a record may not: a float, a repeated key, bad Unicode.

    Raises:
        PreregError: ``raw`` is not UTF-8 or not JSON onus can read, or holds one of those.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PreregError(f"{what} is not UTF-8") from None
    try:
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_float=_no_float, parse_constant=_no_constant)
    except PreregError:
        raise
    except (ValueError, RecursionError) as error:
        raise PreregError(f"{what} is not JSON onus can read: {error}") from None
    _unicode(value)
    return value


def _parse(raw: bytes, *, rule_id: str, root: Path | None) -> Rule:
    """Return the rule a prereg/1 record's bytes describe, checking each file it binds under ``root``.

    With ``root`` None, the bound files' names and digests are checked but the files are not read.

    Raises:
        PreregError: the record is malformed, holds a key prereg/1 does not define, or lacks one it requires.
        BoundArtifactError: a bound file is missing or has changed.
    """
    return _build(_decode(raw, "the record"), rule_id=rule_id, raw=raw, root=root)


def _build(value: object, *, rule_id: str, raw: bytes, root: Path | None) -> Rule:
    """Return the rule the decoded prereg/1 record ``value`` describes, with ``rule_id`` and ``raw`` as given.

    Raises:
        PreregError: the record is malformed, holds a key prereg/1 does not define, or lacks one it requires.
        BoundArtifactError: a bound file is missing or has changed.
    """
    record = _object(value, "the record", _TOP)
    if record["schema"] != SCHEMA:
        raise PreregError(f"schema must be {SCHEMA!r}, not {record['schema']!r}")
    if not isinstance(record["hypotheses"], list) or not record["hypotheses"]:
        raise PreregError("hypotheses must be a non-empty list")
    hypotheses = tuple(_hypothesis(value, f"hypotheses[{i}]") for i, value in enumerate(record["hypotheses"]))
    names = [hypothesis.name for hypothesis in hypotheses]
    if len(set(names)) != len(names):
        raise PreregError(f"hypotheses must have distinct names, not {names}")
    if not isinstance(record["families"], dict) or not record["families"]:
        raise PreregError('families must be a non-empty object of family name: {"correction": ...}')
    families: dict[str, str] = {}
    for name, value in record["families"].items():
        correction = _object(value, f"families.{name}", ("correction",))["correction"]
        if correction not in CORRECTIONS:
            raise PreregError(f"families.{name}.correction must be one of {CORRECTIONS}, not {correction!r}")
        members = [hypothesis for hypothesis in hypotheses if hypothesis.family == name]
        if not members:
            raise PreregError(f"family {name!r} is declared but no hypothesis belongs to it")
        if len({member.alpha for member in members}) > 1:
            raise PreregError(f"family {name!r} is decided at one alpha, but its members state several")
        families[name] = correction
    undeclared = sorted({hypothesis.family for hypothesis in hypotheses} - set(families))
    if undeclared:
        raise PreregError(f"hypotheses name families that are not declared: {undeclared}")
    unit = _text(record["unit"], "unit")
    order_key = _text(record["order_key"], "order_key")
    if len({unit, order_key, OUTCOMES_FIELD}) < 3:
        raise PreregError(f"unit, order_key, and {OUTCOMES_FIELD!r} must be three different fields")
    if record["cluster_key"] is not None:
        raise PreregError("cluster_key must be null: clustered analyses arrive in v0.2, and v0.1 would ignore it")
    horizon = _horizon(record["horizon"])
    registered = iso_date(record["registered"], "registered")
    if horizon.start is not None and horizon.start < registered:
        raise PreregError(
            f"the window starts on {horizon.start}, before the record was registered on {registered}, so it would "
            "not be registered before its data"
        )
    looks = record["looks"]
    if not isinstance(looks, list) or len(looks) != 1 or type(looks[0]) is not int or looks[0] != horizon.size:
        raise PreregError(
            f"looks must be [{horizon.size}], the horizon alone: this release reads a rule only at its horizon"
        )
    provenance = record["provenance"]
    if not isinstance(provenance, dict) or not all(isinstance(note, str) for note in provenance.values()):
        raise PreregError(f"provenance must be an object of strings, not {provenance!r}")
    return Rule(
        id=rule_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        experiment=_text(record["experiment"], "experiment"),
        registered=registered,
        hypotheses=hypotheses,
        families=MappingProxyType(families),
        unit=unit,
        order_key=order_key,
        horizon=horizon,
        looks=(horizon.size,),
        bound_artifacts=MappingProxyType(_bound(record["bound_artifacts"], root)),
        provenance=MappingProxyType(dict(provenance)),
        raw=raw,
    )


def _touches(before: Rule, after: Rule) -> tuple[str, ...]:
    """Return the hypotheses of ``after`` that an amendment from ``before`` to it touches, in its order (E23).

    A change to a field every result depends on (``_SHARED``) touches all of them. Otherwise a hypothesis is touched
    when it is new under its name or any of its own fields changed, and so is every member of a family whose
    correction or set of members changed. A change to the experiment's name or the provenance touches none.
    """
    names = [hypothesis.name for hypothesis in after.hypotheses]
    if any(getattr(before, name) != getattr(after, name) for name in _SHARED):
        return tuple(names)

    def members(rule: Rule, family: str) -> set[str]:
        return {hypothesis.name for hypothesis in rule.hypotheses if hypothesis.family == family}

    earlier = {hypothesis.name: hypothesis for hypothesis in before.hypotheses}
    touched = {hypothesis.name for hypothesis in after.hypotheses if earlier.get(hypothesis.name) != hypothesis}
    for family, correction in after.families.items():
        if before.families.get(family) != correction or members(before, family) != members(after, family):
            touched |= members(after, family)
    return tuple(name for name in names if name in touched)


def _amended(previous: Rule, stem: str, name: str, raw: bytes, signed_at: datetime, root: Path | None) -> Rule:
    """Return ``previous`` as the amend/1 file ``name``, whose bytes are ``raw``, leaves it.

    ``stem`` is the original record's file stem. The amendment holds a whole prereg/1 record, checked as ``load``
    checks one, and names in ``amends`` the id of the rule it amends: the record's, or the amendment before it's.

    Raises:
        PreregError: ``name`` is not ``<stem>.amend-YYYY-MM-DD.json`` with a real day no earlier than the day
            ``previous`` was registered; the file is not an amend/1 object, names another rule in ``amends``, gives
            no one-line reason, or holds a record ``load`` would refuse.
        BoundArtifactError: the record it holds binds a file that is missing or has changed.
    """
    found = re.fullmatch(rf"{re.escape(_nfc(stem))}{_AMEND_STEM}\.json", _nfc(name), re.DOTALL)
    if found is None:
        raise PreregError(f"{name!r} is not named as an amendment of {stem!r} is: {stem}.amend-YYYY-MM-DD.json")
    if iso_date(found.group(1), f"the day in {name}") < previous.registered:
        raise PreregError(f"{name} is dated before {previous.id!r} was registered, on {previous.registered}")
    try:
        decoded = _decode(raw, name)
    except PreregError as error:
        raise PreregError(f"{name}: {error}") from None
    value = _object(decoded, name, _AMEND)
    if value["schema"] != AMEND_SCHEMA:
        raise PreregError(f"{name}'s schema must be {AMEND_SCHEMA!r}, not {value['schema']!r}")
    if value["amends"] != previous.id:
        raise PreregError(
            f"{name} amends {value['amends']!r}, but the rule before it is {previous.id!r}: each amendment names the "
            "record, or the amendment before it, by its prereg id"
        )
    reason = _text(value["reason"], f"{name}'s reason")
    amendment_id = _id(Path(name).stem, raw)
    try:
        after = _build(value["record"], rule_id=amendment_id, raw=raw, root=root)
    except PreregError as error:  # BoundArtifactError too, kept as itself
        raise type(error)(f"the record in {name}: {error}") from None
    if after.registered != previous.registered:
        raise PreregError(
            f"the record in {name} is registered on {after.registered}, but {previous.id!r} was registered on "
            f"{previous.registered}: an amendment cannot move the day a record was registered"
        )
    amendment = Amendment(name, amendment_id, reason, signed_at, _touches(previous, after), raw)
    return replace(after, raw=previous.raw, amendments=(*previous.amendments, amendment))


def _chain(stem: str, raw: bytes, amendments: list[tuple[str, bytes, datetime]], root: Path | None) -> Rule:
    """Return the rule the record ``raw``, with file stem ``stem``, describes once each amendment is applied in turn.

    Each amendment is its file's name, its bytes, and when its sign-off was recorded.
    """
    rule = _parse(raw, rule_id=_id(stem, raw), root=root)
    for name, amendment_raw, signed_at in amendments:
        rule = _amended(rule, stem, name, amendment_raw, signed_at, root)
    return rule


def _nfc(name: str) -> str:
    """Return ``name`` in Unicode normal form C, as a file system that ignores normal form compares names."""
    return unicodedata.normalize("NFC", name)


def _amendment_names(path: Path) -> list[str]:
    """Return the names of the files beside the record ``path`` that start as its amendments do, oldest first.

    Raises:
        PreregError: one is not named ``<stem>.amend-YYYY-MM-DD.json`` with a real day, or is not a file; it is
            refused rather than passed over, since an amendment left out unseen would leave the rule unamended.
    """
    # Found without case and in one Unicode normal form, so that on a file system that ignores either an amendment
    # whose name differs from the record's in case or in form is seen, and refused as misnamed when its case
    # differs, rather than passed over; a difference of form alone is no difference.
    stem = _nfc(path.stem)
    prefix = f"{stem}.amend-".casefold()
    names = sorted(entry.name for entry in path.parent.iterdir() if _nfc(entry.name).casefold().startswith(prefix))
    for name in names:
        found = re.fullmatch(rf"{re.escape(stem)}{_AMEND_STEM}\.json", _nfc(name), re.DOTALL)
        if found is None or not (path.parent / name).is_file():
            raise PreregError(
                f"{name} beside {path.name} is named as its amendments are, but is not a file named "
                f"{path.stem}.amend-YYYY-MM-DD.json; rename it or remove it"
            )
        iso_date(found.group(1), f"the day in {name}")
    return names


def _signed_at(ledger: Path, path: Path, raw: bytes) -> datetime:
    """Return when the sign-off that binds the amendment at ``path``, whose bytes are ``raw``, was recorded.

    The sign-off's artifact is ``prereg:`` and the amendment's path from the ledger's folder, so two records of one
    stem in two folders are signed apart. The time is the ledger line's, which the record's author does not type.

    Raises:
        PreregError: the amendment is outside the ledger's folder, the ledger cannot be read, or it does not say
            SIGNED for exactly these bytes: UNSIGNED, CHANGED, REVOKED, or CORRUPT, each refused, so an amendment is
            applied only once a person has signed it.
    """
    from onus.signoff import SignoffError, Status, check_signoff  # here, so onus.prereg imports without it loaded

    try:
        ledger = ledger.resolve()
    except (OSError, RuntimeError) as error:  # a symlink loop: RuntimeError on 3.11, OSError from 3.13
        raise PreregError(f"{path.name} cannot be checked against the ledger {ledger}: {error}") from None
    try:
        relative = path.resolve().relative_to(ledger.parent)
    except ValueError:
        raise PreregError(
            f"{path.name} is not inside {ledger.parent}, the folder of the ledger that signs it"
        ) from None
    artifact = f"prereg:{relative.as_posix()}"
    try:
        check = check_signoff(ledger, artifact, path)
    except SignoffError as error:
        raise PreregError(
            f"{path.name} cannot be signed as {artifact!r}: {error}; rename the record and its amendments, or the "
            "folders between them and the ledger, with letters, digits, '.', '_', and '-' alone"
        ) from None
    except OSError as error:
        raise PreregError(f"{path.name} cannot be checked against the ledger {ledger}: {error}") from None
    if check.status is not Status.SIGNED or check.line is None or check.line.sha256 != hashlib.sha256(raw).hexdigest():
        raise PreregError(
            f"{path.name} is not signed: {ledger} says {check.status.value.upper()} for {artifact!r} ({check.detail}); "
            "an amendment is applied only once its sign-off is recorded, from the maintainer's terminal"
        )
    return check.line.at


def load(path: str | Path, *, ledger: str | Path | None = None) -> Rule:
    """Load and check the prereg/1 record at ``path``, with each amendment beside it, once each is signed.

    Bound artifacts are read relative to the record's folder. An amendment is a file ``<stem>.amend-YYYY-MM-DD.json``
    beside the record, holding ``{"schema": "amend/1", "amends": <prereg id>, "reason": ..., "record": <a whole
    prereg/1 record>}``; amendments apply oldest first, and the rule takes the newest one's prereg id. Each must be
    SIGNED in ``ledger`` as ``prereg:<its path from the ledger's folder>``, and the sign-off's time is kept on the
    rule, so a read can be labelled post hoc when an amendment came after it.

    Raises:
        PreregError: the record is malformed, holds a key prereg/1 does not define, or lacks one it requires; it, or
            its file stem, gives a name holding a line break; ``path`` is itself an amendment; amendments lie
            beside it and no ``ledger`` is given; or an amendment is misnamed,
            dated before the record was registered, moves its registration, is malformed, is out of its chain, lies
            outside the ledger's folder, is checked against a ledger that cannot be read, or is not signed for
            exactly the bytes read.
        BoundArtifactError: a bound file is missing or has changed.
    """
    path = Path(path)
    if re.fullmatch(rf".+{_AMEND_STEM}", path.stem, re.DOTALL):
        raise PreregError(f"{path.name} is an amendment: load the record it amends, and its amendments come with it")
    raw = path.read_bytes()
    _one_line(path.stem, "the record's file stem")  # the stem begins its prereg id, which every sentence names
    signed = []
    for name in _amendment_names(path):
        if ledger is None:
            raise PreregError(
                f"{path.name} has the amendment {name} beside it: load it with ledger=, the sign-off ledger that binds "
                "its amendments, so that each applies only once signed"
            )
        amendment = path.parent / name
        amendment_raw = amendment.read_bytes()
        signed.append((name, amendment_raw, _signed_at(Path(ledger), amendment, amendment_raw)))
    return _chain(path.stem, raw, signed, path.parent)


def check_intact(rule: Rule) -> None:
    """Refuse a rule that no longer matches the record and amendments it was loaded from, as one built by replace().

    It binds the bytes: the record's, and each amendment's, which the rule's id names through the chain. It does not
    consult the ledger again, so an amendment's ``signed_at`` is taken from the rule; nothing decides a label by it.

    Raises:
        PreregError: its id does not name its newest file's bytes, or its fields are not what those bytes say.
    """
    stem = base_stem(rule.id.rpartition("@")[0])
    rebuilt = _chain(stem, rule.raw, [(each.name, each.raw, each.signed_at) for each in rule.amendments], None)
    if rebuilt != rule:
        raise PreregError(f"rule {rule.id!r} no longer matches the record it was loaded from; load it again")
