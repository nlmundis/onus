"""Adjusting p-values for a family of tests: Holm, Benjamini-Hochberg, and a declared Family.

The adjusted p-values are exact fractions in the order they were given. A Family is declared before any
result is read, refuses a member it did not declare, and refuses to adjust until every member has a result,
so a family cannot quietly shrink to the tests that came out well.
"""

from collections.abc import Iterable, Sequence
from fractions import Fraction

from onus.stats._common import (
    IncompleteFamilyError,
    TestResult,
    UndeclaredMemberError,
    decide,
    p_of,
    probability,
)

CORRECTIONS = ("holm", "benjamini-hochberg")
PValue = TestResult | Fraction | int | str


def _exact_all(p_values: Sequence[PValue]) -> list[Fraction]:
    if not p_values:
        raise ValueError("there are no p-values to adjust")
    return [p_of(value) for value in p_values]


def holm(p_values: Sequence[PValue]) -> list[Fraction]:
    """Return Holm's step-down adjusted p-values, in the order given.

    The i-th smallest of m p-values is multiplied by m - i + 1, and each adjusted value is at least the one
    before it in that order (the running maximum), capped at 1. Holm controls the familywise error rate.
    """
    ps = _exact_all(p_values)
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adjusted = [Fraction(0)] * m
    running = Fraction(0)
    for rank, i in enumerate(order):
        running = max(running, min(Fraction(1), (m - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def benjamini_hochberg(p_values: Sequence[PValue]) -> list[Fraction]:
    """Return Benjamini-Hochberg step-up adjusted p-values, in the order given.

    The i-th smallest of m p-values is multiplied by m / i, and each adjusted value is at most the one after it
    in that order (the running minimum from the top), capped at 1. It controls the false discovery rate.
    """
    ps = _exact_all(p_values)
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adjusted = [Fraction(0)] * m
    running = Fraction(1)
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, ps[i] * m / (rank + 1))
        adjusted[i] = running
    return adjusted


class Family:
    """A family of hypotheses declared before any result is read, adjusted together by one correction.

    Args:
        name: what the family is called in reports.
        members: every hypothesis in the family, by name.
        correction: "holm" or "benjamini-hochberg"; there is no default.
    """

    def __init__(self, name: str, members: Iterable[str], *, correction: str) -> None:
        """Declare the family and its members."""
        self.name = name
        self.members = tuple(members)
        if not self.members:
            raise ValueError(f"family {name!r} declares no members")
        if len(set(self.members)) != len(self.members):
            raise ValueError(f"family {name!r} declares a member twice: {self.members}")
        if correction not in CORRECTIONS:
            raise ValueError(f"correction must be one of {CORRECTIONS}, not {correction!r}")
        self.correction = correction
        self._results: dict[str, Fraction] = {}

    def add(self, member: str, result: PValue) -> None:
        """Record ``member``'s result (a test result or an exact p-value).

        Raises:
            UndeclaredMemberError: the family does not declare ``member``.
            ValueError: ``member`` already has a result.
        """
        if member not in self.members:
            raise UndeclaredMemberError(f"family {self.name!r} does not declare {member!r}; it declares {self.members}")
        if member in self._results:
            raise ValueError(f"{member!r} in family {self.name!r} already has a result")
        self._results[member] = p_of(result)

    def adjusted(self) -> dict[str, Fraction]:
        """Return each member's adjusted p-value.

        Raises:
            IncompleteFamilyError: a declared member has no result yet.
        """
        present = [member for member in self.members if member in self._results]
        pending = [member for member in self.members if member not in self._results]
        if pending:
            raise IncompleteFamilyError(f"family {self.name!r} has no result yet for {pending}")
        adjust = holm if self.correction == "holm" else benjamini_hochberg
        return dict(zip(present, adjust([self._results[member] for member in present]), strict=True))

    def decide(self, alpha: Fraction | int | str = "0.05") -> dict[str, bool]:
        """Return, for each member, whether its adjusted p-value rejects at ``alpha``."""
        probability(alpha, "alpha")
        return {member: decide(p, alpha) for member, p in self.adjusted().items()}
