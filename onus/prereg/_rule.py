"""The pre-registration record: its schema, its id, and loading it with every field checked."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
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
class Rule:
    """A loaded pre-registration record.

    Attributes:
        id: ``prereg_id`` of the file it was loaded from.
        sha256: the sha256 of that file's bytes.
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
        raw: the record's bytes, which ``evaluate`` and ``record_read`` check the rule still matches; the bound
            files are checked only by ``load``.
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


def _parse(raw: bytes, *, rule_id: str, root: Path | None) -> Rule:
    """Return the rule a prereg/1 record's bytes describe, checking each file it binds under ``root``.

    With ``root`` None, the bound files' names and digests are checked but the files are not read.

    Raises:
        PreregError: the record is malformed, holds a key prereg/1 does not define, or lacks one it requires.
        BoundArtifactError: a bound file is missing or has changed.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PreregError("the record is not UTF-8") from None
    try:
        record = json.loads(text, object_pairs_hook=_no_duplicates, parse_float=_no_float, parse_constant=_no_constant)
    except PreregError:
        raise
    except (ValueError, RecursionError) as error:
        raise PreregError(f"the record is not JSON onus can read: {error}") from None
    _unicode(record)
    record = _object(record, "the record", _TOP)
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


def load(path: str | Path) -> Rule:
    """Load and check the prereg/1 record at ``path``; bound artifacts are read relative to its folder.

    Raises:
        PreregError: the record is malformed, holds a key prereg/1 does not define, or lacks one it requires; or it,
            or its file stem, gives a name holding a line break.
        BoundArtifactError: a bound file is missing or has changed.
    """
    path = Path(path)
    raw = path.read_bytes()
    _one_line(path.stem, "the record's file stem")  # the stem begins its prereg id, which every sentence names
    return _parse(raw, rule_id=_id(path.stem, raw), root=path.parent)


def check_intact(rule: Rule) -> None:
    """Refuse a rule that no longer matches the record it was loaded from, such as one built by replace().

    Raises:
        PreregError: its id does not name its bytes, or its fields are not what those bytes say.
    """
    stem = rule.id.rpartition("@")[0]
    if _id(stem, rule.raw) != rule.id or _parse(rule.raw, rule_id=rule.id, root=None) != rule:
        raise PreregError(f"rule {rule.id!r} no longer matches the record it was loaded from; load it again")
