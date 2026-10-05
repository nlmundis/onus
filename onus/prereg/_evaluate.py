"""Evaluating a rule on its data, which is pure, and recording that a result was read, which writes."""

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from fractions import Fraction
from pathlib import Path
from typing import Any

import onus
from onus.prereg._reads import FIELDS, READ_SCHEMA, ReadLine, parse_reads, related_reads
from onus.prereg._rule import (
    OUTCOMES,
    OUTCOMES_FIELD,
    Horizon,
    HorizonNotReachedError,
    PreregError,
    Rule,
    check_intact,
    iso_date,
)
from onus.stats import Family, TestResult, binomial_test, decide, sign_test

# A days window has closed in every time zone at noon UTC on its end day: midnight there in UTC-12, the last zone.
CLOSED_EVERYWHERE = time(12)


@dataclass(frozen=True)
class HypothesisResult:
    """One hypothesis's result under its rule.

    Attributes:
        name: the hypothesis.
        family: the family it was adjusted in.
        alpha: the level it was decided at.
        result: the exact test's result, before adjustment.
        adjusted_p: its p-value after its family's correction.
        met: whether the adjusted p-value is at most alpha, so the null hypothesis is rejected.
    """

    name: str
    family: str
    alpha: Fraction
    result: TestResult
    adjusted_p: Fraction
    met: bool

    @property
    def label(self) -> str:
        """Return "met" or "not met"."""
        return "met" if self.met else "not met"


@dataclass(frozen=True)
class Evaluation:
    """A rule's result on its data, before anyone has read it.

    Attributes:
        prereg: the rule's ``prereg_id``.
        experiment: the rule's experiment.
        n: how many units the evaluation used.
        data_sha256: the sha256 of the units it used, as canonical JSON of their id, order, and outcomes.
        hypotheses: each hypothesis's result, in the rule's order.
        as_of: the day the caller said the evaluation was made, which a days horizon needs; None when not given.
    """

    prereg: str
    experiment: str
    n: int
    data_sha256: str
    hypotheses: tuple[HypothesisResult, ...]
    as_of: date | None = None

    def labels(self) -> dict[str, str]:
        """Return "met" or "not met" for each hypothesis, by name."""
        return {hypothesis.name: hypothesis.label for hypothesis in self.hypotheses}


@dataclass(frozen=True)
class ReadReceipt:
    """Proof that an evaluation was read: the line ``record_read`` appended, and its sha256.

    Attributes:
        prereg: the rule's ``prereg_id``.
        data_sha256: the evaluation's ``data_sha256``.
        at: when the read was recorded, in UTC, from ``record_read``'s own clock.
        line_sha256: the sha256 of the appended line, without its newline.
        reads_path: the file the line was appended to, resolved when it was, so a change of directory keeps it.
    """

    prereg: str
    data_sha256: str
    at: datetime
    line_sha256: str
    reads_path: Path


def _identity(value: object, where: str) -> str | int:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise PreregError(f"{where} must be a string or an int, not {value!r}")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise PreregError(f"{where} is not valid Unicode: {value!r}") from None
    return value


def _units(rule: Rule, data: Sequence[Mapping[str, Any]]) -> list[tuple[str | int, str | int, Mapping[str, Any]]]:
    units: list[tuple[str | int, str | int, Mapping[str, Any]]] = []
    for i, record in enumerate(data):
        if not isinstance(record, Mapping):
            raise PreregError(f"unit {i} must be a mapping, not {record!r}")
        for field in (rule.unit, rule.order_key, OUTCOMES_FIELD):
            if field not in record:
                raise PreregError(f"unit {i} lacks the field {field!r}")
        units.append(
            (
                _identity(record[rule.unit], f"unit {i}'s {rule.unit!r}"),
                _identity(record[rule.order_key], f"unit {i}'s {rule.order_key!r}"),
                record[OUTCOMES_FIELD],
            )
        )
    ids = [unit for unit, _, _ in units]
    if len(set(ids)) != len(ids):
        raise PreregError(f"each unit's {rule.unit!r} must be distinct; some appear more than once")
    return units


