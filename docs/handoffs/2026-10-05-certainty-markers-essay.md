---
date: 2026-10-05
scope: the certainty-markers essay after the maintainer's edits, ready to publish with its drafting note
state: in-progress
prs: [6]
next: push this branch on the maintainer's word, post the gate's raw output to PR #6, then merge on their word
---

# Handoff: certainty-markers essay, revised (2026-10-05)

This note follows `2026-09-29-certainty-markers-essay.md`, which describes PR #6 as first pushed (`00e16c9`),
and corrects its "Open" and "Next actions".

## State

- **PR #6**, branch `certainty-markers-2d27e5f9`. Not merged; the maintainer pushes and merges on their word.
- **Sixteen commits past `00e16c9`:** fifteen to the essay and the README's link to it, then this note. They
  change `docs/certainty-markers.md`, `README.md`, and `docs/handoffs/` only. No file under `onus/`, `tests/`,
  or `tools/` changes, and no pinned file changes.
- **The essay now reads:** the title is "Uncertainty Markers: Labels to Track the Strength of Claims", and the
  README's link carries it. The maintainer rewrote the opening, through the first design decision, by hand,
  and later twelve sentences in three rounds; the rest was redrafted to follow. A drafting note above the
  license line says the essay was drafted with Claude from the maintainer's design and notes, and edited by
  the maintainer.
- **Decided on 2026-10-05:** the essay is published as it stands, with that drafting note. A detector still
  scores most of it as machine-written, the maintainer's own opening excepted; the note says why, and no
  further rewording is planned.
- **Gate:** `make -f Makefile check` must pass on this branch's head before the push, because the README feeds
  the dist check; its raw output goes in PR #6. The result is not recorded here, since this note is part of
  the head it runs on.

## Done this session

- Wrote this note. The essay's text was not changed.

## Open

- **Placement and README wording** remain the session's choices, and vetoable.
- **The branch is one commit behind `main`** (the plan document, `76d4e06`). Its files do not overlap that
  commit's, and the repository squash-merges.

## Next actions

1. Run the gate on the head, scan the diff, the commit messages, and the commit metadata, and push on the
   maintainer's word.
2. Post the gate's raw output to PR #6.
3. Merge PR #6 on the maintainer's word.
