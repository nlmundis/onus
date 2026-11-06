---
date: 2026-11-06
scope: "the `onus.baseline` defects left open by the fix-closure review of #10 to #12"
state: in-progress
prs: [24, 32, 33, 34]
next: the maintainer answers the fix-or-disclose question on #34 and merges the four pull requests
---

# Handoff: baseline fixes (2026-11-06)

This note follows `2026-11-06-l1-amendments.md`.

## State

All four pull requests are open and none is merged. Each had a green `make check` on its branch, a clean leak scan,
and a targeted review.

| Pull request | Defect | `make check` | Mutants |
| --- | --- | --- | --- |
| #24 | `make approve` wording | exit 0, 451 tests | 412 of 412 |
| #32 | B06, the received file | exit 0, 453 tests | 414 of 414 |
| #33 | `_tests_of` with tests inside the code | exit 0, 459 tests | 417 of 417 |
| #34 | B03, the `__wrapped__` chain | exit 0, 467 tests | 428 of 428 |

All four merged together in a scratch clone: `make check` exit 0, 480 tests, 100% coverage, 438 of 438 mutants
caught, the no-op surviving.

## Merging

#33 and #34 conflict in two places, whichever merges second: the refusal in `unreal`, and E17's "What 'real' means".
Keep `{who}` from #34 and the wording of the rule from #33. In E17, keep #34's sentences on the chain, then #33's on
the tests, then each pull request's new bullet. #24 and #32 merged without conflict. `mutt_check.toml` merged cleanly
in the scratch clone.

The `scrub` and `signoff` pull requests also touch `mutt_check.toml` and `docs/plan.md`. They were not part of the
scratch merge.

## Decision for the maintainer

`functools.wraps(real)` laid over `functools.lru_cache(fake)` replaces the cache's `__wrapped__`, and the function
inside the C wrapper cannot be read, so the chain names only real code and the fake is accepted. The answers are:

- Disclose it. #34 does this in E17, and `lru_cache(real)` keeps working.
- Refuse every wrapper placed only by its class. This closes the hole, and no memoized producer could then be approved.

The first is built as a default. It is not yet the maintainer's choice.

## Open to veto, as built

- **#32:** the received path is new on every failure, so nothing can read a fixed location, and each failing run
  leaves a folder for the system to clear.
- **#33:** the test package is known by its name, `tests` or `test`. A test package of any other name inside the code
  stays refused. A helper in `e2e/` with tests in `e2e/tests/` reads as code under test.
- **#34:** a proxy whose true class has no file is refused, `wrapt`'s decorators among them. This worked before.
  Generated code, frozen modules, and zipped packages are refused too.

## Known limits, in E17

- `tempfile` ends its search in the current folder, so with no system temporary folder writable the received text
  lands there.
- The tests are read from the name the test was imported under, so `discover -s tests` narrows them to the test's
  own folder. A base class in another package is not read, a symlinked or split package maps to the wrong folders,
  and a top-level `tests` is not seen from `mypkg/tests`. Each lets a helper pass.

## Open, not fixed

- A text that cannot be encoded as UTF-8 raises `UnicodeEncodeError` from `assertApproved`.
- A partial received file can remain after a failed write, and `label="approved"` gives a received file with
  `.approved` in its name.
- In `unreal`, an import that raises anything but `ImportError` or `ValueError`, a lazy proxy whose `__getattr__`
  raises, and a compiled file name holding a NUL or a surrogate escape as raw exceptions.
- A test class in a `__main__` with no file raises a raw `OSError`.
- `docs/plan.md`'s library section still speaks of `make approve` as first
  written; E17 records that none exists.

## Not verified

- The commits made after each review had no second review, except #34's first round of fixes.
- The received-file work ran on macOS only, by hand. Linux comes from CI. Root and a real second user were not run.

## Lessons

- **A review's fix can make a mutant equivalent.** Adding the second `tests` folders in #33 left a mutant on the
  order of the names surviving. Simplifying the code removed the decision, and so the mutant.
- **A test with a default approved folder can pass for the wrong reason.** The approved folder's parent also counts
  as the tests, so a test of the test's own folder has to keep its approved files elsewhere.
- **A mutant's stated reason is worth checking.** A mock at the end of a chain is refused with or without the mock
  check, because it has no file. Only a mock in the middle shows that the check matters.
