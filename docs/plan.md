# The onus plan

This is the library's plan: what onus is for, the decisions that bind it, how its correctness is established,
and the order of work. It is the canonical copy. Amendments land here, dated, by pull request; a change that
contradicts a decision below is an amendment, not an edit. The projects that use onus (the adopters) are
planned outside this repository; this plan covers only what they need from the library.

The plan was written on 2026-09-23 and kept outside the repository until 2026-09-29, when its library sections
moved here. The progress log is `docs/handoffs/`.

## Purpose

Three problems, seen across the maintainer's own projects, motivate it:

- **Weak verdicts read as evidence.** A small comparison can have so little power that "not met" says almost
  nothing, and nothing on the page says so.
- **Peeking inflates error.** A one-sided sign test at a nominal 5% has an exact size of 0.0443 at 100
  non-tied pairs. Read at every 10 pairs up to 100, it rejects at least once under the null with probability
  0.1250 (`onus.stats.sequential_size(range(10, 101, 10), alpha="0.05", alternative="greater")`, against
  `[100]` for the single look).
- **Copies drift.** Three hand-written sign and binomial tests in those projects disagreed on sidedness.

onus answers them with one small, public, dependency-free library:

- **Exact, hard-to-misuse statistical tests**, with pre-registration records that fix a rule before its data.
- **Property-based testing** (Hypothesis) that is deterministic inside the gate.
- **Two-tier approval testing:** tier 1 baselines that a working session may re-record, where the pull
  request diff is the review; and tier 2 sign-offs, for ground truth, that only a person makes from their own
  terminal.

**Nothing already read may move.** Code that produced a verdict someone has read is frozen and never calls
the library. The library serves new experiments, and an adopter proves parity with differential tests.

## Decisions (2026-09-23)

Numbered as when they were made; the gaps are decisions about the adopters, kept with them.

- **1. Both meanings of "hypothesis testing"** are in scope: statistical significance, and property-based
  testing with Hypothesis.
- **3. Hosting:** public on GitHub, MIT, pinned by git tag. Nothing goes to PyPI.
- **4. Two approval tiers.** Tier 1 (baseline) may be re-recorded by a session; tier 2 (sign-off) is the
  maintainer's alone, from their own terminal, as a hash-bound ledger line.
- **5. Live pre-registered rules are frozen.** A fix arrives as a dated amendment, recorded before the affected
  verdict is read.
- **6. The name** is `onus` (onus probandi: the claim carries its own proof). Its jobs are several, so each
  became a subpackage named by intent (see Shape).
- **8. The library is a runtime dependency for new experiments** only. Frozen legacy functions stay untouched.
- **9. Tier-2 hardening:** the library's tripwires, plus a control outside the library that keeps agent
  sessions from making sign-offs (step H). Signed ledger lines and a ledger mirror were declined for now.

## Amendment 1 (2026-09-29): prereg v0.1 defaults

The maintainer ratified the five defaults that `onus.prereg` (PR #5) chose, and left the count-horizon gap
below open for L1 step 4; the open item's wording came from an adversarial review of this plan, which the
maintainer approved. Each default binds v0.1 and is revisited only by a later dated amendment:

- **`cluster_key` must be null.** `load` refuses any other value until v0.2 adds `cluster`, because v0.1
  `evaluate` treats every unit as independent and would silently ignore a declared cluster, giving
  anti-conservative p-values.
- **`looks` must be `[horizon]`.** No interim reads; sequential helpers stay out of scope, and `status`
  reports "pending" before the horizon without a p-value. For a days horizon, `evaluate` trusts the caller's
  `as_of`; Amendment 2, D5 decides how an early read is recorded, and is built with `report`.
- **Each hypothesis states `method`.** v0.1 accepts only `"exact"`. The method is fixed before the data
  because v0.2's `mann_whitney(method=...)` makes the choice change p.
- **A days horizon's window may not open before `registered`** (checked only against the record's own
  `registered` date).
- **`Rule` holds read-only mappings**, so it cannot be pickled or deep-copied. A dated amendment revisits this
  when the first adopter needs either.
