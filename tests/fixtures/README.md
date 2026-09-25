# Test fixtures

| File | What it is | Source |
|---|---|---|
| `recast-summary.toy_physics.json` | A real RecastEngine run summary (`recast run translate corpus/toy_physics --summary`, `schema: 1`): one unit, three verdicts (`static.rwset` sampled, `differential.bitexact` bit_exact, `symbolic.notary` symbolic) | `RecastEngine-Pro/corpus/toy_physics/verification.json` at engine commit `430d90388f659ca750df2e9824faca22555f28e2` |

The summary is the input a `unit-differential` case hands to `make_manifest.py`.
It is copied rather than referenced so the suite runs in a bare checkout; when
the engine changes the summary's shape, re-copy it and record the new commit
here — a diff in this file is a change in what CC-Test has to read.
