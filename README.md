# onus

*Onus probandi*: the burden of proof. onus makes a claim carry its own evidence, fixed before anyone looked:

- **an experiment's verdict** comes from an exact statistical test under a rule registered before the data;
- **a rendered output** is still the one a person approved, or the test says what changed;
- **a function's behaviour** holds an invariant over generated inputs, deterministically inside the gate.

It is built for `unittest` suites and has no runtime dependencies.

## Status

Scaffold only (v0.0.0): packaging, the gate, and the repository's own invariants. v0.1.0 brings:

| Subpackage | What it gives a caller |
|---|---|
| `onus.stats` | Exact binomial and sign tests, Wilson and Clopper-Pearson intervals, Holm and Benjamini-Hochberg over declared families, and exact power, minimum detectable effect, and the true size of a peeking schedule |
| `onus.prereg` | Pre-registration records bound to content hashes, dated amendments, a fixed horizon, and post-hoc labelling of anything amended after it was read |
| `onus.report` | One sentence per result carrying its n, sidedness, family correction, the minimum detectable effect when it is not significant, and its provenance |
| `onus.scrub` | Composable scrubbers for dates, paths, and ids, so outputs compare byte for byte |
| `onus.baseline` | Approved outputs committed beside the tests; a mismatch fails with a diff, and re-approval is an explicit `make` target |
| `onus.signoff` | A hash-chained ledger of human sign-offs for ground truth, which only a person at a terminal can write |
| `onus.invariants` | Deterministic Hypothesis profiles and generators for unittest (the `invariants` extra) |

## Develop

```bash
make check
```

Needs pyenv with the patch in `.python-version` installed, and uv. See `AGENTS.md` for the rules.

## License

MIT.
