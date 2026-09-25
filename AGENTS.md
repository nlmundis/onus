# Working in onus

onus is a public, MIT-licensed library. Anything committed here is published, so every test fixture is
synthetic: no client names, no real addresses, no paths from anyone's machine, no data from another repo.

## Commands

- `make check` is the whole gate and the only definition of done. Paste its raw output, never a filtered
  one, when claiming anything passes.
- `make test` is the fast loop: the suite on the pinned interpreter.
- `make format`, `make lint`, `make types`, `make coverage`, `make compat`, `make dist`, and `make mutants`
  are the gate's stages, runnable alone. `make dist` builds the sdist and wheel from the files git tracks
  (with their working-tree contents), in a scratch folder, and checks them with `tools/check_dist.py`, the
  same script the release runs. It refuses a module under `onus/` that git does not track yet: `git add` it.
  The build backend is not pinned: pyproject.toml asks for `setuptools>=77`, and `make dist` and the release
  each build with the newest version uv resolves when they run, so a setuptools release between the two can
  change or break the artifacts.

The interpreters are pyenv's exact patches, the one in `.python-version` and `COMPAT_PIN` for the floor
check, each handed to uv by path; never let uv discover or download one. `make interpreters` resolves both
before any stage runs, and `make gate-env` prints the settings make exports to every stage. Tools run
through uvx or `uv run --no-project` at the versions pinned in the Makefile.

## Rules

- **No runtime dependency.** `dependencies = []`. Only `onus.invariants` may import hypothesis, and only
  through the `invariants` extra.
- **A released function's numeric output never changes.** A fix ships as a new `method=` value, never as a
  changed default. `alternative` and `method` arguments are keyword-only and have no default.
- **A mutant enters `mutt_check.toml` only together with the test that kills it**, and the test must fail
  for the reason the mutant names, not a syntax or import error. No test may skip.
- **Never write a sign-off line.** `onus.signoff` records a person's approval from their own terminal; a
  session, a script, or a test never writes one to a real ledger.
- **The files that define the gate and the release have reviewed copies** in `tests/approved/`: the
  Makefile, `pyproject.toml`, `MANIFEST.in`, and every workflow. `ApprovedFilesTest` fails on any byte of
  difference, and on a workflow with no copy. Change one only together with its copy, in the same commit, so
  the diff shows the reviewer every changed line of the gate or the release. CI runs `ApprovedFilesTest` in its
  own step before the gate, outside make, so no line in a pinned file can switch that check off.
- **The Makefile is the only makefile.** make reads only the first of `GNUmakefile`, `makefile`, and
  `Makefile` that it finds, so either of the others beside it would be read instead, and could `include` it
  with its failures switched off. `make siblings` refuses both, and CI runs `make -f Makefile check`, which
  reads the Makefile whatever else is there.
- **pyproject.toml holds every tool's settings.** `make siblings`, which the gate runs before its first stage,
  refuses a `ruff.toml`, `.ruff.toml`, `mypy.ini`, `.mypy.ini`, `.coveragerc`, `setup.cfg`, `tox.ini`, or
  `uv.toml` at the root (and the gate sets `UV_NO_CONFIG=1`, so uv reads no config file anywhere), and every
  tool is handed pyproject.toml explicitly, so a config file in a subfolder is not read either.
  pyproject.toml also stops black and ruff from skipping what a `.gitignore`, `.ignore`, or
  `.git/info/exclude` lists, so no ignore file can take a module out of the format or lint stage.
- **Workflows hand third-party code no token.** Every action is pinned by commit (with its tag in a comment),
  every checkout sets `persist-credentials: false`, and the gate's token can only read; `WorkflowTokenTest`
  checks all three. Only the release's Create step holds a write token, through `GH_TOKEN`.
- **Branch, then PR.** Never commit to `main`; the ruleset refuses it anyway. Stage by path.

## Releasing

1. Set `onus.__version__` to the new number in a PR, and merge it to `main`.
2. Tag the merge commit on `main` with `vX.Y.Z` and push that tag on its own (`git push origin vX.Y.Z`).
   The release workflow runs the whole gate on that commit; refuses a tag that is not on `main` or does not
   match `__version__` (so `v0.1` is refused, not ignored); builds and checks the sdist and wheel with
   `tools/check_dist.py`; and attaches them to a GitHub Release. Nothing goes to PyPI.

GitHub reads a tag's workflows from the tagged commit, so a `v*` tag starts the release workflow only on a
commit that carries `.github/workflows/release.yml`; main's first commit (`e36cb6e`) has none, so a tag on it
starts nothing and is still permanent. GitHub also starts no workflow for tags pushed more than three at a
time, or pushed by a workflow's own token, so push release tags by hand and one at a time. A valid tag that
started no run is stranded, since the ruleset keeps it from being pushed again; the admin removal below, then
pushing it alone, releases it.

**Every `v*` tag is permanent.** The "release tags never move" ruleset refuses deleting or moving one, and no
one can bypass it, so a tag pushed by mistake stays, and its version is spent: fix the cause, set
`__version__` to the next unused version in a PR, merge it, and tag that merge commit. Each refusal the
release job makes says whether the tag is spent. A tag whose gate fails skips the release job. When the
failure is the commit's own (a test, lint, types, or the dist check failing on its files), the tag is spent
the same way; when it is not (the network, a lost runner, a tool that could not be fetched), re-running the
failed jobs clears it, so re-run them once before calling the tag spent. A refusal that says the tag is not
spent (main could not be fetched, the build could not run) usually clears by re-running the job; a build that
still cannot run on the re-run has its cause in the commit, such as a build requirement no index has, and the
tag is spent. Only the repository admin can take a tag away, by disabling the ruleset, deleting the tag, and
enabling the ruleset again; after that the name is free to push again.

## Rulesets

`.github/rulesets/*.json` are the records of the two live rulesets, every setting included; GitHub does not
read these files. Find a live ruleset's id with `gh api repos/nlmundis/onus/rulesets --jq '.[] | [.id,
.name]'`. After changing a record, apply it with `gh api -X PUT repos/nlmundis/onus/rulesets/<id> --input
<file>`. To compare a live ruleset with its record, project both onto the record's fields (the live one also
carries its id, source, links, and timestamps) and sort their keys; no output means they match:

```bash
F='{name, target, enforcement, conditions, bypass_actors, rules}'
diff <(gh api repos/nlmundis/onus/rulesets/<id> --jq "$F" | jq -S .) <(jq -S "$F" <file>)
```
