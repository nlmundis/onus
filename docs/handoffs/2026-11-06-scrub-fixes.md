---
date: 2026-11-06
scope: "onus.scrub: the defects left open by the fix-closure review of #10 to #12"
state: in-progress
prs: [15, 16, 17, 18, 19, 20, 21, 22]
next: the maintainer merges #15 to #22 in the order under Next actions, then the rest of the handoff's Open list
---

# Handoff: scrub defects (2026-11-06)

This note follows `2026-11-06-l1-amendments.md`, and covers its `scrub` items only.

## State

- **All eight pull requests are open and unmerged.** Each had a green `make check` on its head when it was pushed;
  the raw summary is in its body.
- **Two lines are stacked.** #17 sits on #15, because they change adjacent lines. #19, #20, #21, and #22 stack in
  that order, because all four change the same regex lines and one docstring paragraph. The repository does not
  delete a branch on merge, so GitHub does not retarget a stacked pull request by itself.
- **The combined tree:** every branch merged in a scratch clone gave one conflict, a single bullet of `docs/plan.md`
  between #17 and #19. The result has 434 mutants, each anchor found exactly once.

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
- **`chain` refuses one scrubber listed twice,** though adjacent repeats are harmless. This is open to veto.
- **The final timestamp rule had no agent review.** Two closure reviews each found majors in the fix before it. The
  rule that replaced them was checked by the last reviewer's differential fuzz instead: 13 new order disagreements in
  300,000 strings on one seed, all the case E16 discloses.

## Next actions

1. Merge #15, then set #17's base to `main` and merge it.
2. Merge #16 and #18 in either order.
3. Merge #19, and set each next pull request's base to `main` in turn: #20, #21, #22.
4. #17 and #19 conflict on one bullet of `docs/plan.md`, so whichever merges second needs main merged in first. Keep
   the new bullet from each side, and let the "Two patterns" line go.
5. After any other merge, read `make mutants` for stale anchors, not only the count.

## Lessons

- **A timestamp scrubber must not read what follows it to decide.** An earlier scrubber may have replaced that text,
  so each lookahead split the two chain orders. Only a differential fuzz across the orders showed this.
- **A fix to a fix needs its own review.** Each closure review here found majors in the commit before it.
