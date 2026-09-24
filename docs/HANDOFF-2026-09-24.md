# Handoff: onus scaffold, PR #1 (2026-09-24)

This file lets a new session, including a cloud one, continue the work without the private notes it came from. It is a working note, not documentation. Delete it once PR #1 merges or it is replaced.

## State, verified 2026-09-24

- **PR #1** (`scaffold-56d7be31`, head `7d9ddc8`): the L1 scaffold (packaging, the `make check` gate, the repository's own invariant tests, `check_dist`, and the release workflow). Nothing past the scaffold has been started.
- **CI on `7d9ddc8`:** the "all checks passed" run 36031990495 concluded `success`.
- **Local `make check` on `7d9ddc8`:** rc=0, 49 tests, 100% coverage, dist check passed, 38 of 38 mutants caught, and the no-op spec survived.
- **Review:** four adversarial review rounds ran, which is the maintainer's cap. Of 45 confirmed findings, 32 are fixed and 13 are open (listed below). Verdict: **NOT READY**. A fifth round, or any merge, needs the maintainer's word.
- **This branch** (`handoff-b6fb45f7`) is `7d9ddc8` plus this file. Base your work on `scaffold-56d7be31`, not on this branch, so this file stays out of the PR.

## Rules for any session working here

- Every push, PR, merge, and tag needs the maintainer's explicit word, item by item. Work on a branch and commit, and do not push to `main` (the "protect main" ruleset refuses it anyway).
- Release tags never move ("release tags never move" ruleset: every `v*` tag is permanent, with no bypass). Do not create tags.
- **The repository is public.** Test fixtures are synthetic only. Before every push, scan the tree, the commit messages, and the PR body for home directory paths, real email addresses, and customer or company names. Run the scan with a positive control, a pattern known to match, so an empty result means something.
- A session never writes a tier-2 sign-off line. Sign-offs come only from the maintainer's own terminal.
- Interpreters are pyenv's exact 3.13.12 (main) and 3.11.14 (compat), passed to uv by path with `UV_PYTHON_DOWNLOADS=never`. In an environment without pyenv, say that the compat and interpreter stages cannot run there. Do not substitute another interpreter silently.
- Mark a deliberate corner-cut in place: `# ⚠ SHORTCUT (YYYY-MM-DD) — <what> — ceiling: <limit> — exit: <what lifts it>`.
- Paste the raw `make check` output, never piped or trimmed, and read the test count from it.

## The 13 open defects on PR #1

Each has a known fix. None is made yet.

1. **Major:** a `GNUmakefile` or `makefile` beside `Makefile`, holding `include Makefile` plus `.IGNORE:` or its own `check:` target, turns CI's `make check` green. The tests that forbid such a file run inside that same make. Fix: CI runs `make -f Makefile check`, pinned by the exact run line and the approved `check.yml`.
2. **Major:** a `ruff.toml`, `.ruff.toml`, `mypy.ini`, `.mypy.ini`, `.coveragerc`, or `setup.cfg` takes precedence over pyproject's tool tables and can switch off lint, types, or the coverage floor. Fix: refuse those names at the root, or pass `--config pyproject.toml` explicitly.
3. **check_dist exit codes:** "defect" is exit 1, the same code Python gives any uncaught exception, so a missing `uv` or `git`, or an `OSError` while copying, makes the release call the tag spent. Fix: wrap `OSError` in `BuildError`, give DEFECTIVE a distinct code, and add a test.
4. **check_dist build failures:** every nonzero `uv build` exit is called NOT_BUILT ("re-run"), including a backend error caused by committed config, which a re-run cannot fix.
5. **Stray-module check:** any untracked `*.py` under `onus/` (editor lock files, AppleDouble `._*` files, ignored paths) is treated as a needed module.
6. **AGENTS.md** says a failed gate always spends the tag, but a transient failure can be re-run.
7. **AGENTS.md** says any `v*` tag starts the release workflow. That ignores a tag on a commit with no `release.yml`, which today includes main's `e36cb6e`.
8. **Makefile comment:** the "read before" wording is wrong, because make uses only the first makefile it finds.
9. **check_dist's egg-info rationale** contradicts "gitignored caches".
10. **AGENTS.md** does not mention that the build backend is unpinned.
11. **The py.typed remedy** does not cover an `exclude-package-data` cause.
12. **The "tests/" remedy text** is not pinned by a test.
13. **The COMPAT_GIVEN half** of the override logic is not pinned.

