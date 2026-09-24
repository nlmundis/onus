# Working in onus

onus is a public, MIT-licensed library. Anything committed here is published, so every test fixture is
synthetic: no client names, no real addresses, no paths from anyone's machine, no data from another repo.

## Commands

- `make check` is the whole gate and the only definition of done. Paste its raw output, never a filtered
  one, when claiming anything passes.
- `make test` is the fast loop: the suite on the pinned interpreter.
- `make format`, `make lint`, `make types`, `make coverage`, `make compat`, `make dist`, and `make mutants`
  are the gate's stages, runnable alone. `make dist` builds the sdist and wheel from the files git tracks, in
  a scratch folder, and checks them with `tools/check_dist.py`, the same script the release runs; commit a
  new file before expecting it in the build.

The interpreters are pyenv's exact patches, the one in `.python-version` and `COMPAT_PIN` for the floor
check, each handed to uv by path; never let uv discover or download one. `make interpreters` resolves both
before any stage runs, and `make gate-env` prints the settings make exports to every stage. Tools run through uvx or `uv run --no-project` at the versions pinned in the Makefile.

## Rules

- **No runtime dependency.** `dependencies = []`. Only `onus.invariants` may import hypothesis, and only
  through the `invariants` extra.
- **A released function's numeric output never changes.** A fix ships as a new `method=` value, never as a
  changed default. `alternative` and `method` arguments are keyword-only and have no default.
- **A mutant enters `mutt_check.toml` only together with the test that kills it**, and the test must fail
  for the reason the mutant names, not a syntax or import error. No test may skip.
- **Never write a sign-off line.** `onus.signoff` records a person's approval from their own terminal; a
  session, a script, or a test never writes one to a real ledger.
- **The Makefile and both workflows have reviewed copies** in `tests/approved/`, and `ApprovedFilesTest`
  fails on any difference. Change one only together with its copy, in the same commit, so the diff shows the
  reviewer every changed line of the gate or the release.
- **Branch, then PR.** Never commit to `main`; the ruleset refuses it anyway. Stage by path.

## Releasing

1. Set `onus.__version__` to the new number in a PR, and merge it to `main`.
2. Tag the merge commit on `main` with `vX.Y.Z` and push the tag. Every `v*` tag starts the release workflow.
   It runs the whole gate on that commit; refuses a tag that is not on `main` or does not match
   `__version__` (so `v0.1` is refused, not ignored); builds and checks the sdist and wheel with
   `tools/check_dist.py`; and attaches them to a GitHub Release. Nothing goes to PyPI.

**Every `v*` tag is permanent.** The "release tags never move" ruleset refuses deleting or moving one, and
no one can bypass it, so a tag pushed by mistake stays, and its version is spent: fix the cause, set
`__version__` to the next unused version in a PR, merge it, and tag that merge commit. Each refusal says
this. Only the repository admin can take a stray tag away, by disabling the ruleset, deleting the tag, and
enabling the ruleset again; after that the name is free to push again.

## Rulesets

`.github/rulesets/*.json` are the records of the two live rulesets; GitHub does not read these files. Find a
live ruleset's id with `gh api repos/nlmundis/onus/rulesets --jq '.[] | [.id, .name]'`. After changing a
record, apply it with `gh api -X PUT repos/nlmundis/onus/rulesets/<id> --input <file>`. To compare, fetch
only the fields a record holds, since the live ruleset carries more (id, source, links, timestamps):
`gh api repos/nlmundis/onus/rulesets/<id> --jq '{name, target, enforcement, conditions, bypass_actors,
rules}'`, and compare it with `jq '{name, target, enforcement, conditions, bypass_actors, rules}' <file>`.
