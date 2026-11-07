---
date: 2026-11-06
scope: "the signoff defects left open by the review of #10 to #12: G03, G11, the check diff, and M06 to M09"
state: in-progress
prs: [25, 26, 27, 28, 29, 30, 31, 37, 38, 39]
next: merge #25 to #31, #37, #38, and #39, merging main in and re-gating each branch a merge conflicts with
---

# Handoff: signoff fixes (2026-11-06)

This note follows `2026-11-06-l1-amendments.md`.

## State

- **Ten pull requests are open, one per defect, each off `e07f8c8` except #39, which is stacked on #29.** None is merged; merging is the maintainer's.
- **Each head had `make check` exit 0 before it was pushed,** with its raw summary in its body, at 100% coverage with
  every mutant caught and the no-op surviving.

| PR | Defect | Head | Tests | Mutants |
|---|---|---|---|---|
| #25 | M08, a pickled `CorruptLedgerError` | `2d395d5` | 451 | 412 |
| #26 | G11, tripwires stated as a guarantee | `0a8fabf` | 451 | 413 |
| #27 | M06, a stray kept file | `8a3b743` | 454 | 417 |
| #28 | G03, `check_signoff`'s `OSError` and a folder ledger | `471e5d0` | 459 | 418 |
| #29 | M07, the kept copy not flushed | `88dfb7d` | 462 | 424 |
| #30 | M09, a bound file hidden behind a content change | `80e22a8` | 455 | 418 |
| #31 | `check` printing control characters | `b71f40f` | 459 | 421 |
| #37 | `record` saying already signed over a bad copy | `0874a9f` | 451 | 412 |
| #38 | `revoke` passing over a bad copy | `252d78d` | 452 | 412 |
| #39 | `record_read` flushing short of the disk on macOS | `f5078d3` | 463 | 427 |

- **The branches conflict in small places when merged together:** #31 with #28, #29, and #30; #29 with #28; #30 with
  #28; #26 with #25; #38 with #29. `git merge-tree` found no other pair, and #37 conflicts with none. Each later merge
  needs main merged in and its gate run again, and any merge can also touch the scrub and baseline work in
  `mutt_check.toml` and `docs/plan.md`.

## Done this session

- **Every defect was reproduced first.** Each first fix's tests were watched failing; tests added in the rework were
  checked through their mutants, run by the gate. Each disclosure is under E21.
- **The reviews changed the fixes.** One targeted review ran on each commit, and closure reviews ran on each later
  commit. They found real defects in five of the first seven, each fixed.
- **CI found what the local gate could not.** A mutant in #31 did not compile on Python 3.11, since the local gate runs
  mutants on 3.13 alone. Compiling every mutant on the floor Python would have caught it.
- **Three changes reach beyond the finding as written, as built and open to veto:**
  - `prereg.load` turns the new `OSError` into a `PreregError`, since a folder ledger would otherwise leave `load` as
    an exception it does not list.
  - `OSError` is listed, not wrapped in `SignoffError`, because `load` turns any `SignoffError` into advice to rename
    the record.
  - `check_signoff` makes a bound file it cannot read part of the detail when the content has already decided
    CHANGED, rather than raising, so the base's CHANGED stands.

## Open

### Decided by the coordinator, under the maintainer's word

- **`F_FULLFSYNC` is in #29.** Only a refusal falls back to `fsync`; a failed flush raises. On one APFS Mac, the file
  and the folder descriptor each took `F_FULLFSYNC`. A narrower limit stays in E21. Linux was not run here; CI runs
  the tests there.
- **Both bad-copy bugs are fixed,** as #37 and #38, each independent of the other, and neither stacked.

### Known and left

- A stray written under the hash while the prompt waits, by a process ignoring the lock, still gets the old message.
- `record_read` flushes its line, not its folder, so a reads file just created can lose its name in a power loss.

### Carried

- The `onus/baseline/_approved.py` wording on `make approve`, from the review's doc pass, is the baseline work's.
- The parity scripts still have no owner, and step H is still unbuilt.

## Next actions

1. Merge #25 to #31, #37, and #38, re-gating after each conflict, then retarget #39 to main and merge it.
2. L1 step 5, `invariants`.
