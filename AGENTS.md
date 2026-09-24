# Working in onus

onus is a public, MIT-licensed library. Anything committed here is published, so every test fixture is
synthetic: no client names, no real addresses, no paths from anyone's machine, no data from another repo.

## Commands

- `make check` is the whole gate and the only definition of done. Paste its raw output, never a filtered
  one, when claiming anything passes.
- `make test` is the fast loop: the suite on the pinned interpreter.
- `make format`, `make lint`, `make types`, `make coverage`, `make compat`, and `make mutants` are the gate's
  stages, runnable alone.

The interpreter is pyenv's exact patch in `.python-version`, handed to uv by path; never let uv discover or
download one. Tools run through uvx or `uv run --no-project` at the versions pinned in the Makefile.

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
