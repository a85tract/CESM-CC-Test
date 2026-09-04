# Correctness half

Four tools turn a pair of model runs into an evidence package that
`schemas/evidence-manifest.v1.json` accepts.

```
reference run ─┐
               ├─► compare_runpair.py --json ─┐
candidate run ─┘   (bitwise, Pipeline 1)      │
                                              ├─► make_manifest.py ─► evidence/<product>/<version>/
reference run ─┐                              │                       manifest.json
               ├─► compare_stats.py --json  ──┘                        summary.md
candidate run ─┘   (statistical, Pipeline 2)                           report.txt
                                                                            │
                                                                            ▼
                                                              verify_evidence.py  (CI)
```

The comparators run on HPC where the output lives. `verify_evidence.py` runs in CI, on the
committed manifest, in seconds. Nothing in this directory ever executes a model run — see
`../docs/VALIDATION-ARCHITECTURE.md` §4 for why that split exists.

`dataio.py` is not a tool: it is the input adapter both comparators share, and the one
place that decides how a file is read and dumped.

`check_validation_md.py` is the fifth tool and belongs to the other side of the split:
it runs against a *product* checkout, not against model output, and it is what
`../.github/workflows/validation-callable.yml` calls to ask whether a product's
`VALIDATION.md` still matches the evidence produced here — and whether the commit it
names is still that repository's HEAD.

## Status

| Module | Migration step | State |
|---|---|---|
| `compare_runpair.py` | 2 | **implemented** |
| `make_manifest.py` | 3 | **implemented** |
| `verify_evidence.py` | 3 | **implemented** — all 11 error invariants and 6 warnings from `../schemas/README.md` |
| `check_validation_md.py` | 6 | **implemented** — the product side of layer 2: the claim in a product's `VALIDATION.md` against the manifest, plus commit drift |
| `compare_stats.py` | 8 | **implemented, but decision D4 is still open.** It evaluates the rule kinds the schema names, under the readings recorded in `../docs/VALIDATION-ARCHITECTURE.md` §8.1. The schema keeps its `provisional` marker and `verify_evidence.py` still rejects statistical evidence |

Still to do here: migration step 5 (write the `benchmarks/<product>/*.yaml` files) and
step 4 (the first evidence package). Until benchmarks exist there is nothing for
`make_manifest.py` to read acceptance criteria from — which is why
`schemas/examples/example-bitwise.manifest.json` is reported by the verifier as naming
benchmarks that do not exist.

## Running them

```bash
# Layer 1, on HPC. Text report to stderr, machine-readable JSON to a file.
correctness/compare_runpair.py \
    --reference-run-dir /glade/derecho/scratch/$USER/pi-native/run \
    --candidate-run-dir /glade/derecho/scratch/$USER/pi-codon/run \
    --timer physpkg_st1 --timer bc_physics --timer CPL:RUN_LOOP \
    --json pi.json 2> report.txt

correctness/make_manifest.py \
    --case pi-6month-allcodon=pi.json \
    --benchmark-dir benchmarks/pycam5 \
    --artifact-repo ~/PyCAM5 \
    --reference-commit <baseline-sha> \
    --outputs-location /glade/derecho/scratch/$USER/pi-codon/run \
    --outputs-retention "scratch, purged ~2026-12-01" \
    --case-outputs pi-6month-allcodon=/glade/derecho/scratch/$USER/pi-codon/run \
    --security-summary ~/audits/hpc-devsecops/PyCAM5/<ts>/summary.json \
    --summary  evidence/pycam5/unreleased-e8d68996/summary.md \
    --out      evidence/pycam5/unreleased-e8d68996/manifest.json

# Layer 2, in CI or before opening the pull request.
correctness/verify_evidence.py                       # every manifest under evidence/
correctness/verify_evidence.py --base-ref origin/main --strict
```

`compare_stats.py` additionally needs the criteria, because a statistical comparison has no
criterion of its own:

