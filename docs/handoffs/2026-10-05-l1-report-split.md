---
date: 2026-10-05
scope: "L1 step 3, part 2: the maintainer's two decisions of 2026-10-05 on onus.report (Amendment 4): assert_quoted leaves this pull request, and an early re-read names the first read"
state: in-progress
prs: []
next: one targeted review of this session's delta; if it closes clean, run the leak scan, push, and open the pull request, each on the maintainer's word
---

# Handoff: onus.report without assert_quoted (2026-10-05)

This note follows `2026-09-29-l1-report.md`, which records the build and its three reviews, and corrects its
"Open" and "Next actions": the maintainer has answered both questions it left.

## State

- **Branch `l1-report-ce037ab9`**, forked from `l1-report-baab0134` at `b67569e`, the head the earlier note
  describes. Neither branch is pushed, and there is no pull request.
- **`onus.report` now exports** `render`, `render_exploratory`, `receipt_from_line`, and `MDE_POWER`.
  `assert_quoted` is gone from this branch: `onus/report/_quote.py`, `QuoteTest`, and the 27 mutants that named
  either.
- **An early re-read names the first read.** Its sentence carries "re-read on different data; first read
  <12 hex>" between "read early (...)" and the provenance. A first early read's sentence is unchanged.
- **`docs/plan.md` has Amendment 4** (E11 and E12), and marks E1 and E9 withdrawn where they stand.
- **Gate:** `make -f Makefile check` exit 0 on this change before this note was written, read from the run's own
  exit line: 232 tests, 100% branch coverage, 267 of 267 mutants caught with none stale, and the no-op spec's
  mutant survived, as it must. The run on the commit itself goes in the pull request.

## Done this session

- **E11.** Removed `assert_quoted` with everything that tested it. It produced the worst finding of each of the
  three reviews because it guessed where free text quotes a result; the maintainer chose to rebuild it on
  explicit quote markers, in its own pull request, over a fourth round on the guessing design.
- **E12.** `render` appends the re-read clause to an early read's sentence too. One helper, `_re_read`, now
  gives the clause to both kinds of sentence. `test_an_early_re_read_names_the_first_read` replaces the test
  that held the clause off; the mutant `an_early_re_read_not_disclosed` replaces the one that held the
  opposite, and `a_decided_re_read_not_disclosed` pins the other call, since `a_re_read_not_disclosed` now
  switches the helper off for both.
- The README and the package docstring no longer describe `assert_quoted`.

## Open

- **This delta is unreviewed.** The three review rounds of the earlier note are spent, and they did not see
  it. One targeted review of it comes before the branch is called ready.
- **The marker's form is undecided.** E11 leaves it to the pull request that rebuilds `assert_quoted`: what
  marks a quote in a document, whether a marked quote may be wrapped, and what an unmarked copy of a result
  means.
- **Nothing pins a released sentence yet.** `MDE_POWER` and the sentence's wording are frozen once released
  because documents quote them; until `assert_quoted` returns, no check in this library holds a document to a
  rendered sentence.
- Carried from the earlier note, unchanged: the count-horizon registration check, owned by the session that
  starts L1 step 4, and the parity scripts, which have no owner.

## Next actions

1. Review this delta, and fix what it confirms.
2. Run the leak scan over the tree, the commit messages, the commit metadata, and the pull request body, with
   a positive control; push and open the pull request on the maintainer's word.
3. Then `assert_quoted` on explicit quote markers, as its own branch from main once this merges: propose the
   marker's form to the maintainer first.
