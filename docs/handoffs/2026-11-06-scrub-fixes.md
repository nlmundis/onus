---
date: 2026-11-06
scope: "onus.scrub: the defects left open by the fix-closure review of #10 to #12"
state: done
prs: [15, 16, 17, 18, 19, 20, 21, 22]
next: the baseline and signoff fixes in their own pull requests, then L1 step 5, `invariants`
---

# Handoff: scrub defects (2026-11-06)

This note follows `2026-11-06-l1-amendments.md`, and covers its `scrub` items only.

## State

- **All eight pull requests are merged,** in the order #15, #17, #16, #18, #19, #20, #21, #22, then this note.
- **The ruleset requires a branch to be up to date,** so each was updated from main, gated, and passed CI before it
  merged. The repository does not delete a branch on merge, so GitHub does not retarget a stacked pull request by
  itself; each stacked base was set to `main` by hand.
- **The final tree,** on 3.13, 3.11, and 3.14: `make check` exit 0, 472 tests, 100% coverage, 434 of 434 mutants
  caught, the no-op surviving. That tree holds the eight fixes on the main they started from; the baseline and signoff
  pull requests were open beside it, and their merges clean against it was checked as text only.

## Done this session

- **S02, #17:** `chain` and `assertApproved` refuse two scrubbers that write one numbered name.
- **S04, #19:** a fraction or `Z` that runs on leaves the timestamp whole; seconds or an offset that runs on stays
  behind the token.
- **The comma fraction, #20:** removed, by the maintainer's choice.
- **M01, #21:** an offset's hours stop at 14, by the maintainer's choice.
- **M02, #22:** `:60` at any minute is documented, by the maintainer's choice.
- **The token and `paths` start boundary, M04, and M11, #16:** one root cause. `file:///` stays, by the maintainer's
  choice.
- **M03, #15, and M05 with M10, #18.**

## Open

- **A shipped scrubber can still take a number** in three forms, all in E16's known limits: digits joined on that read
  as an offset (`T12:00-14`), as seconds (`T12:00:42:7`), or as a fraction (`T12:00:00.2026`). The README's "ships no
  scrubber that replaces a number" is not qualified. Whether it should be is the maintainer's call.
- **`chain` refuses a numbered scrubber listed twice.** This is open to veto.
- **The final timestamp rule** had an adversarial review at the coordinator's request. It found no defect in
  the rule, and one major: an hour range depends on the hour, now disclosed. Chain orders still disagree on inputs E16
  lists, and a timestamp joined by a full stop to an id fails at random unless `uuids` runs first.
- **`test_the_odds_the_docstring_gives_are_the_odds`** computes from literals, not from `_NUMBER`, so it would not
  notice the regex changing. The mutants on `_NUMBER` do.

## Next actions

1. After each baseline or signoff merge, read `make mutants` for stale anchors, not only the count.
2. Decide the two open questions above.
3. Build L1 step 5, `invariants`.

## Lessons

- **A stacked pull request conflicts with its own squash** on the next update. A tree gated beforehand gave the exact
  result, and comparing tree hashes proved it.
- **A timestamp scrubber must not read what follows it to decide.** An earlier scrubber may have replaced that text,
  so each lookahead split the two chain orders. Only a differential fuzz across the orders showed this.
- **A fix to a fix needs its own review.** Each closure review here found majors in the commit before it.