```bash
correctness/compare_stats.py \
    --reference member0/ --reference member1/ --reference member2/ \
    --candidate candidate/ \
    --acceptance benchmarks/jax-kernels/hs94-ne16.yaml --json hs94.json
```

## Dependencies

Standard library, plus:

| Need | Used by | Absent means |
|---|---|---|
| `numpy` | both comparators, in-process backend | the comparators cannot run on non-NetCDF input |
| `jsonschema` + `referencing` | `verify_evidence.py`, and `make_manifest.py` for its pre-write check | the verifier exits **2** and says so; `make_manifest.py` warns that it wrote unvalidated |
| `PyYAML` | reading `benchmarks/*.yaml` | a clear error naming the alternative (`.json`), never a guessed criterion |
| NCO (`ncks`, `ncdump`) *or* `netCDF4` / `xarray` | reading `.nc` | `.nc` input is ERROR / exit 2 with a message naming all three ways out |

```bash
python3 -m venv .venv && .venv/bin/pip install numpy jsonschema pyyaml pytest
.venv/bin/python -m pytest tests/
.venv/bin/python schemas/test_schemas.py
```

`tests/test_correctness.py` uses `.npz` and text tables only, so the whole suite runs in a
bare checkout with no NetCDF stack at all.

## Two backends, and the manifest records which one ran

A numeric digest is only comparable against a digest taken the same way — that is why the
manifest carries `dump_tool` beside `dump_format`. So the comparator picks one backend for
the whole comparison and names it in its output:

- **`ncks`** — the original path: `ncks -C -H -s FORMAT` for one digest per file, `ncdump`
  per character variable. Chosen automatically when every input is `.nc` and NCO is on
  PATH. Produces digests comparable with everything filed to date, and has no access to the
  values, so it reports no per-field detail.
- **`numpy`** — in-process. Reads `.npy`, `.npz`, text tables, and `.nc` when `netCDF4` or
  `xarray` is importable. Its dump carries a `# name dtype shape` header per variable, so
  the byte stream differs from NCO's and the two digests must never be compared. In
  exchange it holds the arrays, so it reports per-field `max_abs` and `max_rel`.

`--dump-tool` forces one; the default is `auto`.

## Conventions these tools share

- **`--json` writes to stdout, human-readable text to stderr.** A caller can pipe one into
  the next without parsing prose. `--json PATH` writes the JSON to a file instead.
- **The JSON matches the schema's shape directly.** `compare_runpair.py --json` emits
  `files[]` and `timing` that drop into `cases[].result` with no transformation, so
  `make_manifest.py` never has to reshape anything. The other top-level keys are what
  `make_manifest.py` needs in order to decide the acceptance rules.
- **Exit codes are three-valued, matching the schema's `status`:** `0` PASS, `1` FAIL,
  `2` ERROR (the comparison could not be carried out — a missing file, a mismatched file
  set, an unreadable format, no overlapping variables). A failed comparison and an absent
  comparison are not the same result. `verify_evidence.py` reads the same way: `0` clean,
  `1` findings, `2` nothing could be verified.
- **Silence is not an available answer.** A rule with no measurement behind it is never a
  pass. If it gates, the case is ERROR and the check is written `passed: false` with the
  reason in `detail` — the schema forbids `null` on a gating check, and the ERROR status is
  what distinguishes this from a comparison that ran and failed. If it does not gate, the
  check is `passed: null` with the reason, which is what null is for.
- **Reference vs candidate, not native vs codon.** The candidate is Codon for PyCAM5,
  Python-owned control flow for freeCAM, and a GPU kernel for Pipeline 2. The old option
  names stay as hidden aliases so existing scripts keep working.
- **The benchmark owns the criteria.** A comparator reports what it measured;
  `benchmarks/<product>/<case>.yaml` decides which of those measurements gate, and
  `make_manifest.py` copies that block into the manifest verbatim. Changing a criterion
  means editing a benchmark, never editing an evidence package.
