"""Simulate how often the sign test rejects, to cross-check onus.stats.power's exact figures.

Each case draws win/loss sequences with a fixed seed, runs onus.stats.sign_test at every look, and counts how
often any look rejects. The rates are written to a JSON file that is committed; tests/test_stats.py requires
each to lie within 3 standard errors of the exact power or sequential size. The header carries this
script's sha256, so a changed case list shows up as a stale file.
"""

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from onus.stats import decide, sign_test

SCRIPT = Path(__file__).resolve()
SEED = 20260925
# (name, win probability, looks, alpha, alternative); one look is a fixed-sample power or size.
CASES: list[tuple[str, str, list[int], str, str]] = [
    ("size, n=15, two-sided", "1/2", [15], "0.05", "two-sided"),
    ("power, n=20, p=0.7, greater", "7/10", [20], "0.05", "greater"),
    ("power, n=30, p=0.65, two-sided", "13/20", [30], "0.05", "two-sided"),
    ("power, n=40, p=0.4, less", "2/5", [40], "1/10", "less"),
    ("peeking size, looks 10..50, two-sided", "1/2", [10, 20, 30, 40, 50], "0.05", "two-sided"),
]


def rejects(rng: random.Random, p_win: float, looks: list[int], alpha: str, alternative: str) -> bool:
    """Draw one sequence of pairs and return whether the sign test rejects at any look."""
    wins = n = 0
    for look in looks:
        while n < look:
            wins += rng.random() < p_win
            n += 1
        result = sign_test(wins, n - wins, ties=0, alternative=alternative, method="exact")
        if decide(result, alpha):
            return True
    return False


def simulate(reps: int, seed: int = SEED) -> list[dict[str, Any]]:
    """Return each case with the share of ``reps`` simulated runs that rejected."""
    out = []
    for name, p_win, looks, alpha, alternative in CASES:
        rng = random.Random(f"{seed}:{name}")
        numerator, denominator = (int(part) for part in p_win.split("/"))
        hits = sum(rejects(rng, numerator / denominator, looks, alpha, alternative) for _ in range(reps))
        out.append(
            {
                "name": name,
                "p_win": p_win,
                "looks": looks,
                "alpha": alpha,
                "alternative": alternative,
                "reps": reps,
                "rate": hits / reps,
            }
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Write the simulated rates to the given path."""
    parser = argparse.ArgumentParser(description="Simulate sign-test rejection rates for onus.stats.")
    parser.add_argument("out", type=Path, help="where to write the JSON results")
    parser.add_argument("--reps", type=int, default=20000, help="simulated runs per case")
    args = parser.parse_args(argv)
    results = {
        "header": {"script_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(), "seed": SEED},
        "cases": simulate(args.reps),
    }
    args.out.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(CASES)} cases of {args.reps} runs", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
