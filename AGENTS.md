# Working in onus

onus is a public, MIT-licensed library. Anything committed here is published, so every test fixture is
synthetic: no client names, no real addresses, no paths from anyone's machine, no data from another repo.

## Commands

- `make check` is the whole gate and the only definition of done. Paste its raw output, never a filtered
  one, when claiming anything passes.
- `make test` is the fast loop: the suite on the pinned interpreter.
- `make format`, `make lint`, `make types`, `make coverage`, `make compat`, and `make mutants` are the gate's
  stages, runnable alone.

The interpreters are pyenv's exact patches, the one in `.python-version` and `COMPAT_PIN` for the floor
check, each handed to uv by path; never let uv discover or download one. `make gate-env` prints the settings
every stage runs with. Tools run through uvx or `uv run --no-project` at the versions pinned in the Makefile.

## Rules

- **No runtime dependency.** `dependencies = []`. Only `onus.invariants` may import hypothesis, and only
  through the `invariants` extra.
- **A released function's numeric output never changes.** A fix ships as a new `method=` value, never as a
  changed default. `alternative` and `method` arguments are keyword-only and have no default.
- **A mutant enters `mutt_check.toml` only together with the test that kills it**, and the test must fail
  for the reason the mutant names, not a syntax or import error. No test may skip.
- **Never write a sign-off line.** `onus.signoff` records a person's approval from their own terminal; a
  session, a script, or a test never writes one to a real ledger.
- **Branch, then PR.** Never commit to `main`; the ruleset refuses it anyway. Stage by path.

## Releasing

1. Set `onus.__version__` to the new number in a PR, and merge it to `main`.
2. Tag the merge commit on `main` with `vX.Y.Z` and push the tag. The release workflow runs the whole gate on
   that commit, refuses a tag that is not on `main` or does not match `__version__`, checks the built
   artifacts, and attaches them to a GitHub Release. Nothing goes to PyPI.

**Every `v*` tag is permanent.** The "release tags never move" ruleset refuses deleting or moving one, with
no bypass. A tag pushed by mistake (wrong commit, wrong version, or a shape the workflow ignores such as
`v0.1`) cannot be reused: fix the cause and tag the next version. Removing a stray tag needs the repository
admin to disable that ruleset, delete the tag, and enable the ruleset again.

## Rulesets

`.github/rulesets/*.json` are the records of the two live rulesets; GitHub does not read these files. They
were applied with `gh api -X POST repos/nlmundis/onus/rulesets --input <file>`. After changing a record,
apply it with `gh api -X PUT repos/nlmundis/onus/rulesets/<id> --input <file>`, and compare a live ruleset
with its record through `gh api repos/nlmundis/onus/rulesets/<id>`.
