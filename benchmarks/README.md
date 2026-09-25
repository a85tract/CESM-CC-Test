# Benchmarks — case definitions and acceptance criteria

One file per validated case, at `benchmarks/<product>/<case-id>.yaml`. The file name's
stem is the case id, and a manifest's `cases[].benchmark` points at this path — the
verifier checks both.

**This directory is the source of truth for acceptance criteria.** A comparator reports
what it measured; the benchmark decides which of those measurements gate. `make_manifest.py`
copies the `acceptance` block from here into the manifest, so changing a criterion means
editing a benchmark, never editing an acceptance record.

`TEMPLATE.yaml` is an annotated starting point, with both shapes: `bitwise` for a
whole-model run pair, and `unit-differential` for a RecastEngine case, whose measurements
are the verdicts in the case repository's `verification.json`.

## Products

| Directory | Files | State |
|---|---|---|
| `clubb-jax/` | 15 | one per committed summary at clubb-jax `99c8b22f`; all 15 evaluate PASS. See `clubb-jax/README.md` |
| `clm-ml-jax/` | 2 | schema-valid, not yet evaluable: the case commits a merged verdict-string file, not the engine's schema-1 summary. See `clm-ml-jax/README.md` |
| `pycam5/` | 0 | bitwise whole-model cases, not written yet |
| `freecam/` | 0 | not written yet |

`elm-jax/` is added when that case repository exists (`docs/CORRECTNESS-ORGANIZATION.md`
step 7). The four directories for products that do not exist (`jax-kernels`,
`numba-kernels`, `pyphys-bridge`, `pyccpp`) were removed on 2026-09-24.

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

## Exceptions: ungated, waived, gated and failing

A unit-differential benchmark has three ways to treat a unit that does not meet the plain
gate. They claim different things and are not interchangeable.

- **`ungated`**, on a rule, with a `reason`: the rule does not judge the unit, because the
  gate cannot meaningfully judge it there — no recorded call reaches it, the sampled oracle
  cannot build a reference for its drivers, or the reference itself rounds differently
  from any faithful translation. The unit must still appear in `unit_set_equal`, so the gap
  shows in the criterion and in every manifest built from it.
- **`waivers`**, on `ulp_tiered`, with a bound and a `reason`: the unit is judged and
  accepted beyond the gate, up to the bound, because the residual was measured to be
  conditioning of the reference. A waiver without that measurement is not a waiver.
- **Gated and failing**: the unit was judged and the verifier called the residual a
  defect. It stays gated, and the case reads FAIL. Removing it is a maintainer's decision,
  written into the benchmark with a reason, never an adjustment made so a run passes.

`clubb-jax/README.md` lists every ungated unit and waiver in that product;
`clm-ml-jax/README.md` has the three gated-and-failing units.
