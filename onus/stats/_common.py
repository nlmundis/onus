"""What every part of onus.stats shares: its errors, its result type, exact inputs, and the decision rule."""

from dataclasses import dataclass
from fractions import Fraction

ALTERNATIVES = ("two-sided", "greater", "less")


class StatsError(ValueError):
    """An input onus.stats refuses rather than guess about."""


class EmptySampleError(StatsError):
    """A test or interval was asked for with no observations."""


class MissingDataError(StatsError):
    """A pair had a missing value and the caller asked for missing values to be refused."""


class UndeclaredMemberError(StatsError):
    """A result was added to a family that does not declare it."""


class IncompleteFamilyError(StatsError):
    """A family was adjusted before every declared member had a result."""


def exact(value: Fraction | int | str, name: str) -> Fraction:
    """Return ``value`` as an exact fraction; a float is refused, since 0.05 as a float is not 1/20.

    Raises:
        TypeError: ``value`` is a float, or not a number at all.
        ValueError: ``value`` is a string that is not an exact number, such as "nan", "inf", or "1/0".
    """
    if isinstance(value, bool) or not isinstance(value, Fraction | int | str):
        raise TypeError(f"{name} must be a Fraction, an int, or a string such as '0.05', not {value!r}")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name} must be an exact number such as '0.05', not {value!r}") from None


def probability(value: Fraction | int | str, name: str, *, open_interval: bool = False) -> Fraction:
    """Return ``value`` as an exact probability in [0, 1], or in (0, 1) when ``open_interval`` is set.

    Raises:
        ValueError: ``value`` lies outside the interval.
    """
    result = exact(value, name)
    if (open_interval and not 0 < result < 1) or not 0 <= result <= 1:
        interval = "(0, 1)" if open_interval else "[0, 1]"
        raise ValueError(f"{name} must lie in {interval}, not {result}")
    return result


def check_alternative(alternative: str) -> str:
    """Return ``alternative`` if it is one of "two-sided", "greater", or "less".

    Raises:
        ValueError: it is not.
    """
    if alternative not in ALTERNATIVES:
        raise ValueError(f"alternative must be one of {ALTERNATIVES}, not {alternative!r}")
    return alternative


def check_method(method: str, allowed: tuple[str, ...]) -> str:
    """Return ``method`` if this release implements it.

    Raises:
        ValueError: it does not.
    """
    if method not in allowed:
        raise ValueError(f"method must be one of {allowed}, not {method!r}")
    return method


def check_count(value: int, name: str) -> int:
    """Return ``value`` if it is a non-negative int (a bool is refused).

    Raises:
        TypeError: it is not an int.
        ValueError: it is negative.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, not {value!r}")
    if value < 0:
        raise ValueError(f"{name} must not be negative, not {value}")
    return value


@dataclass(frozen=True)
class TestResult:
    """The outcome of an exact test: its exact p-value and every count it was computed from.

    Attributes:
        test: which test ran: "binomial", "sign", or "mcnemar".
        method: how its p-value was computed; "exact" in this release.
        alternative: "two-sided", "greater", or "less".
        p_exact: the p-value as an exact fraction; decisions use this, never ``p_value``.
        successes: the count the test is about (successes, wins, or the first discordant count).
        n: the number of trials the test used (after ties and dropped pairs).
        null: the success probability under the null hypothesis.
        ties: pairs that were ties, excluded from ``n``.
        missing: pairs dropped for a missing value, excluded from ``n``.
        warnings: anything the caller should read before quoting the result.
    """

    __test__ = False  # A result type, not a test case, for any runner that collects by name.

    test: str
    method: str
    alternative: str
    p_exact: Fraction
    successes: int
    n: int
    null: Fraction
    ties: int = 0
    missing: int = 0
    warnings: tuple[str, ...] = ()

    @property
    def p_value(self) -> float:
        """The p-value as a float, for display only."""
        return float(self.p_exact)


def p_of(value: "TestResult | Fraction | int | str", name: str = "p-value") -> Fraction:
    """Return the exact p-value of a result, or ``value`` itself as an exact probability."""
    if isinstance(value, TestResult):
        return value.p_exact
    return probability(value, name)


def decide(result: "TestResult | Fraction | int | str", alpha: Fraction | int | str = "0.05") -> bool:
    """Return whether ``result`` rejects the null hypothesis at level ``alpha``: iff its exact p-value <= alpha.

    ``result`` may be a test result or an exact (adjusted) p-value. ``alpha`` is exact too, so a p-value of
    exactly 1/20 rejects at "0.05".
    """
    return p_of(result) <= probability(alpha, "alpha")
