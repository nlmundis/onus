"""Write the reference fixture: what scipy and statsmodels say for a fixed set of onus.stats cases.

``make reference`` runs this with pinned scipy and statsmodels, outside any project environment, and the output
is committed. Its header carries this script's sha256 and the versions that produced it, so the drift test in
tests/test_stats.py notices both a stale fixture and a changed case list. onus is never imported here: the
fixture is an independent second opinion.
"""

import argparse
import hashlib
import importlib
import json
import platform
import sys
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPT = Path(__file__).resolve()

BINOMIAL = [
    (k, n, p, alternative)
    for n in (1, 5, 10, 17, 30, 100)
    for k in sorted({0, 1, n // 3, n // 2, n - 1, n})
    for p, alternative in (
        ("1/2", "two-sided"),
        ("1/2", "greater"),
        ("1/2", "less"),
        ("1/3", "greater"),
        ("3/10", "less"),
    )
]
INTERVALS = [
    (k, n, confidence)
    for n in (1, 7, 10, 40, 250)
    for k in sorted({0, 1, n // 4, n // 2, n - 1, n})
    for confidence in ("0.9", "0.95", "0.99")
]
FAMILIES = [
    ["1/100", "1/25", "3/100"],
    ["1/1000", "1/100", "1/50", "3/100", "1/20", "7/100", "1/2"],
    ["1/5", "1/5", "1/2", "9/10"],
    ["1/10000"],
]


def interval_case(proportion: ModuleType, k: int, n: int, confidence: str) -> dict[str, Any]:
    """Return one interval case: statsmodels' Wilson and Clopper-Pearson ("beta") bounds for k of n."""
    case: dict[str, Any] = {"k": k, "n": n, "confidence": confidence}
    for method, name in (("wilson", "wilson"), ("clopper-pearson", "beta")):
        bounds = proportion.proportion_confint(k, n, alpha=1 - float(Fraction(confidence)), method=name)
        case[method] = [float(bound) for bound in bounds]
    return case


def build(stats: ModuleType, proportion: ModuleType, multitest: ModuleType) -> dict[str, Any]:
    """Return the fixture's cases, each with the answer the given scipy and statsmodels modules give."""
    return {
        "binomial": [
            {
                "k": k,
                "n": n,
                "p": p,
                "alternative": alternative,
                "p_value": float(stats.binomtest(k, n, float(Fraction(p)), alternative=alternative).pvalue),
            }
            for k, n, p, alternative in BINOMIAL
        ],
        "intervals": [interval_case(proportion, k, n, confidence) for k, n, confidence in INTERVALS],
        "families": [
            {
                "p_values": family,
                "holm": [
                    float(v) for v in multitest.multipletests([float(Fraction(p)) for p in family], method="holm")[1]
                ],
                "benjamini-hochberg": [
                    float(v) for v in multitest.multipletests([float(Fraction(p)) for p in family], method="fdr_bh")[1]
                ],
            }
            for family in FAMILIES
        ],
    }


def header(versions: dict[str, str]) -> dict[str, str]:
    """Return the fixture header: this script's sha256, the Python that ran it, and the library versions."""
    return {
        "script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        **versions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the fixture to the given path."""
    parser = argparse.ArgumentParser(description="Write onus.stats' reference fixture from scipy and statsmodels.")
    parser.add_argument("out", type=Path, help="where to write the JSON fixture")
    args = parser.parse_args(argv)
    scipy = importlib.import_module("scipy")
    statsmodels = importlib.import_module("statsmodels")
    cases = build(
        importlib.import_module("scipy.stats"),
        importlib.import_module("statsmodels.stats.proportion"),
        importlib.import_module("statsmodels.stats.multitest"),
    )
    fixture = {"header": header({"scipy": scipy.__version__, "statsmodels": statsmodels.__version__})} | cases
    args.out.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {sum(len(v) for v in cases.values())} cases", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
