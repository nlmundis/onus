---
date: 2026-11-06
scope: "the signoff defects left open by the review of #10 to #12: G03, G11, the check diff, and M06 to M09"
state: in-progress
prs: [25, 26, 27, 28, 29, 30, 31]
next: the maintainer decides the three questions under "Open", then merges #25 to #31, re-gating each branch that a merge conflicts with
---

# Handoff: signoff fixes (2026-11-06)

This note follows `2026-11-06-l1-amendments.md`.

## State

- **Seven pull requests are open, one per defect, each off `e07f8c8`.** None is merged; merging is the maintainer's.
- **Each head had `make check` exit 0 before it was pushed,** with its raw summary in its body, at 100% coverage with
  every mutant caught and the no-op surviving.

| PR | Defect | Head | Tests | Mutants |
|---|---|---|---|---|
| #25 | M08, a pickled `CorruptLedgerError` | `2d395d5` | 451 | 412 |
| #26 | G11, tripwires stated as a guarantee | `0a8fabf` | 451 | 413 |
| #27 | M06, a stray kept file | `8a3b743` | 454 | 417 |
| #28 | G03, `check_signoff`'s `OSError` and a folder ledger | `471e5d0` | 459 | 418 |
| #29 | M07, the kept copy not flushed | `362a811` | 455 | 417 |
| #30 | M09, a bound file hidden behind a content change | `80e22a8` | 455 | 418 |
| #31 | `check` printing control characters | `6786236` | 459 | 421 |

- **The branches conflict in small places when merged together:** #31 with #28, #29, and #30; #30 with #28; #26 with
  #25. `git merge-tree` found no other pair. Each later merge needs main merged in and its gate run again, and any
  merge can also touch the scrub and baseline work in `mutt_check.toml` and `docs/plan.md`.

## Done this session

- **Every defect was reproduced first.** Each first fix's tests were watched failing; tests added in the rework were
  checked through their mutants, run by the gate. Each disclosure is under E21.
- **The reviews changed the fixes.** One targeted review ran on each commit. Those found real defects in five of the
  seven, which were fixed; one closure pass followed, and its findings were fixed too. Those last fixes were gated
  but not reviewed again.
- **Three changes reach beyond the finding as written, as built and open to veto:**
  - `prereg.load` turns the new `OSError` into a `PreregError`, since a folder ledger would otherwise leave `load` as
    an exception it does not list.
  - `OSError` is listed, not wrapped in `SignoffError`, because `load` turns any `SignoffError` into advice to rename
    the record.
  - `check_signoff` makes a bound file it cannot read part of the detail when the content has already decided
    CHANGED, rather than raising, so the base's CHANGED stands.

## Open

### For the maintainer to decide

1. **`F_FULLFSYNC` on macOS.** `fsync` there stops at the drive's cache and does not order writes, so the flushes in
   #29 do not order a copy and its line on macOS. E21 discloses it. Using `F_FULLFSYNC` is a small change, and it
   needs a fallback where a file system refuses it.
2. **`revoke` over a bad kept copy.** A kept copy that does not match leaves CORRUPT, but `revoke` never reads it, so
   the revocation is written, the artifact reads REVOKED, and a later `record` of other content reads SIGNED. The bad
   copy is passed over, against `_append`'s "nothing is added". This predates these pull requests; no fix is written.
3. **`record` of already-signed content over a bad kept copy.** It says "already signed", where `check` says CORRUPT,
   because that test comes before the copy is read. This also predates them; no fix is written.

### Known and left

- A stray written under the hash while the prompt waits, by a process ignoring the lock, still gets the old message.

### Carried

- The `onus/baseline/_approved.py` wording on `make approve`, from the review's doc pass, is the baseline work's.
- The parity scripts still have no owner, and step H is still unbuilt.

## Next actions

1. The three decisions above.
2. Merge #25 to #31, in any order, re-gating after each conflict.
3. L1 step 5, `invariants`.