**What the four rounds taught:** pinning a guard by a fragment of its text failed every round. Each round found a new way to switch the guard off: `|| true`, a `-` prefix (GNU `make -n` strips it), `if: always()`, a GNUmakefile, a `ruff.toml`. Pin whole files (`tests/approved/` holds reviewed byte copies of the Makefile, the workflows, pyproject.toml, and MANIFEST.in), and refuse sibling configs by name. The common flaw was tests that checked a guard's text was present, not that the guard could fail.

## Next actions, in order

1. Fix defects 1 to 13 on a branch off `scaffold-56d7be31`, each with a test that fails first. Add a mutant to `mutt_check.toml` wherever a guard is new. Run `make check`.
2. Report to the maintainer: what changed, the raw `make check` result, and the leak scan with its positive control. Then wait for the word to push and for a decision on a fifth review round.
3. After PR #1 merges: L1 steps 2 to 6 below, each its own PR.

## L1, library v0.1.0: order of work

1. ~~The scaffold.~~ (PR #1.)
2. `binomial`, `intervals`, `multiplicity`, `power`, with the oracles, the reference fixture, and the sims cross-check.
3. `prereg`, `report`.
4. `approval` (the `scrub`, `baseline`, and `signoff` subpackages).
5. `property`, to be named `onus.invariants`, since `property` shadows the builtin. It is the only module that imports hypothesis.
6. The v0.1 mutants and the no-op spec.

Then the leak scan, and a push, PR, merge, and `v0.1.0` tag, each on the maintainer's word.

**Verify:** every mutant caught, the no-op survives, `make reference` reproduces the fixture byte for byte, and `git status --porcelain` is empty after two runs.

**Planned subpackages:** `onus.stats`, `onus.prereg`, `onus.report`, `onus.baseline` (tier 1), `onus.signoff` (tier 2), `onus.scrub`, `onus.invariants`. `prereg` imports `signoff`, because amendments are bound by sign-offs.

**v0.2.0 (L2), later:** `ranks`, `cluster`, `rate_ratio_test`, their oracles and mutants, and `make calibrate`.

## Design decisions (maintainer, 2026-09-23)

- "Hypothesis testing" means both statistical significance tests and property-based tests (the Hypothesis library).
- Hosted public on GitHub under MIT and pinned by git tag. Nothing goes to PyPI.
- Approvals come in two tiers. Tier 1 baselines may be re-recorded by a session, and the PR diff is the review. Tier 2 sign-offs on ground truth come only from the maintainer, from their own terminal, as hash-bound ledger lines.
- Pre-registered rules are frozen once live. Fixes land as dated amendments before the affected verdict is read.
- Vetoable defaults: floor 3.11; exact rationals; reject iff p ≤ α; two-sided binomial only at p=½; n=0 raises; `evaluate` and `record_read` are split, and `render` requires a receipt; a v0.1/v0.2 split; adopters use `max_examples=50`; received files go to `$TMPDIR`.

## Library specification

The spec below is copied from the design plan. Where it names `onus.property` or the `property` extra, read `onus.invariants` and `invariants`, as the scaffold already does.

#### Shape
- **Layout:** a flat package `onus/` at the repo root, with `py.typed`.
- **Python:** `requires-python >=3.11`, with CI covering 3.11–3.14. `.python-version` is `3.13.12`, and the venv is built with `uv venv --seed --python "$(pyenv prefix 3.13.12)/bin/python3" venv`.
- **`compat`** runs `compileall` on a pyenv-installed exact `3.11.x`, which `pyenv install` adds on the maintainer's go-ahead, never on uv's discovery.
- **Dependencies:** `dependencies = []`. The only extra is `property = ["hypothesis>=6.168.1,<7"]`, and only `onus.property` imports it.
- **Tooling** is (black and ruff at 120 with D, ANN, B, UP, I, google docstrings; strict mypy; coverage `branch=true`, `fail_under=95`). **`tools/` is inside lint, type, and coverage scope.**
- **Packaging and release** are: setuptools≥77, dynamic `__version__`, SPDX MIT, and `tests/test_repo.py` (version support, a stdlib-only import with hypothesis blocked, AGENTS.md targets, MutationSpec, a `.hypothesis/` gitignore check). `release.yml` and the rulesets are already in the scaffold. Nothing goes to PyPI.
- **Gate:** `make check` = `format lint types coverage test compat mutants`. The opt-in targets `explore`, `reference`, and `calibrate` are never part of `check`.
- **Library test fixtures are synthetic only.** No client names, vault paths, or real addresses.

#### stats: stdlib only, exact rationals
- **General rules:**
  - Exact tails are computed in `fractions.Fraction`, and results are frozen dataclasses (`p_exact`, `p_value`, counts, ties, missing, method, warnings).
  - `decide(result, alpha="0.05")` rejects iff `p_exact <= Fraction(alpha)`.
  - **`alternative` and `method` are keyword-only with no default.**
- **v0.1:**
  - `binomial`: `binom_tail`; `binomial_test` (two-sided only at p=½); `sign_test(wins, losses, *, ties, alternative)`; `paired_sign_test(first, second, *, alternative, missing: "refuse"|"drop")`; `mcnemar_exact`.
  - `intervals`: `wilson(k, n, *, confidence="0.95", z=None)` and `clopper_pearson`, both raising `EmptySampleError` at n=0.
  - `multiplicity`: `holm`, `benjamini_hochberg`, and `Family`, which refuses undeclared members and incomplete adjustment.
  - `power` (exact DP): `sign_test_power`, `sign_test_mde`, `binomial_power`/`binomial_mde`, `sequential_size`.
- **v0.2 (step L2):**
  - `ranks.mann_whitney(..., method: "exact"|"normal")`: exact is the tie-conditional permutation null; normal has tie and continuity corrections.
  - `cluster.cluster_bootstrap`, reporting valid draws, raising `InsufficientDraws` below b/2, and warning under 20 clusters.
  - `cluster.cluster_sign_flip_test`.
  - `binomial.rate_ratio_test`.
- **Freeze rule:** a released function's numeric output never changes; a fix is a new `method=` value. Known-wrong legacy behaviour is never reproduced in the library.
- **Out of scope:** a Bayesian layer, automatic test choice, post-hoc power, sequential-until-significant helpers, numpy/scipy at runtime, and a pytest plugin.

#### prereg and report
- **`prereg_id(path)`** returns `f"{name}@{sha256[:12]}"`.
- **Records** use `"prereg/1"` JSON and reject unknown keys. Fields: experiment, registered, hypotheses `[{name, test, alternative, alpha, family}]`, families, unit, cluster_key, order_key, horizon `{kind: count|days, n|days, start}`, looks, `bound_artifacts {path: sha256}`, and provenance.
- **Amendments** are separate `<stem>.amend-YYYY-MM-DD.json` files, each bound by a tier-2 sign-off.
- **Evaluation and read-recording are split**, because the name must not hide a write:
  - `evaluate(rule, data)` is pure. It refuses before the horizon and uses exactly the first N units in `order_key` order.
  - `record_read(rule, result, *, reads_path) -> ReadReceipt` appends to the session-writable `reads.jsonl`.
  - `report.render(result, decision, *, receipt, prereg, family)` **requires a receipt**, so displaying a verdict records it.
- **Post hoc:** an amendment signed after the first read of a hypothesis it touches labels that hypothesis post hoc. The labels are met / not met / pending / post hoc.
- **`render`'s sentence** carries n, discordant/ties, sidedness, the family correction, **the MDE whenever the result is not significant**, the prereg id, a data hash, and the library version. It has no wall clock. Without a prereg it says "exploratory".
- **`report.assert_quoted(doc, sentence)`** checks that a rendered sentence is quoted verbatim in a document.

#### approval
- **`scrub`:** `chain`, `iso_dates`, `iso_timestamps`, `paths(mapping)` (including `/private/var`↔`/var`), `uuids`/`hex_ids`, `pattern`, and `redactor(fn)`. No PII rules ship, and numeric scrubbers on stats output are forbidden.
- **Tier 1:**
  - Tests use `ApprovedMixin.assertApproved(received, *, label="", ext=".md")`. Files are `tests/approved/<module>.<Class>.<method>[.<label>].approved<ext>`, committed.
  - On a mismatch the test fails with a diff and writes the received file under `$TMPDIR/onus-received/<repo-sha8>/`.
  - A missing approved file fails; it never skips.
  - **Recording** happens only under `make approve`, which sets `ONUS_APPROVE_ROOT="$(git rev-parse --show-toplevel)"` for the invoking checkout. That includes a session's own worktree. The helper refuses unless the approved path resolves under that root **and** the root is a git work tree. mutt_check sandboxes are neither, so they refuse.
  - `forbid=` patterns apply while recording. Approved files carry the producer, `inputs_sha256`, and the scrubbers, and never a timestamp. `ApprovedProducersAreReal` refuses test-local or mock producers.
- **Tier 2 (`signoff`):**
  - **Ledger:** the adopter passes the ledger path. Lines are `{"schema":"signoff/1", artifact, sha256, bytes, bound, supersedes, reviewed_by, at, tool, prev}`, hash-chained. Blobs are content-addressed with mode 0444.
  - **Ids** are exact, matching `^[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._/-]+$`; no globs.
  - `check_signoff` returns SIGNED, UNSIGNED, CHANGED (with a diff), REVOKED, or CORRUPT, and **fails closed** on a malformed line or a broken chain.
  - **`record`** refuses when any session env var is set or `/dev/tty` can't be opened, shows the diff, reads a typed 8-hex prefix from `/dev/tty`, then appends under flock and fsync.
  - **These are tripwires; the control is Step H.**

#### property (`[property]` extra)
- **Profiles:** `use_profile()` defaults to "gate" (`derandomize=True`, `database=None`, `deadline=None`, `max_examples=50` in adopters and 200 in the library; health-check failures fail). "explore" loads only under `ONUS_HYPOTHESIS_PROFILE=explore`, with its database in `~/.local/state/onus/explore/<repo>`.
- **Storage:** `HYPOTHESIS_STORAGE_DIRECTORY` points outside the worktree, and `.hypothesis/` is gitignored anyway.
- **Strategies** are independent grammars only (`emails`, `in_context`, `markdown_text`, `normalization_variants`). Adopters own the oracles and bounds.
- **`python -m onus.property examples <log>`** prints `@example` lines for a human to paste. It never edits source.

#### How we know the library is right
1. **Brute-force oracles** in `make check` (all 2^n for n≤14, all labelings with ties for n+m≤12, all 2^C flips), with two coverage tests:
   - **Exact size:** size ≤ α for n≤200 and α∈{.01,.05,.10}.
   - **Clopper-Pearson coverage** at least nominal on a 1001-point grid.
2. **The reference fixture:** `make reference` runs `uvx --with scipy==PIN --with statsmodels==PIN python tools/reference/make_reference.py`. The output is committed with the script sha256 and versions in its header, and a drift test guards it.
3. **Hypothesis properties:**
   - tail complement; two-sided = min(1, 2·min tail); sign-test symmetry and monotonicity;
   - U sums, and U(x,y)+U(y,x)=nm;
   - interval containment and reflection;
   - Bonferroni ⊆ Holm ⊆ BH;
   - power monotone in effect and α (never in n);
   - `sequential_size` with one look equals the fixed size.
4. **Simulation cross-check:** A Monte Carlo script `tools/sims/ht_sims.py` (write it fresh; the earlier draft is not in this repo) is run, with its output committed. A test asserts that the exact DP matches within 3 SE.
5. **Mutants** in `mutt_check.toml`, one named killer class each:
   - **Tails and tests:** tail off-by-one; sidedness flipped; two-sided not doubled; cap removed; `<=`→`<` (killed at α=1/16 with 4–0); continuity correction dropped; tie variance dropped.
   - **Intervals:** wilson z hardcoded; n0 returns a zero interval.
   - **Families and power:** Holm running-max removed; incomplete family allowed; undeclared family member accepted; MDE uses the observed effect.
   - **Missing data and defaults:** `missing="refuse"` silently drops; `alternative` gains a default; `method` gains a default.
   - **Bootstrap:** invalid draws dropped silently; percentile off-by-one.
   - **Pre-registration:** horizon not enforced; `evaluate` uses more than the first N or ignores `order_key`; unknown prereg key accepted; amendment after a read accepted; `render` without a receipt.
   - **Tier 1:** approved auto-overwritten; missing approved file auto-created or skipped; received file written into the worktree; `make approve` records outside the root; `forbid` ignored while recording.
   - **Tier 2:** record allowed under a session; tty→stdin; glob id accepted; corrupt line skipped; broken `prev` chain accepted.

   `mutt_check.noop.toml` must **survive**. Mutated files are restored from a pre-mutation snapshot, never `git checkout <path>`.

