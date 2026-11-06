---
date: 2026-11-06
scope: "L1 step 4, last slice: prereg amendments, the post hoc label, the count-horizon disclosure; and a fix-closure review of #10 to #12"
state: done
prs: [13]
next: fix the defects listed under "Open from the review of #10 to #12", one pull request per defect, then build L1 step 5, `invariants`
---

# Handoff: prereg amendments (2026-11-06)

This note follows `2026-10-08-l1-signoff.md`.

## State

- **Pull request #13 is merged as `d32efc7`.** L1 step 4 is complete: `scrub`, `baseline`, `signoff`, and the prereg
  work. The design is plan Amendment 7, E22 to E26.
- **At the merged head:** `make check` exit 0, 450 tests, 100% coverage, 411 of 411 mutants caught, the no-op
  surviving; CI green on all four Python versions.
- **New in `onus.prereg`:** `Amendment`, `load(path, *, ledger=None)`, `read/3` lines. `onus.report.render` carries
  the post hoc clause and the count-horizon clause. Tests are in `tests/test_amend.py`.

## Done this session

- **The maintainer's answers:** `forbid=` on every run stays (E26); an amendment is a whole record (E22); what it
  touches is computed from the two records (E23); the read line moves to `read/3` (E25). E24 writes down the
  count-horizon choice of 2026-10-08.
- **One change from the review, as built and open to veto:** post hoc is decided by the amendments the experiment's
  first read lists, and no clock decides it. The first design compared sign-off times, and the review showed three
  ways that gave the wrong label: a backdated `signed_at` on the rule, a revocation and re-signing, and an amendment
  signed before a read but placed beside the record after it.
- **Every commit was reviewed:** one targeted review of the slice, then one agent for each of the three fix commits
  and one for the CI fix. Findings were fixed or written down as known limits under E26, except two left
  deliberately: a wording nit in Amendment 7 (the non-ASCII limit applies to the amendment's path from the
  ledger's folder, not the whole path), and the fact that the anchor check in `tests/test_repo.py` is a textual
  tripwire.

## Open

### From the review of #10 to #12

A fix-closure review of those three pull requests' fix commits left 6 of the 10-08 round's 24 majors partly closed
and confirmed 4 new majors; an agent then reproduced or traced all 11 minors the review had cut for budget. None is
fixed yet.

- **`scrub`:**
  - Two `hex_ids` in one chain share token numbers.
  - A timestamp whose fraction runs on into a letter is cut back and still replaced.
  - The comma fraction takes in a number that follows a timestamp in a CSV row.
  - A numbered token fools the whole-path check in `paths`.
  - Minors:
    - A colon-less offset takes in a following hyphen-joined year.
    - `:60` is accepted at any minute, undocumented.
    - `pattern` raises `TypeError` on an unhashable name.
    - A path after a doubled slash, or in a `file:///` URL, is replaced.
    - The `hex_ids` docstring and E16 leave out a trailing `e` and an upper-case `E`.
- **`baseline`:**
  - `unreal` checks only the two ends of a `__wrapped__` chain.
  - The received file is written to a predictable path under a shared temporary folder and follows a symlink.
  - `_tests_of` refuses every producer when tests sit inside the code package.
- **`signoff`:**
  - `check_signoff` raises an `OSError` its docstring does not list.
  - A ledger path that is a folder answers UNSIGNED where `record` refuses.
  - The README and two docstrings still state the tripwires as a guarantee.
  - `check` prints the diff with control characters unescaped.
  - Minors:
    - A stray kept file gives a misleading remedy.
    - The `.partial` copy is not fsynced.
    - A pickled `CorruptLedgerError` repeats its remedy.
    - A bound-file change is hidden behind a content change.

- **Docs, from one pass nobody verified:** `onus/baseline/_approved.py` still speaks of `make approve`, which onus does
  not have. The review's other doc finding, the plan's "while recording" wording, is fixed by #13.

Reproduce each before fixing it, and decide fix or disclose with the maintainer where it is a judgment call.

### Lessons

- **`mutt_check`'s control refuses any skipped test,** so a test that skips on Linux turns CI red while macOS is
  green. Write the file under the other spelling instead of skipping on a case-sensitive file system.
- **A green first run of a new test file proves little.** A helper that dropped every key whose value was None made
  one test pass on every input; only running the mutant showed it.

### Carried

- The parity scripts still have no owner (L1 step 2).
- Step H is still unbuilt: the sign-off checks are tripwires, and the maintainer applies H before a tier-2 sign-off is
  relied on.

## Next actions

1. The fixes above, one pull request per defect.
2. L1 step 5, `invariants`.
3. L1 step 6, the check that the whole mutant list is present and caught.
