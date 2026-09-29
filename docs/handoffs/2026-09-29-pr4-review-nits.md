---
date: 2026-09-29
scope: two more adversarial reviews of PR #4 and their nits (the nesting test's handler check, the hook's cleanup, the hook command's quoting)
state: done
prs: [4]
next: merge PR #4 on the maintainer's word once CI is green on its head, then start L1 step 3 from main
---

# Handoff: PR #4's fourth and fifth reviews (2026-09-29)

This follows `2026-09-29-nits-and-cloud-hook.md`, written earlier in the same session, which describes
PR #4's work and its first three reviews.

## State

- **PR #4** is open and not merged; the maintainer merges it on their word. Its code head is `8ed8f60`.
- **Gate:** `make -f Makefile check` exit 0 on `8ed8f60`: 161 tests, 100% branch coverage, the dist check
  passed, 171 of 171 mutants caught, and the no-op survived. The raw output is in the PR.
- **Reviews:** the fourth, of the whole PR, found no bug and four nits; three were fixed in `a387dd4`, on the
  maintainer's word. The fifth, of `a387dd4`, found no bug and three nits, fixed in `8ed8f60`.

## Done this session

- **Nesting test:** it now also checks that a refused inner `within` leaves the outer SIGALRM handler in
  place. The new mutant `a_refused_budget_replaces_the_outer_handler` installs a handler before the refusal
  and is caught by that check.
- **Hook cleanup:** the hook traps EXIT, HUP, INT, and TERM, and removes its temp folder (a CPython checkout
  included) and any prefix it was building; only a failed build's log is kept, matched by name, so a temp
  folder with a bracket in its path keeps it too. A signal sent to the hook's shell alone waits for the
  running build step; SIGKILL leaves the folder behind. Checked in a sandbox with a fake git, configure, and
  make: a failed pyenv clone, a failed build, a success, a rerun, TERM to the pid and to the process group,
  and a TMPDIR containing `[`.
- **Hook command:** `.claude/settings.json` quotes `$CLAUDE_PROJECT_DIR`.
- AGENTS.md's paragraph on the hook says which endings the cleanup covers.

## Open

- **Left as it is (fourth review):** an object whose `__class__` claims int or float passes wilson's
  isinstance check and then gets a descriptor TypeError from `int.bit_length` rather than the documented
  message. It is contrived and fails loudly, not wrongly.
- **Carried over:** the Open items of `2026-09-29-nits-and-cloud-hook.md` still stand.

## Next actions

1. Merge PR #4 on the maintainer's word.
2. L1 step 3: `prereg` and `report`, as their own PR, from main.