- **Open, owner: the session that starts L1 step 4.** A count horizon has no equivalent check: `evaluate`
  takes the first N units by `order_key` with no date test, so they can predate registration. Decide whether
  to add a check (for example, a date-valued `order_key`, or a `start` for count horizons) or to disclose it
  as a limit, and decide it before the first adopter writes a count-horizon record; if that record comes
  first, its `provenance` discloses the gap. A check against `registered` alone only tests the record against
  itself, because the record's author types `registered`, so the decision names what witnesses that date
  (for example, the tier-2 sign-off time).

## Amendment 2 (2026-09-29): report design (L1 step 3, part 2)

Options were drafted and checked by adversarial review against `f7a3c51` before the maintainer chose; the
review changed three of the recommendations (D1, D5, D7). Each choice binds v0.1:

- **D1, receipt binding: re-derive from the data.** `render(rule, data, name, *, receipt, reads_path,
  as_of=None)` runs `evaluate` itself. It requires a line in the caller-named reads file (equal to
  `receipt.reads_path` once resolved) whose sha256 is `receipt.line_sha256`, and whose prereg, experiment,
  data_sha256, n, labels, and at all match. Every number in the sentence comes from the data in that call,
  so a hand-built receipt or a hand-edited `Evaluation` cannot be rendered. render does file I/O. Ship
  `receipt_from_line(reads_path, line_sha256)` so that a second process never hand-builds a receipt.
- **D2, MDE power: a fixed `Fraction(4, 5)`, printed** ("MDE at 80% power"). It is computed at the test's
  non-tied n (`TestResult.n`, not `Evaluation.n`), so it is conditional on the observed ties, and the sentence
  says so. With no rejection region, the sentence says "no outcome at this n can reach significance at level
  α". When α is so large that the test already has 80% power, it says "no MDE exists". The constant is frozen
  once released, because `assert_quoted` pins sentences. An optional per-hypothesis `power` key defaulting to
  4/5 may be added later; it is additive.
- **D3, MDE alpha: α/m**, where m is counted from the rule's family, named in the sentence as a Bonferroni
  bound. With exact fractions, a raw p at or below α/m is met under Holm or Benjamini-Hochberg whatever the
  other members show, so this is a guaranteed floor on power. It is conservative: it overstates the MDE,
  loosely for BH and for large families.
- **D4, exploratory: `render_exploratory(result)`**, which accepts a `TestResult` only and raises TypeError on
  anything else. The sentence starts "Exploratory:" and carries sidedness, the null, ties, missing, method,
  warnings, the exact p, and the onus version. It has no met / not met, no significance, and no MDE, because
  there is no alpha. `render` always requires a receipt. Known gap: a pre-registered hypothesis's `.result`
  can still be printed this way unrecorded, as plain attribute access already allows.
- **D5, early read: record and flag.** `Evaluation` stores `as_of`. `record_read` always appends, and refuses a
  days-horizon `Evaluation` without `as_of`. Each line records `as_of` and `early`, which is true when the read
  time is before `horizon.end` 12:00 UTC, the moment the window has closed in every time zone. render states
  no met / not met for an early read and shows "read early", beside the post hoc label; Amendment 3, E3, drops
  its MDE clause too.
- **D6, re-read on different data: seal, with a recorded override.** `record_read` refuses a read whose
  data_sha256, n, or labels differ from an earlier read in the same reads file with the same experiment or
  record stem. It allows one only when `supersedes=<the first read's line sha256>` and `reason=` are passed,
  and writes both into the line; render then shows "re-read on different data; first read <hash>". The
  check-then-append takes a lock (flock), and a malformed earlier line refuses. The seal binds only the reads
  file it is given.
- **Schema:** the read line moves from `read/1` to `read/2`, carrying `as_of`, `early`, `supersedes`, and
  `reason`. No adopter reads file exists yet.
- **D7, `prereg_id`: keep the stem.** No code change.
- **D8, the read time (decided after the review raised it): `record_read` loses `now=`.** It reads the clock
  through one private function that tests patch, so the recorded time, and with it `early` (D5), is not the
  caller's to choose. This changes `record_read`'s merged but unreleased signature; the test that pins the
  exact line compares every field but `at`, and checks that `at` lies between two clock reads.