def _chosen(
    rule: Rule, units: list[tuple[str | int, str | int, Mapping[str, Any]]], as_of: date | None
) -> list[tuple[str | int, str | int, Mapping[str, Any]]]:
    if as_of is not None and type(as_of) is not date:
        raise PreregError(f"as_of must be a date, not {as_of!r}")
    horizon = rule.horizon
    if horizon.kind == "count":
        if len({type(order) for _, order, _ in units}) > 1:
            raise PreregError(f"{rule.order_key!r} must be all ints or all strings, so the units have one order")
        orders = [order for _, order, _ in units]
        if len(set(orders)) != len(orders):
            raise PreregError(f"{rule.order_key!r} has repeated values, so which units come first is ambiguous")
        if len(units) < horizon.size:
            raise HorizonNotReachedError(f"the horizon is {horizon.size} units; the data holds {len(units)}")
        return sorted(units, key=lambda unit: unit[1])[: horizon.size]
    if as_of is None:
        raise PreregError("a days horizon needs as_of, the day the evaluation is made, since evaluate reads no clock")
    assert horizon.start is not None and horizon.end is not None
    if as_of < horizon.end:
        raise HorizonNotReachedError(f"the window runs to {horizon.end} (exclusive); as_of is {as_of}")
    dated = [(iso_date(order, f"{rule.order_key!r} of unit {unit!r}"), unit, order, o) for unit, order, o in units]
    # By day, then by unit, so the data's hash does not depend on how units dated the same day were listed.
    dated.sort(key=lambda entry: (entry[0], json.dumps(entry[1])))
    return [(unit, order, o) for day, unit, order, o in dated if horizon.start <= day < horizon.end]


def _outcomes_read_once(unit: str | int, outcomes: object) -> dict[Any, Any]:
    """Return a copy of a used unit's outcomes, so the checks, the counts, and the data hash see one reading of them.

    A mapping could answer differently when read again, which would let the counts disagree with the hash.

    Raises:
        PreregError: ``outcomes`` is not a mapping.
    """
    if not isinstance(outcomes, Mapping):
        raise PreregError(f"unit {unit!r} must record its outcomes as a mapping by hypothesis name")
    return dict(outcomes)


