---
date: 2026-09-29
scope: publish the certainty-markers essay as docs/certainty-markers.md, linked from the README
state: in-progress
prs: [6]
next: the maintainer decides on a drafting note or a rewrite, then merges PR #6 on their word
---

# Handoff: certainty-markers essay (2026-09-29)

## State

- **PR #6**, branch `certainty-markers-2d27e5f9`, from main `f7a3c51`. Not merged; the maintainer merges on
  their word.
- **What it adds:** `docs/certainty-markers.md`, an essay, and a "Writing" heading in the README that links it
  by absolute URL. No file under `onus/`, `tests/`, or `tools/` changes, and no pinned file changes.
- **Gate:** `make -f Makefile check` exit 0 on `4c61111`, the commit carrying the essay's final text; the raw
  output is in PR #6. This note is the only later change, and no test reads `docs/handoffs/`.
- **Prior-art search:** run this session, before anything was pushed. No substantially equivalent published
  scheme was found; the closest relatives are in the essay's "Related work" section, each with a URL and how
  it differs, all accessed on 2026-09-29.

## Done this session

- Wrote the essay from a private draft, keeping only the grammar, the design decisions, and the shape of the
  enforcement. It carries no measured figures, no private paths, and no wikilinks, so it can move to another
  site unchanged.
- Every marker example is inline code, not a fenced block, because the scanner the essay describes strips
  inline code spans only; a fenced example would be counted as a real flag wherever the essay is copied into
  a scanned knowledge base.
- One cold review for unsurfaced decisions. Fixed from it: the reminder's tool coverage was overstated; the
  scanner's exclusion of its own report was missing; an empirical claim about calibration went beyond its
  source; the worked example's hedge used the register the cited study found agents discount least; the
  resolution rule and the example disagreed; the memory-store correction route was missing; and the shortcut
  marker was presented as part of the prose grammar rather than as a sibling convention.

## Later the same session

- **License, decided by the maintainer:** the essay ends with a CC BY 4.0 notice in the maintainer's name,
  and the README's License section says the code is MIT and the essay CC BY 4.0.
- **Outbound check:** eight sentences flagged by the structure lint were reworded without changing any
  claim. A forced second-opinion detector run on the final text scored it as fully machine-written, which is
  what it is; nothing was reworded to move that score.
- **Second prior-art pass:** it covered engineering requirements practice, intelligence analysis, legal
  citators, provenance standards, laboratory notebooks, and agent trust metadata. It added three relatives
  to the essay and narrowed the related-work opening. There is still no substantially equivalent scheme.

## Open

- **The detector result.** Whether the essay carries a drafting note, or is rewritten, before it goes out
  under the maintainer's name.
- **Placement and README wording** were chosen by the session for the theme they share with onus; both are
  vetoable.

## Next actions

1. The maintainer decides on the drafting note or a rewrite.
2. Merge PR #6 on the maintainer's word.