## Amendment 3 (2026-09-29): report details

The review of `report` left three questions the spec did not decide (its findings F3, F6, and F7's case half),
and the build left three more; the maintainer chose each from options. Each choice binds v0.1. A second review,
of what these choices built, found where the build fell short of them; the notes marked "as built" record the
result:

- **E1, `assert_quoted`: every copy must match (F3).** `assert_quoted(doc, sentence)` takes the prereg id and
  the hypothesis name from the rendered sentence. Every line of the document that names both must hold the
  rendered sentence verbatim, after any markdown prefix such as "- " or "> ", and at least one such line must
  exist; otherwise it raises AssertionError naming the offending line. A stale copy of the same result on a line
  of its own therefore fails wherever it stands in the document, as does any other wording of it on one line
  with both. The sentence stays one line.
  - As built: `render` refuses a sentence that would span lines (a hypothesis name, family, or file stem holding
    any break `str.splitlines` makes), and `assert_quoted` raises ValueError for one that does, and for a
    sentence `render` did not return (an empty or exploratory one).
  - As built, what "names" means: a line names the id or the name where it stands as a word, with no word
    character running on from either end, so "fast" is not named in "faster", nor `layout@X` in `old_layout@X`.
    Inside the body of any rendered sentence on the line, from its verdict to its onus version, only the prereg
    id that body names counts, since its other words are the template's, its family's, or its warnings'; and the
    name does not count inside the prereg id. So a document quoting each sentence once passes when a hypothesis
    is named "warnings" or "power", when "fast" stands beside "faster", when the file stem is a hypothesis's
    name, and when `layout@X` stands beside `old_layout@X`. A document quoting both a read and the re-read that
    superseded it fails for each.
  - Known limits, from reading line by line: a line quoting another hypothesis of the same record whose name
    holds this one's as a word ("faster" in "much faster") fails too. A stale copy passes when it shares a line
    with the exact sentence, when it is hard-wrapped so that no one line names both, and when it is written
    inside the body of another sentence.
- **E2, MDE precision: the gap to 4 significant digits (F6).** The MDE prints as p0 plus the gap ("success
  probability 0.5 + 0.4635"; "0.999 - 0.001844" below the null), with p0 exact and the gap, the MDE's distance
  from p0, to 4 significant digits, rounded away from the null, so the printed effect still reaches 80% power.
  It replaces the 4 fixed decimals, which at n = 4000 printed 1.0000 at p0 = 999/1000 (the MDE is 0.99994) and
  0.0005 at p0 = 1/1000000 (the MDE is 0.000402). It pins sentences once released, as D2's constant does.
- **E3, early read: no verdict and no MDE.** An early read's sentence carries neither a verdict nor the MDE
  clause, so nothing hints at the result; the MDE appears only on a read that is not early and not met. The
  sentence still carries p and the family's adjusted p beside α, from which a reader can work the verdict out.
- **E4, the seal after an override: kept as built.** After a recorded override, every later read that differs
  from the first read, a re-read of the corrected data included, needs `supersedes=` (the first read) and
  `reason=` again, and render keeps showing "re-read on different data; first read <hash>" on each. So does a
  read of the first data again, which differs from the re-read. No code change; a test and a mutant now pin the
  corrected data read again.
- **E5, `reads_path` equality: kept as built (F7's case half).** render compares the caller's `reads_path`
  with the receipt's once both are resolved (D1), and `resolve()` keeps a name's spelling, so on a
  case-insensitive disk "Reads.jsonl" is refused for "reads.jsonl", as is a hard link, which a file-identity
  check would have accepted. No code change; a test and a mutant now pin both refusals.
- **E6, Windows: `fcntl` is imported lazily.** `record_read` imports fcntl itself, so `onus.prereg` and
  `onus.report` import on every platform. On a platform without fcntl, `record_read` raises NotImplementedError,
  which names the missing file lock (`fcntl.flock`), before it opens the reads file. No Windows support is
  claimed beyond that, and no Windows run tests it.
- **Known limits, recorded with these decisions:**
  - A refused read can leave an empty reads file behind when it created the file: `record_read` opens the file
    to lock it before the seal decides, so a `supersedes=` with no earlier read to supersede leaves it there.
  - `read/2` labels hold only "met" and "not met", so the post hoc label (L1 step 4) needs a `read/3` or a
    widening of `read/2` then.
  - E2's gap has no cap at the boundary, so when the MDE lies within one rounding step of 1 (or of 0, below the
    null), the printed effect passes it: at p0 = 0.33330001 and n = 2400, with an alpha below p0 to the 2400th
    power, the MDE is 0.99990703 and the sentence prints "0.33330001 + 0.6667", above 1. Only an absurdly small
    alpha reaches it. There no gap of four significant digits both reaches the power and keeps the effect within
    the boundary; which gives way is open for the maintainer.

## The library

### Shape

- **Layout:** a flat package `onus/` at the repository root, with `py.typed`. A `src/` layout under
  `pip install -e` makes every mutant survive under mutt_check, so the package stays flat.
- **Subpackages, named by intent:** `onus.stats`, `onus.prereg`, `onus.report`, `onus.baseline` (tier 1),
  `onus.signoff` (tier 2), `onus.scrub`, and `onus.invariants` (the Hypothesis part; not `property`, which
  would shadow the builtin). `prereg` will import `signoff` (L1 step 4), since amendments are bound by
  sign-offs. Built so far: `stats`, `prereg`, and `report`.
- **Python:** `requires-python >=3.11`, with CI covering 3.11 to 3.14. Locally, `.python-version` pins the
  exact patch and the floor check (it compiles the package) runs on an exact 3.11 patch, both from pyenv and
  handed to uv by path; in CI each matrix job supplies its own interpreter.
- **Dependencies:** `dependencies = []`. The only extra is `invariants = ["hypothesis>=6.168.1,<7"]`, and only
  `onus.invariants` imports it. (Hypothesis 6.168.1 needs Python 3.10 or later.)
- **Tooling:** black and ruff at 120 columns with the D, ANN, B, UP, and I rules and Google docstrings; strict
  mypy; coverage with `branch = true` and `fail_under = 95`. `tools/` is inside lint, type, and coverage scope.
- **Packaging and release** follow mutt_check: setuptools 77 or later, a dynamic `__version__`, SPDX MIT, a
  tag-triggered release workflow, and rulesets that make `main` pull-request-only and `v*` tags permanent.
- **Gate:** `make check` is the whole gate (see `AGENTS.md`). The opt-in targets `reference` and `sims` (and `calibrate`,
  from v0.2) are never part of it.
- **Test fixtures are synthetic only.** No client names, machine paths, or real addresses.

### stats: stdlib only, exact rationals

- Exact tails are computed in `fractions.Fraction`, and results are frozen dataclasses carrying `p_exact`,
  `p_value`, counts, ties, missing, method, and warnings.
- `decide(result, alpha="0.05")` rejects iff `p_exact <= Fraction(alpha)`.
- **`alternative` and `method` are keyword-only, with no default.**
- **v0.1:**
  - `binomial`: `binom_tail`; `binomial_test` (two-sided only at p = 1/2); `sign_test(wins, losses, *, ties,
    alternative, method)`; `paired_sign_test(first, second, *, alternative, missing, method)`, where `missing` is `"refuse"` or `"drop"`;
    `mcnemar_exact`.
  - `intervals`: `wilson(k, n, *, confidence=None, z=None)` (0.95 unless `z` is given) and `clopper_pearson`, both raising
    `EmptySampleError` at n = 0.
  - `multiplicity`: `holm`, `benjamini_hochberg`, and `Family`, which refuses undeclared members and incomplete
    adjustment.
  - `power` (exact DP): `sign_test_power`, `sign_test_mde`, `binomial_power`, `binomial_mde`, and
    `sequential_size`.
- **v0.2 (step L2):**
  - `ranks.mann_whitney(..., method="exact"|"normal")`: exact is the tie-conditional permutation null; normal
    has tie and continuity corrections.
  - `cluster.cluster_bootstrap`, reporting valid draws, raising `InsufficientDraws` below b/2, and warning under
    20 clusters; and `cluster.cluster_sign_flip_test`.
  - `binomial.rate_ratio_test`.
- **Freeze rule:** a released function's numeric output never changes; a fix is a new `method=` value.
  Known-wrong legacy behaviour is never reproduced in the library.
- **Out of scope:** a Bayesian layer, automatic test choice, post hoc power, sequential-until-significant
  helpers, numpy or scipy at runtime, and a pytest plugin.

### prereg and report

- **`prereg_id(path)`** returns `"<stem>@<first 12 hex digits of the file's sha256>"`. Any edit gives a record
  a new id.
- **Records** use `"prereg/1"` JSON and reject unknown keys. Fields: experiment, registered, hypotheses
  `[{name, test, alternative, method, alpha, family}]`, families, unit, cluster_key, order_key, horizon
  (`{kind: "count", n}` or `{kind: "days", days, start}`), looks, `bound_artifacts {path: sha256}`, and
  provenance. `load` also requires `p0` on a `binomial_test`, where two-sided is allowed only at p0 = 1/2, and
  refuses it on a `sign_test`; takes `families` as `{name: {correction}}`; takes `alpha` and `p0` as exact
  numbers written as strings, such as `"0.05"`; and requires `bound_artifacts` paths that stay inside the
  record's folder. These are as built, not among the five defaults Amendment 1 ratifies.
- **Amendments** are separate `<stem>.amend-YYYY-MM-DD.json` files, each bound by a tier-2 sign-off (L1 step 4).
- **Evaluation and read-recording are split**, because a name must not hide a write:
  - `evaluate(rule, data, *, as_of=None)` is pure. It refuses before the horizon. A count horizon uses exactly
    the first N units in `order_key` order; a days horizon needs `as_of` past its window and uses the units
    dated inside it.
  - `record_read(rule, evaluation, *, reads_path, supersedes=None, reason=None)` appends a `read/2` line to a
    reads file and returns a `ReadReceipt`. The read time is the clock's (D8), and the seal and its override
    are D6's.
  - `report.render` requires a receipt, so displaying a verdict records it. Its signature and checks are
    Amendment 2's D1, D5, and D6; exploratory results use `render_exploratory` (D4).
- **Post hoc:** an amendment signed after the first read of a hypothesis it touches labels that hypothesis
  post hoc. The labels are met / not met / pending today, and render shows "read early" in place of a verdict
  (D5); post hoc arrives with L1 step 4, and needs a `read/3` or a widened `read/2` (Amendment 3).
- **render's sentence** is one line, and render refuses one that would span lines (Amendment 3, E1). It carries
  n, discordant pairs and ties, sidedness, the family correction, **the MDE whenever a read that is not early is
  not met** (D2, D3; Amendment 3, E2 and E3), the prereg id, a data hash, and the library version. It reads no
  wall clock.
- **`report.assert_quoted(doc, sentence)`** fails a test unless every line of the document that names the
  sentence's hypothesis and prereg id holds the rendered sentence verbatim, and one line does (Amendment 3, E1),
  so a document quoting a figure that is not the rendered sentence, or a stale copy on a line of its own, fails.

### baseline, signoff, and scrub (approval testing)

- **`scrub`:** `chain`, `iso_dates`, `iso_timestamps`, `paths(mapping)` (including `/private/var` and `/var`),
  `uuids` and `hex_ids`, `pattern`, and `redactor(fn)`. No PII rules ship, and numeric scrubbers on stats output
  are forbidden.
- **Tier 1 (`baseline`):**
  - Tests use `ApprovedMixin.assertApproved(received, *, label="", ext=".md")`. Approved files are
    `tests/approved/<module>.<Class>.<method>[.<label>].approved<ext>`, committed.
  - On a mismatch the test fails with a diff and writes the received file under
    `$TMPDIR/onus-received/<repo-sha8>/`. A missing approved file fails; it never skips.
  - **Recording** happens only under `make approve`, which sets `ONUS_APPROVE_ROOT` to the invoking checkout's
    top level. The helper refuses unless the approved path resolves under that root and the root is a git work
    tree, so a mutation sandbox refuses.
  - `forbid=` patterns apply while recording. Approved files carry the producer, `inputs_sha256`, and the
    scrubbers, never a timestamp. `ApprovedProducersAreReal` refuses test-local or mock producers.
- **Tier 2 (`signoff`):**
  - **Ledger:** the adopter passes the ledger path. Lines are `{"schema": "signoff/1", artifact, sha256, bytes,
    bound, supersedes, reviewed_by, at, tool, prev}`, hash-chained. Blobs are content-addressed, mode 0444.
  - **Ids** are exact, matching `^[a-z0-9][a-z0-9._-]*:[A-Za-z0-9._/-]+$`; no globs.
  - `check_signoff` returns SIGNED, UNSIGNED, CHANGED (with a diff), REVOKED, or CORRUPT, and **fails closed** on
    a malformed line or a broken chain.
  - **`record`** refuses when any agent-session environment variable is set or `/dev/tty` cannot be opened,
    shows the diff, reads a typed 8-hex prefix from `/dev/tty`, then appends under flock and fsync.
  - **These are tripwires; the control is step H.**

### invariants (the `invariants` extra)

- **Profiles:** `use_profile()` defaults to "gate" (`derandomize=True`, `database=None`, `deadline=None`,
  `max_examples` 200 in the library and 50 in adopters; health-check failures fail). "explore" loads only under
  `ONUS_HYPOTHESIS_PROFILE=explore`, with its database under `~/.local/state/onus/explore/<repo>`.
- **Storage:** `HYPOTHESIS_STORAGE_DIRECTORY` points outside the worktree, and `.hypothesis/` is gitignored
  anyway.
- **Strategies** are independent grammars only (`emails`, `in_context`, `markdown_text`,
  `normalization_variants`). Adopters own the oracles and the bounds.
- **`python -m onus.invariants examples <log>`** prints `@example` lines for a person to paste. It never edits
  source.

### How we know the library is right

1. **Brute-force oracles** in `make check`: all 2^n outcomes for n ≤ 14 (built); all labelings with ties for
   n + m ≤ 12 and all 2^C sign flips arrive with the v0.2 tests they check. Two coverage tests: exact size ≤ α for n ≤ 200 and α in
   {0.01, 0.05, 0.10}; and Clopper-Pearson coverage at least nominal on a 1001-point grid.
2. **The reference fixture:** `make reference` recomputes answers with pinned scipy and statsmodels versions
   and commits them with the script's sha256; a drift test guards it.
3. **Hypothesis properties:** tail complement; two-sided = min(1, 2 × the smaller tail); sign-test symmetry and
   monotonicity; U sums, and U(x, y) + U(y, x) = nm; interval containment and reflection;
   Bonferroni ⊆ Holm ⊆ BH; power monotone in the effect and in α (never in n); and `sequential_size` with one
   look equals the fixed size.
4. **Simulation cross-check:** `tools/sims/ht_sims.py`, with its output committed; a test asserts that the exact
   DP matches within 3 standard errors.
5. **Mutants** in `mutt_check.toml`, each with the test that kills it:
   - **Tails and tests:** tail off by one; sidedness flipped; two-sided not doubled; cap removed; `<=` to `<`
     (killed at α = 1/16 with 4 to 0); continuity correction dropped; tie variance dropped.
   - **Intervals:** wilson z hardcoded; n = 0 returns a zero interval.
   - **Families and power:** Holm running maximum removed; incomplete family allowed; undeclared member
     accepted; MDE uses the observed effect.
   - **Missing data and defaults:** `missing="refuse"` silently drops; `alternative` gains a default; `method`
     gains a default.
   - **Bootstrap:** invalid draws dropped silently; percentile off by one.
   - **Pre-registration:** horizon not enforced; `evaluate` uses more than the first N or ignores `order_key`;
     unknown prereg key accepted; amendment after a read accepted; `render` without a receipt.
   - **Tier 1:** approved file overwritten automatically; missing approved file created or skipped; received
     file written into the worktree; `make approve` records outside the root; `forbid` ignored while recording.
   - **Tier 2:** record allowed under a session; tty replaced by stdin; glob id accepted; corrupt line skipped;
     broken `prev` chain accepted.

   `mutt_check.noop.toml` must **survive**. Mutated files are restored from a pre-mutation snapshot, never with
   `git checkout <path>`.

## Order of work

**Rules for every step:**

- A branch per session, then a pull request; files staged by path. `make check`'s raw output, with its test
  count, goes in the pull request body.
- **The maintainer's explicit word, per item,** is needed to push, open a pull request, merge, or tag.
- **Before each push,** scan the tree, the commit messages, and the pull request body for names of people,
  companies, customers, and private repositories, machine paths, and email addresses, with a positive control.
- Deliberate corner-cuts are marked in place: `# ⚠ SHORTCUT (date) — what — ceiling — exit`.
- Every session ends with a note in `docs/handoffs/`.

**L1. Library v0.1.0:**

1. The scaffold, green on an empty package (PR #1, merged).
2. `binomial`, `intervals`, `multiplicity`, and `power`, with the oracles, the reference fixture, and the sims
   cross-check (PR #3, merged). **Open, no owner yet:** the plan also named parity scripts here, comparing
   the library with the adopters' earlier hand-written tests; they were not built, and no later step owns them.
3. `prereg` (PR #5, merged), then `report` to Amendments 2 and 3 (**next**), as its own pull request.
4. `baseline`, `signoff`, and `scrub`, plus the prereg work PR #5 deferred: amendment files and their sign-off
   binding, the post hoc label in `prereg` and `render` (with the `read/3` or widened `read/2` it needs,
   Amendment 3), the "amendment after a read accepted" mutant, and Amendment 1's open count-horizon decision.
5. `invariants`.
6. The v0.1 mutants: each part brings its own, and the no-op spec (`mutt_check.noop.toml`) is already enforced,
   so this step checks that the whole list below is present and caught.

Then the leak scan, and a push, pull request, merge, and `v0.1.0` tag, each on the maintainer's word.

**Verify:** every mutant caught, the no-op survives, `make reference` reproduces the fixture byte for byte, and
`git status --porcelain` is empty after two runs.

**H. Tier-2 control (right after L1; proposed, applied by the maintainer).** The library's `record` checks
are tripwires, not a control. H is a control outside the library that keeps agent sessions from making a
sign-off, with test cases for what it must and must not block, and a log of what it blocks. The maintainer
applies it before the first tier-2 sign-off is relied on.

**L2. Library v0.2.0 (after the first adopter integrates v0.1):** `ranks`, `cluster`, and `rate_ratio_test`,
with their oracles and mutants, and `make calibrate`.

## Maintainer-only items

- Every push, pull request, merge, and tag.
- Installing the pinned interpreter patches.
- Each tier-2 `signoff record`, from their own terminal.
- Applying step H before the first tier-2 sign-off is relied on.
- Declaring an adopter's confirmatory families.

## Defaults chosen here (vetoable)

- **Floor and arithmetic:** floor 3.11; exact rationals; reject iff p ≤ α.
- **Test definitions:** two-sided binomial only at p = 1/2; n = 0 raises.
- **Structure:** evaluate and record_read are split, and render requires a receipt; the v0.1 / v0.2 split.
- **Operations:** adopter `max_examples = 50`, pending a timing measurement in an adopter; received files in
  `$TMPDIR`.

## Risks

- **A tier-2 ledger is only as durable as its adopter keeps it**; the library keeps no copy, and until H lands
  only the tripwires stand between an agent session and a ledger.
- **Bit-identical bootstrap intervals** depend on CPython's `random.choice` stream. An RNG canary must fail
  loudly on drift.
- **Exact DPs** need a measured time budget.
- **MDE lines will show most comparisons are underpowered.** The amendment ledger makes any after-the-fact
  loosening visible.

## Verification (end to end)

1. **Library:** every mutant caught; the no-op survives; the reference fixture reproduces byte for byte; the
   worktree is clean after two runs; the leak scan is clean before each push.
2. **Tier 2:** from an agent session, `signoff record` refuses, and once H is applied, H blocks it too. From
   the maintainer's terminal, the record, status, and diff round trip works. A hand-corrupted line and a broken `prev` chain both return CORRUPT.