def evaluate(rule: Rule, data: Sequence[Mapping[str, Any]], *, as_of: date | None = None) -> Evaluation:
    """Evaluate ``rule`` on ``data``, reading no clock and writing nothing.

    Each unit is a mapping holding the rule's ``unit`` field (its id), its ``order_key`` field, and
    ``"outcomes"``, a mapping from each hypothesis's name to what the unit recorded for it: "win", "loss", or
    "tie" for a sign test, "success" or "failure" for a binomial test. A count horizon uses exactly the first N
    units in ``order_key`` order. A days horizon's ``order_key`` holds "YYYY-MM-DD" dates, and it uses the units
    dated inside its window, once ``as_of`` is past the window; ``evaluate`` trusts that day, and ``record_read``
    flags a read recorded before the window has closed. ``as_of`` is kept in the evaluation whatever the horizon.
    String order values sort as text, so "10" comes before "2": write them zero-padded, or as ints.

    Raises:
        HorizonNotReachedError: the data holds fewer units than a count horizon, or a days window is still open.
        PreregError: a unit is malformed, two units share an id, a count horizon's order is ambiguous, a used
            unit's outcomes do not match the rule's hypotheses, ``as_of`` is given and is not a date, or ``rule``
            no longer matches its record.
        EmptySampleError: a sign test's used units are all ties, or a days window holds no units.
    """
    check_intact(rule)
    names = [hypothesis.name for hypothesis in rule.hypotheses]
    chosen: list[tuple[str | int, str | int, dict[Any, Any]]] = []
    for unit, order, recorded in _chosen(rule, _units(rule, data), as_of):
        outcomes = _outcomes_read_once(unit, recorded)
        chosen.append((unit, order, outcomes))
        if not all(isinstance(name, str) for name in outcomes):
            raise PreregError(f"unit {unit!r} must record its outcomes as a mapping by hypothesis name")
        if sorted(outcomes) != sorted(names):
            raise PreregError(f"unit {unit!r} must record an outcome for exactly {sorted(names)}, not {outcomes!r}")
        for hypothesis in rule.hypotheses:
            if outcomes[hypothesis.name] not in OUTCOMES[hypothesis.test]:
                raise PreregError(
                    f"unit {unit!r} records {outcomes[hypothesis.name]!r} for {hypothesis.name!r}, a "
                    f"{hypothesis.test}; it must be one of {OUTCOMES[hypothesis.test]}"
                )
    results: dict[str, TestResult] = {}
    for hypothesis in rule.hypotheses:
        seen = [outcomes[hypothesis.name] for _, _, outcomes in chosen]
        if hypothesis.test == "sign_test":
            results[hypothesis.name] = sign_test(
                seen.count("win"),
                seen.count("loss"),
                ties=seen.count("tie"),
                alternative=hypothesis.alternative,
                method=hypothesis.method,
            )
        else:
            assert hypothesis.p0 is not None
            results[hypothesis.name] = binomial_test(
                seen.count("success"),
                len(seen),
                p=hypothesis.p0,
                alternative=hypothesis.alternative,
                method=hypothesis.method,
            )
    adjusted: dict[str, Fraction] = {}
    for family_name, correction in rule.families.items():
        members = [hypothesis.name for hypothesis in rule.hypotheses if hypothesis.family == family_name]
        family = Family(family_name, members, correction=correction)
        for member in members:
            family.add(member, results[member])
        adjusted.update(family.adjusted())
    used = [{"unit": unit, "order": order, "outcomes": dict(outcomes)} for unit, order, outcomes in chosen]
    canonical = json.dumps(used, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return Evaluation(
        prereg=rule.id,
        experiment=rule.experiment,
        n=len(chosen),
        data_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        hypotheses=tuple(
            HypothesisResult(
                h.name, h.family, h.alpha, results[h.name], adjusted[h.name], decide(adjusted[h.name], h.alpha)
            )
            for h in rule.hypotheses
        ),
        as_of=as_of,
    )


def status(rule: Rule, data: Sequence[Mapping[str, Any]], *, as_of: date | None = None) -> dict[str, str]:
    """Return each hypothesis's label: "pending" before the horizon, then "met" or "not met".

    Raises:
        PreregError: as ``evaluate`` does, except that a horizon not yet reached is "pending", not an error.
        EmptySampleError: as ``evaluate`` does.
    """
    try:
        return evaluate(rule, data, as_of=as_of).labels()
    except HorizonNotReachedError:
        return {hypothesis.name: "pending" for hypothesis in rule.hypotheses}


def _now() -> datetime:
    """Return the time now: the one clock ``record_read`` reads, so no caller chooses a read's time.

    Tests patch this function, and nothing else, to record a read at a chosen moment.
    """
    return datetime.now(UTC)


def read_early(horizon: Horizon, at: datetime) -> bool:
    """Return whether a read at ``at`` came before ``horizon``'s days window had closed in every time zone.

    That moment is noon UTC on the window's end day; a count horizon's read is never early. ``record_read`` writes
    this into each line as ``early``, and ``render`` refuses a line whose ``early`` is not the one its time gives.
    """
    end = horizon.end
    return end is not None and at < datetime.combine(end, CLOSED_EVERYWHERE, tzinfo=UTC)


def _seal(rule: Rule, evaluation: Evaluation, earlier: list[ReadLine], supersedes: str | None) -> None:
    """Refuse a re-read on different data unless it names the first read it supersedes.

    The earlier reads that count are those of the rule's experiment or of a record with the rule's file stem, so
    an edited record, which gets a new id, is sealed with the one it replaced.

    Raises:
        PreregError: the read's data hash, n, or labels differ from such an earlier read and ``supersedes`` is not
            given; ``supersedes`` is given and no such read differs; or it names a read other than the first.
    """
    related = related_reads(earlier, rule.experiment, rule.id.rpartition("@")[0])
    this = (evaluation.data_sha256, evaluation.n, evaluation.labels())
    differs = [line for line in related if (line.data_sha256, line.n, line.labels) != this]
    if differs and supersedes is None:
        raise PreregError(
            f"{rule.experiment!r} was already read on other data or with other labels (the read at line sha256 "
            f"{differs[0].sha256}); to record a re-read, pass supersedes={related[0].sha256!r}, the first read, and "
            "reason="
        )
    if supersedes is not None and not differs:
        raise PreregError(
            f"supersedes is given, but no earlier read of {rule.experiment!r} differs from this one: there is "
            "nothing to supersede"
        )
    if supersedes is not None and supersedes != related[0].sha256:
        raise PreregError(
            f"supersedes must name the first read of {rule.experiment!r}, {related[0].sha256!r}, not {supersedes!r}"
        )


def record_read(
    rule: Rule,
    evaluation: Evaluation,
    *,
    reads_path: str | Path,
    supersedes: str | None = None,
    reason: str | None = None,
) -> ReadReceipt:
    """Append a ``read/2`` line to ``reads_path`` recording that ``evaluation`` was read, and return its receipt.

    The read time comes from onus's own clock, never from the caller. The line records the evaluation's
    ``as_of`` and ``early``: whether a days horizon's read was recorded before noon UTC on the window's end day,
    when the window has closed in every time zone. A count horizon's read is never early.

    The reads file is sealed: once it holds a read of the rule's experiment, or of a record with the rule's file
    stem, a read whose data hash, n, or labels differ from any such earlier read is refused, unless
    ``supersedes`` names the first of them by its line sha256 and ``reason`` says why; both are written into the
    line. The seal binds only the reads file it is given. The check and the append hold an exclusive flock on the
    file, so writers take turns, and a line that is not a read/2 line refuses every read. flock comes from fcntl,
    which only POSIX has; ``record_read`` imports it itself, so ``onus.prereg`` imports everywhere, and where there
    is no fcntl it refuses before it opens the reads file.

    Raises:
        PreregError: ``evaluation`` names another rule or other hypotheses, states a family or alpha the rule does
            not, or labels a hypothesis other than its adjusted p-value decides; a days horizon's evaluation
            carries no ``as_of``, or one before its window's end; ``rule`` no longer matches its record;
            ``supersedes`` and ``reason`` are not given together, or are malformed; the seal refuses the read; or
            the reads file holds a line that is not a read/2 line, or its last line was cut short.
        NotImplementedError: this platform has no fcntl, so no flock to hold while the read is checked and appended.
    """
    try:
        import fcntl  # here, not at the top, so that onus.prereg and onus.report import where there is no fcntl
    except ImportError:
        raise NotImplementedError(
            "record_read holds fcntl.flock on the reads file while it checks the seal and appends, and this platform "
            "has no fcntl, so it cannot record a read"
        ) from None
    check_intact(rule)
    if evaluation.prereg != rule.id:
        raise PreregError(f"the evaluation is of {evaluation.prereg!r}, not of {rule.id!r}")
    if [hypothesis.name for hypothesis in evaluation.hypotheses] != [h.name for h in rule.hypotheses]:
        raise PreregError(f"the evaluation does not hold a result for each of {rule.id!r}'s hypotheses")
    # The data is not here to re-check, so only what follows from the rule is: pass what evaluate returned.
    for result, hypothesis in zip(evaluation.hypotheses, rule.hypotheses, strict=True):
        if (result.family, result.alpha) != (hypothesis.family, hypothesis.alpha):
            raise PreregError(f"{result.name!r} states a family or alpha that {rule.id!r} does not")
        if result.met != decide(result.adjusted_p, result.alpha):
            raise PreregError(f"{result.name!r} is labelled {result.label!r}, which its adjusted p-value does not give")
    as_of = evaluation.as_of
    if as_of is not None and type(as_of) is not date:
        raise PreregError(f"the evaluation's as_of must be a date, not {as_of!r}")
    end = rule.horizon.end
    if end is not None and (as_of is None or as_of < end):
        raise PreregError(
            f"{rule.id!r} has a days horizon, so its read needs the as_of evaluate was given, on or after {end}; "
            f"the evaluation's is {as_of}"
        )
    if (supersedes is None) != (reason is None):
        raise PreregError("supersedes and reason are given together, for a re-read on different data, or not at all")
    if not (FIELDS["supersedes"](supersedes) and FIELDS["reason"](reason)):
        raise PreregError(
            f"supersedes must be a line sha256 (64 lowercase hex digits) and reason non-blank text, not "
            f"{supersedes!r} and {reason!r}"
        )
    reads_path = Path(reads_path).resolve()  # so the receipt names this file after a change of directory too
    with reads_path.open("a+b") as reads:
        fcntl.flock(reads.fileno(), fcntl.LOCK_EX)
        reads.seek(0)
        _seal(rule, evaluation, parse_reads(reads.read(), reads_path), supersedes)
        at = _now().astimezone(UTC)
        early = read_early(rule.horizon, at)
        line = json.dumps(
            {
                "schema": READ_SCHEMA,
                "prereg": rule.id,
                "experiment": rule.experiment,
                "data_sha256": evaluation.data_sha256,
                "n": evaluation.n,
                "labels": evaluation.labels(),
                "at": at.isoformat(),
                "as_of": None if as_of is None else as_of.isoformat(),
                "early": early,
                "supersedes": supersedes,
                "reason": reason,
                "onus": onus.__version__,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        reads.write((line + "\n").encode("utf-8"))
        reads.flush()
        os.fsync(reads.fileno())
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    return ReadReceipt(rule.id, evaluation.data_sha256, at, digest, reads_path)
