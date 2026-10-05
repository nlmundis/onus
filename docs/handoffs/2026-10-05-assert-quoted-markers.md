---
date: 2026-10-05
scope: "onus.report.assert_quoted rebuilt on explicit quote markers (Amendment 5, E14), the part Amendment 4 split out of L1 step 3"
state: in-progress
prs: []
next: one targeted review of this branch; then the leak scan, the push, and the pull request, each on the maintainer's word
---

# Handoff: assert_quoted on explicit quote markers (2026-10-05)

This note follows `2026-10-05-l1-report-split.md`, whose pull request (#8) merged as `821b336`, and takes up its
last next action.

## State

- **Branch `assert-quoted-ce037ab9`**, from main `821b336`. Not pushed, and there is no pull request.
- **`onus.report.assert_quoted(doc, sentences)`** is back, rebuilt: `onus/report/_quote.py`, `QuoteTest` in
  `tests/test_report.py`, and fourteen mutants in `mutt_check.toml`. It shares no code with the function
  Amendment 4 removed.
- **`docs/plan.md` has Amendment 5** (E14), and its library section and the README describe the new function.
- **Gate:** the raw result of `make -f Makefile check` on the head commit goes in the pull request.

## Done this session

- **The maintainer's three choices.** The marker is a bare HTML comment pair, `<!-- onus:quote -->` and
  `<!-- /onus:quote -->`, with no record id or hypothesis name in it; a span may differ from its sentence in
  whitespace only; and the function is built now, in its own pull request.
- **The rule.** Every marked span must hold one of the sentences passed in, and every sentence must stand in at
  least one span. Nothing is parsed, so a stale copy inside markers fails because it is none of the sentences.
- **Exact markers.** "onus:quote" may stand in a document only inside one of the two markers. This closes the
  gap an exact-match marker would otherwise leave: a marker mistyped marks nothing, and its quote would go
  unchecked.
- **Each mutant was run by hand** against `QuoteTest` in a scratch copy, to read why its test fails, since a
  mutant must die for the reason it names. Three tests were strengthened so that the stray marker in each case
  would let a stale copy through beside a good quote, where before the mutant died on a different message.

## Open

- **This branch is unreviewed.**
- **Only marked text is checked.** A copy of a result outside any markers is not found. Nothing in the library
  finds unmarked copies, by design: the removed function tried to, and guessed.
- **A document cannot show the markers as an example.** Prose or a code block holding "onus:quote" outside a
  marker fails the check. A document about the convention itself must be checked some other way, or not at all.
- **One guard has no mutant.** `_stands` refuses a marker that would start before the document does. Without the
  guard the result is the same, because no marker fits in the few characters a negative start leaves, so no test
  can tell the two apart; the guard stays for the reader.
- Carried, unchanged: the count-horizon registration check, owned by the session that starts L1 step 4, and the
  parity scripts, which have no owner.

## Next actions

1. One targeted review of this branch, and fix what it confirms.
2. Run the leak scan over the tree, the commit messages, the commit metadata, and the pull request body, with a
   positive control; push and open the pull request on the maintainer's word.
3. Then L1 step 4: `baseline`, `signoff`, and `scrub`, with the prereg work PR #5 deferred.
