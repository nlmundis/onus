---
date: 2026-09-25
scope: PR #1 (the L1 scaffold) from review round 5 through merge
state: done
prs: [1, 2]
next: L1 step 2, a PR from main adding binomial, intervals, multiplicity, and power with their oracles
---

# Handoff: scaffold merged (2026-09-25)

## State

- **main is `0bb3567`**, the squash merge of PR #1: the L1 scaffold (packaging, the `make check` gate, the
  repository's own invariant tests, `tools/check_dist.py`, and the release workflow). No library code yet.
  No tag exists; `onus.__version__` is `0.0.0`.
- **Gate on the merged tree** (PR head `782840c`, identical to main's tree): `make check` exit 0 on pyenv's
  exact 3.13.12 and 3.11.14, 89 tests, 100% branch coverage, the dist check passed, 103 of 103 mutants caught,
  the no-op spec survived, and `git status --porcelain` empty afterwards. CI (3.11 to 3.14 and the required
  "all checks passed") was green on `782840c`.
- **Branches:** `scaffold-56d7be31` and `handoff-b6fb45f7` are deleted once this note is on main.
- **Where things are written down:** AGENTS.md holds the rules and commands. The library specification, the
  L1 order of work, and the maintainer's design decisions are in `2026-09-24-scaffold-review-rounds-1-4.md` in
  this folder; they still hold.

## Done since the 2026-09-24 note

- Fixed the 13 defects that note listed (commits on PR #1, each with a test that failed first and a mutant).
- Review round 5 (limited to those fixes) confirmed 5 findings, all fixed: ignore files hiding modules from
  lint and format, a root `uv.toml` read by every `uv run` stage, the exit-4 wording, and two nits.
- Review round 6 (the whole PR, 116 agents) confirmed 34 findings and disputed 13. Fixed on PR #1: F2, F4, F5
  with G2.1, F6, F8, F9 with F18, F12, F13, F27, G1.1 and G1.2 (the PR description lists what each was).
- Decided with the maintainer: no history rewrite of the PR branch; the squash merge kept the early commits'
  working notes out of main.
- Started this folder and the AGENTS.md rule that each session ends with a note here.

## Open

- **Round 6 findings not fixed:**
  - F11: "a 4 that repeats is the commit's own" is too strong for a long network outage; uv exits 1 for an
    unsatisfiable requirement and 2 for a fetch failure, so the build step could tell them apart.
  - F15: a subpackage named `build`, `dist`, or `venv` skips format and lint (black's and ruff's any-depth
    exclusions), and the unanchored `.gitignore` entries hide it from `git add`.
  - F16: a folder without `__init__.py` ships in the wheel but counts for nothing in coverage, and a test
    folder without one never runs.
  - F17: a `.gitattributes` can collapse pinned-file diffs in review.
  - F19: the stdlib-only import probe runs with the checkout on `sys.path`, and checks import time only.
  - F21: `RulesetRecordTest` does not check main.json's rule parameters.
  - F24: the release job's step scripts are checked only as text and first run on a permanent tag.
  - Nits: F22, F28 to F31, F33, F34, F36, F38, F39.
  - The 13 disputed findings (F3, F10, F23, F25, F26, F32, F35, G1.3, G1.4, G2.2, G3.3, G4.1, G4.2) wait for
    the maintainer's judgement.
- **Known limits, documented:** a plain local `make check` beside a GNUmakefile reads it (CI's
  `make -f Makefile` does not); a runner-side failure inside the build step reads as a spent tag; the build
  backend is unpinned; a change to `check.yml` itself can drop its pin step.
- **Environment:** in a cloud session python.org is unreachable, so pyenv's two interpreters were built from
  CPython's `v3.13.12` and `v3.11.14` git tags. A new cloud session has to do the same before `make check`
  can run; `pyenv install` needs the maintainer's word.

## Next actions

1. L1 step 2: `binomial`, `intervals`, `multiplicity`, `power`, with the brute-force oracles, the reference
   fixture, and the sims cross-check, as one PR from main (see the 2026-09-24 note for the specification).
2. Decide which open round-6 findings to fix before v0.1.0, and which of the 13 disputed ones matter.
3. L1 steps 3 to 6 as their own PRs, then the leak scan and the `v0.1.0` tag, each on the maintainer's word.
