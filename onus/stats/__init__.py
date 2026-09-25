"""Exact tests, intervals, multiplicity corrections, and power, with the standard library alone.

Every test returns a frozen ``TestResult`` carrying its exact p-value and the counts behind it, and
``decide(result, alpha)`` rejects iff that exact p-value is at most alpha. ``alternative`` and ``method`` are
keyword-only and have no default, so every call states its sidedness and method.
"""

from onus.stats._common import (
    EmptySampleError,
    IncompleteFamilyError,
    MissingDataError,
    StatsError,
    TestResult,
    UndeclaredMemberError,
    decide,
)
from onus.stats.binomial import binom_pmf, binom_tail, binomial_test, mcnemar_exact, paired_sign_test, sign_test
from onus.stats.intervals import Interval, clopper_pearson, wilson
from onus.stats.multiplicity import Family, benjamini_hochberg, holm
from onus.stats.power import (
    binomial_mde,
    binomial_power,
    rejection_region,
    sequential_size,
    sign_test_mde,
    sign_test_power,
)

__all__ = [
    "EmptySampleError",
    "Family",
    "IncompleteFamilyError",
    "Interval",
    "MissingDataError",
    "StatsError",
    "TestResult",
    "UndeclaredMemberError",
    "benjamini_hochberg",
    "binom_pmf",
    "binom_tail",
    "binomial_mde",
    "binomial_power",
    "binomial_test",
    "clopper_pearson",
    "decide",
    "holm",
    "mcnemar_exact",
    "paired_sign_test",
    "rejection_region",
    "sequential_size",
    "sign_test",
    "sign_test_mde",
    "sign_test_power",
    "wilson",
]
