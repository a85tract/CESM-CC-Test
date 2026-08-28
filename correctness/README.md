# Correctness half — framework

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

## Status

Every module here is a **stub**. Each states its inputs, its outputs, and the invariants it
has to enforce, then raises `NotImplementedError`. That is deliberate: a stub that returned
an empty result would let a caller record a passing evidence package for a comparison that
never happened, which is the same failure mode the schema's explicit `gating`, `ERROR`
status, and per-check states exist to prevent.

| Module | Migration step | Blocked on |
|---|---|---|
| `compare_runpair.py` | 2 | nothing — port from `PyCAM5/scripts/validation/compare_cesm_runpair.py` |
| `make_manifest.py` | 3 | `compare_runpair.py` |
| `verify_evidence.py` | 3 | nothing — invariants are listed in `../schemas/README.md` |
| `compare_stats.py` | 8 | decision D4 — the statistical acceptance vocabulary is not agreed |

## Conventions these tools share

- **`--json` writes to stdout, human-readable text to stderr.** A caller can pipe one into
  the next without parsing prose.
- **The JSON matches the schema's shape directly.** `compare_runpair.py --json` emits
  objects that drop into `cases[].result.files[]` and `cases[].result.timing` with no
  transformation, so `make_manifest.py` never has to reshape anything.
- **Exit codes are three-valued, matching the schema's `status`:** `0` PASS, `1` FAIL,
  `2` ERROR (the comparison could not be carried out — a missing file, a mismatched file
  set). A failed comparison and an absent comparison are not the same result.
- **Reference vs candidate, not native vs codon.** The candidate is Codon for PyCAM5,
  Python-owned control flow for freeCAM, and a GPU kernel for Pipeline 2. The old option
  names stay as hidden aliases so existing scripts keep working.
