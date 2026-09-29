"""Evaluating a rule on its data, which is pure, and recording that a result was read, which writes."""

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import onus
from onus.prereg._rule import (
    OUTCOMES,
    OUTCOMES_FIELD,
    HorizonNotReachedError,
    PreregError,
    Rule,
    check_intact,
    iso_date,
)
from onus.stats import Family, TestResult, binomial_test, decide, sign_test

READ_SCHEMA = "read/1"


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
    """

    prereg: str
    experiment: str
    n: int
    data_sha256: str
    hypotheses: tuple[HypothesisResult, ...]

    def labels(self) -> dict[str, str]:
        """Return "met" or "not met" for each hypothesis, by name."""
        return {hypothesis.name: hypothesis.label for hypothesis in self.hypotheses}


@dataclass(frozen=True)
class ReadReceipt:
    """Proof that an evaluation was read: the line ``record_read`` appended, and its sha256.

    Attributes:
        prereg: the rule's ``prereg_id``.
        data_sha256: the evaluation's ``data_sha256``.
        at: when the read was recorded, in UTC.
        line_sha256: the sha256 of the appended line, without its newline.
        reads_path: the file the line was appended to.
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
    if type(as_of) is not date:
        raise PreregError(f"as_of must be a date, not {as_of!r}")
    assert horizon.start is not None and horizon.end is not None
    if as_of < horizon.end:
        raise HorizonNotReachedError(f"the window runs to {horizon.end} (exclusive); as_of is {as_of}")
    dated = [(iso_date(order, f"{rule.order_key!r} of unit {unit!r}"), unit, order, o) for unit, order, o in units]
    # By day, then by unit, so the data's hash does not depend on how units dated the same day were listed.
    dated.sort(key=lambda entry: (entry[0], json.dumps(entry[1])))
    return [(unit, order, o) for day, unit, order, o in dated if horizon.start <= day < horizon.end]


def evaluate(rule: Rule, data: Sequence[Mapping[str, Any]], *, as_of: date | None = None) -> Evaluation:
    """Evaluate ``rule`` on ``data``, reading no clock and writing nothing.

    Each unit is a mapping holding the rule's ``unit`` field (its id), its ``order_key`` field, and
    ``"outcomes"``, a mapping from each hypothesis's name to what the unit recorded for it: "win", "loss", or
    "tie" for a sign test, "success" or "failure" for a binomial test. A count horizon uses exactly the first N
    units in ``order_key`` order. A days horizon's ``order_key`` holds "YYYY-MM-DD" dates, and it uses the units
    dated inside its window, once ``as_of`` is past the window. String order values sort as text, so "10" comes
    before "2": write them zero-padded, or as ints.

    Raises:
        HorizonNotReachedError: the data holds fewer units than a count horizon, or a days window is still open.
        PreregError: a unit is malformed, two units share an id, a count horizon's order is ambiguous, or a used
            unit's outcomes do not match the rule's hypotheses, or ``rule`` no longer matches its record.
        EmptySampleError: a sign test's used units are all ties, or a days window holds no units.
    """
    check_intact(rule)
    chosen = _chosen(rule, _units(rule, data), as_of)
    names = [hypothesis.name for hypothesis in rule.hypotheses]
    for unit, _, outcomes in chosen:
        if not isinstance(outcomes, Mapping) or not all(isinstance(name, str) for name in outcomes):
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


def record_read(
    rule: Rule, evaluation: Evaluation, *, reads_path: str | Path, now: datetime | None = None
) -> ReadReceipt:
    """Append a line to ``reads_path`` recording that ``evaluation`` was read, and return its receipt.

    ``now`` defaults to the current time; a given ``now`` must carry its timezone. Appends are not locked, so
    one process at a time should record reads to a file.

    Raises:
        PreregError: ``evaluation`` is not a result of ``rule``, ``rule`` no longer matches its record, or the
            reads file's last line was cut short.
        ValueError: ``now`` has no timezone.
    """
    check_intact(rule)
    if evaluation.prereg != rule.id:
        raise PreregError(f"the evaluation is of {evaluation.prereg!r}, not of {rule.id!r}")
    if [hypothesis.name for hypothesis in evaluation.hypotheses] != [h.name for h in rule.hypotheses]:
        raise PreregError(f"the evaluation does not hold a result for each of {rule.id!r}'s hypotheses")
    at = datetime.now(UTC) if now is None else now
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError(f"now must carry its timezone, not {at!r}")
    at = at.astimezone(UTC)
    line = json.dumps(
        {
            "schema": READ_SCHEMA,
            "prereg": rule.id,
            "experiment": rule.experiment,
            "data_sha256": evaluation.data_sha256,
            "n": evaluation.n,
            "labels": evaluation.labels(),
            "at": at.isoformat(),
            "onus": onus.__version__,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    reads_path = Path(reads_path)
    if reads_path.is_file() and reads_path.stat().st_size > 0:
        with reads_path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            if existing.read(1) != b"\n":
                raise PreregError(f"{reads_path} does not end in a newline: its last write was cut short; repair it")
    with reads_path.open("a", encoding="utf-8") as reads:
        reads.write(line + "\n")
        reads.flush()
        os.fsync(reads.fileno())
    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
    return ReadReceipt(rule.id, evaluation.data_sha256, at, digest, reads_path)
