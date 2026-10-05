---
date: 2026-10-05
scope: "L1 step 3, part 2: the maintainer's decisions of 2026-10-05 on onus.report (Amendment 4): assert_quoted leaves this pull request, an early re-read on different data names the first read, and, after one review of that build, a re-read says what it differed in"
state: in-progress
prs: []
next: one more targeted review, of the second review's fixes; if it closes clean, run the leak scan, push, and open the pull request, each on the maintainer's word
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
- **An early re-read on different data names the first read.** Its sentence carries "re-read on different
  data; first read <12 hex>" between "read early (...)" and the provenance. A first early read's sentence is
  unchanged, and so is that of the same data read early again under an edited record.
- **A re-read says what it differed in.** One that is not early, of the same data after a read under a
  different record, carries "re-read after a read under a different record; first read <12 hex>".
- **`docs/plan.md` has Amendment 4** (E11 to E13), and marks E1 and E9 withdrawn where they stand.
- **Gate:** the raw result of `make -f Makefile check` on each commit goes in the pull request; this note is
  part of the commit it would describe.

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
- **One targeted review of that build** (commit `af20ccc`): three findings, all confirmed, none refuted. The
  major one: the seal requires `supersedes` when labels differ as well as when data does, so E12's clause on an
  early read of the same data under an edited record told a reader holding both sentences that a verdict had
  changed. The two minor ones: "on different data" was printed where the data hash was the same, and render's
  docstring put the clause after the warnings.
- **The fix, on the maintainer's two choices.** `re_read_kind` sorts a re-read by the reads before it that the
  seal held it to: "data" when any has another data hash, else "record". An early read carries the clause only
  for "data" (E12 as rebuilt); a read that is not early words the two apart (E13). Two new tests, an assertion
  added to an existing one, and five mutants pin it: the early read under an edited record, the wording, the
  first data read again after a re-read, another experiment's reads in the same file, and a later read leaving
  an earlier sentence as it was.
- **A second targeted review, of that fix** (commit `47265cf`): it found the three earlier findings fixed and
  the early read's rule unbroken, and confirmed three new ones, each rated minor once checked. "Re-read under a
  different record" was false of a record edited, read, and put back, since the third read is of the first
  read's own record; the maintainer chose "re-read after a read under a different record", which is true of
  every such read. Neither half of the rule for which earlier reads count was pinned in render's copy of it;
  the seal and render now share `related_reads`, which the seal's two mutants pin. Render's docstring named only
  reads of the experiment, and now names those of a record with the same file stem too.
- **A test now pins that `render` is idempotent:** asked again for a recorded read it gives the same sentence,
  and it writes nothing. `record_read` is not, by D5: every read is recorded, so the same data read again
  appends a second line, needs no `supersedes`, and is refused one ("nothing to supersede").

## Open

- **The second review's fixes are unreviewed.** The maintainer asked for one more targeted round on them.
- **The marker's form is undecided.** E11 leaves it to the pull request that rebuilds `assert_quoted`: what
  marks a quote in a document, whether a marked quote may be wrapped, and what an unmarked copy of a result
  means.
- **Nothing pins a released sentence yet.** `MDE_POWER` and the sentence's wording are frozen once released
  because documents quote them; until `assert_quoted` returns, no check in this library holds a document to a
  rendered sentence.
- Carried from the earlier note, unchanged: the count-horizon registration check, owned by the session that
  starts L1 step 4, and the parity scripts, which have no owner.

## Next actions

1. Review the second review's fixes, and fix what that confirms.
2. Run the leak scan over the tree, the commit messages, the commit metadata, and the pull request body, with
   a positive control; push and open the pull request on the maintainer's word.
3. Then `assert_quoted` on explicit quote markers, as its own branch from main once this merges: propose the
   marker's form to the maintainer first.
