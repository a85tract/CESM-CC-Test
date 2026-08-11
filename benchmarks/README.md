# Benchmarks — case definitions and acceptance criteria

One file per validated case, at `benchmarks/<product>/<case-id>.yaml`. The file name's
stem is the case id, and a manifest's `cases[].benchmark` points at this path — the
verifier checks both.

**This directory is the source of truth for acceptance criteria.** A comparator reports
what it measured; the benchmark decides which of those measurements gate. `make_manifest.py`
copies the `acceptance` block from here into the manifest, so changing a criterion means
editing a benchmark, never editing an evidence package.

`TEMPLATE.yaml` is an annotated starting point. Product directories are empty — filling
them in is migration step 5 (Pipeline 1) and step 8 (Pipeline 2, blocked on decision D4).

## Format

| Key | Required | Notes |
|---|---|---|
| `id` | yes | Must equal the file stem; `^[a-z0-9][a-z0-9-]*$` |
| `product` | yes | Directory name, e.g. `pycam5` |
| `description` | yes | One line, for the generated evidence index |
| `case` | yes | How to reproduce the run: `compset`, `resolution`, `duration`, `ranks`, and whatever else the machine needs |
| `reference` | yes | What the candidate is compared against, and how that baseline was produced |
| `acceptance` | yes | Copied verbatim into the manifest — must validate against `../schemas/acceptance.v1.json` |

`acceptance` is the part worth care. Every rule carries an explicit `gating` flag, and a
bitwise block must contain at least one gating rule; the schema rejects a block in which
nothing gates, because a PASS from such a block would mean nothing. Rules that are computed
but do not gate — character-variable differences, timing deltas — belong here too, marked
`gating: false`, so the manifest records that they were measured and deliberately ignored.
