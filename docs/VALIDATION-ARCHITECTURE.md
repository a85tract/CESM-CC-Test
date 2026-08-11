# CC-Test Validation Architecture

**Status**: proposal, pending review. Nothing implemented; no existing file modified.
**Date**: 2026-08-10
**Scope**: this repository (`CESM-CC-Test`) plus a two-file addition to each product repository.
**Supersedes**: `docs/CORRECTNESS-REFACTOR.md` (earlier draft, same architecture).

---

## 1. The model

CC-Test = **C**orrectness and **C**yber Test. The Cyber half exists today (gitleaks,
syft→grype, AI audit, AddressSanitizer). The Correctness half is empty. This document
builds it as a **hybrid**: CC-Test is the central validation infrastructure and the
evidence index; every product repository shows its own validation status locally.

No separate results repository is created.

| Content | Location |
|---|---|
| Validation workflow, shared schema, comparison tools | CC-Test |
| Benchmarks, reference output, acceptance criteria | CC-Test, one directory per product |
| CI configuration that calls CC-Test | Each product repository |
| Short validation summary for the current version | `VALIDATION.md` in each product repository |
| Full evidence package per release | CC-Test `evidence/` index; product release links to it |
| Large outputs, logs, data | Release assets or long-term storage — never committed to Git |

This satisfies two audiences at once:

- A user landing on `PyCAM5` or `freeCAM` immediately sees whether that product is validated.
- A PESOSE reviewer landing on CC-Test sees one cross-product, reproducible assurance
  system with provenance.

---

## 2. Ground truth (measured 2026-08-10)

| Observation | Consequence |
|---|---|
| CC-Test contains only `tools/ hpc/ hooks/` — no schema, benchmark, or evidence | The Correctness half is genuinely at zero |
| CC-Test `README.md` calls itself `hpc-devsecops` (install path `~/hpc-devsecops`), while the overview calls it CC-Test | Identity conflict — resolved in §8, D1 |
| No product repository has `.gitleaks.toml`, `.vex/openvex.json`, or `.github/scripts/ai_audit.py` | The Cyber half's "reuse the target repo's own config" contract is currently unfulfilled everywhere; checks skip silently |
| Only PyCCPP has `.github/workflows/`, inherited from ESCOMP/CAM and guarded by `github.repository == 'ESCOMP/CAM'` | Effectively no product repository has working CI |
| `PyCAM5/scripts/validation/compare_cesm_runpair.py` (~250 lines) is the only correctness comparator | It is the seed of the Correctness half, but prints text only — no machine-readable output |
| Same file: `return 0 if overall_numeric_ok` — char differences and timing are computed but do not affect the exit code | Acceptance criteria are implicit — see §4, adjustment C |
| `PyCAM5/test/system/archive_baseline.sh` targets goldbach / yellowstone | CAM upstream legacy; those machines are retired, script unusable |
| `cc-test`, `PyCAM5`, `PyCCPP` have **zero** Git tags | The sketch's `evidence/pycam5/v0.2.0/` layout assumes tags that do not exist — see §8, D2 |
| Pipeline 1 criteria are bitwise; Pipeline 2 criteria are "1.24e-6 rel diff" / "within ensemble spread" | Two criteria families; the schema must express both |
| Validation actually happens on Derecho: PBS jobs, CESM builds, multi-year integrations, `/glade` scratch output | A GitHub-hosted runner cannot execute validation — see §4, adjustment A |

---

## 3. Products in scope

| Product | Pipeline | Criteria family | Current evidence to backfill |
|---|---|---|---|
| `PyCAM5` | 1 | bitwise | PI + MCO 6-month all-Codon, 2026-06-16, `overall_numeric_equal=True` |
| `freeCAM` | 1 | bitwise | CAM-SIMA oracle gate: 7 pinned suites, `ne3np4.pg3`, 24 ranks, 50 steps |
| `PyCCPP` | 1 | — | Early stage, not integrated; placeholder directory only |
| `jax-kernels` | 2 | statistical | HS94 6-member ne16 500 steps 1.24e-6 rel diff; TJ2016 7.52e-3 within ensemble spread |
| `numba-kernels` | 2 | statistical | ZM 30yr 720/720 rc=0; MG 3yr 72/72 rc=0 |
| `pyphys-bridge` | 2 | statistical | Deployment/integration runs; shares Pipeline 2 criteria |

The sketch's example directories `pyccpp/` and `jaxcam6/` are replaced by the actual
submodule names above; there is no `jaxcam6` repository.

---

## 4. Three adjustments to the sketch

The architecture is right. Three points need to change on contact with the machines.

### Adjustment A — CI verifies evidence; it does not produce evidence

`<product>/.github/workflows/validation.yml` cannot call CC-Test to *run* validation. One
6-month all-Codon PI/MCO validation needs Derecho's ifx toolchain, CESM input data, hours
of compute, and `/glade` storage. A GitHub-hosted runner has none of these.

So the pipeline splits into two layers — **producing** evidence and **verifying** evidence:

```
Layer 1 — produce evidence   (HPC, PBS / manual, offline)
  Derecho: run reference + candidate
        -> CC-Test comparator --json
        -> evidence/<product>/<version>/manifest.json
        -> pull request into CC-Test

Layer 2 — verify evidence    (GitHub Actions, every PR, seconds)
  In CC-Test:      manifest validates against schema; artifact_commit exists in the
                   product repo; acceptance rules and result are self-consistent;
                   no duplicate version directory
  In the product:  the commit declared in VALIDATION.md is HEAD, or the drift is
                   declared; the linked evidence package exists and reads PASS
```

Layer 2 is everything that can genuinely run in CI, and it is worth running: it catches
the failure mode where `VALIDATION.md` says PASS but points at a commit that stopped being
the current code months ago.

### Adjustment B — large output is tiered, and Git holds only the manifest

The sketch says large outputs go to Release assets or long-term artifact storage, never
into Git. Correct, with one bound made explicit: a GitHub release asset is capped at
**2 GiB per file**, and a 30-year CESM history set is orders of magnitude past that. So
"Release assets" covers the derived artifacts, not the raw model output.

| Tier | Content | Location | Scale |
|---|---|---|---|
| 0 | `manifest.json`, `summary.md`, `report.txt` | Committed to CC-Test `evidence/` | KB |
| 1 | Comparison plots, per-variable diff tables, run logs, PBS logs, timing dumps | GitHub Release assets on the CC-Test release for that evidence package | MB — under 2 GiB per file |
| 2 | NetCDF history/restart files, ensemble member output | HPC storage (`/glade` scratch or campaign); never uploaded | GB — TB |

Tier 2 data is recorded in the manifest by `location`, `retention` (including the expected
purge date), and a per-file `md5` + byte count. The manifest stays valid after the data is
purged — it preserves the fingerprint, which is what a later re-run needs to compare
against. Reproducibility rests on the manifest, not on data custody.

### Adjustment C — implicit acceptance criteria must become explicit

Current behaviour of `compare_cesm_runpair.py`:

| Check | Computed | Affects exit code |
|---|---|---|
| Per-variable md5 equality, numeric variables | yes | **yes** |
| Char variable differences | yes | no |
| GPTL timing delta % | yes | no |

Today's de facto criterion is therefore "numeric BFB only". That is defensible — char
variables often carry timestamps, and timing should not gate correctness — but it must be
written into the manifest's `acceptance` block with an explicit `gating` flag per rule.
Otherwise the PASS an evidence package claims has no defined meaning.

---

## 5. Target layout

```
CESM-CC-Test/
├── README.md                       # rewritten: Correctness + Cyber, two halves
├── docs/
│   └── VALIDATION-ARCHITECTURE.md  # this file
│
├── schemas/                        # DONE (step 1)
│   ├── evidence-manifest.v1.json   # JSON Schema draft 2020-12, see §6
│   ├── acceptance.v1.json          # criteria vocabulary: bitwise | statistical
│   ├── README.md                   # design notes + invariants left to the verifier
│   ├── test_schemas.py             # schema self-test
│   └── examples/
│       └── example-bitwise.manifest.json
│
├── correctness/                    # SCAFFOLDED — every module is a stub
│   ├── README.md                   # how the four tools compose
│   ├── compare_runpair.py          # step 2: port from PyCAM5, add --json
│   ├── compare_stats.py            # step 8: blocked on D4
│   ├── make_manifest.py            # step 3: comparator output + probe -> manifest
│   └── verify_evidence.py          # step 3: schema + invariants; the CI entry point
│
├── tools/  hpc/  hooks/            # existing Cyber half, untouched
│
├── benchmarks/                     # SCAFFOLDED — format defined, cases empty
│   ├── README.md                   # the format, and why it owns the criteria
│   ├── TEMPLATE.yaml               # annotated starting point
│   └── {pycam5,freecam,pyccpp,jax-kernels,numba-kernels,pyphys-bridge}/
│
├── evidence/                       # SCAFFOLDED — append-only, nothing filed yet
│   ├── README.md                   # the rules: immutability, versioning, retention
│   └── INDEX.md                    # generated cross-product table
│                                   # -> <product>/<version>/{manifest.json,summary.md,report.txt}
│
└── .github/workflows/
    ├── verify-evidence.yml         # validates every manifest in this repo
    └── validation-callable.yml     # workflow_call, reused by product repos
```

Two notes on the layout:

- The sketch places workflows at a top-level `workflows/`. GitHub only resolves reusable
  workflows under `.github/workflows/`, so the callable workflow lives there. HPC-side job
  templates (PBS scripts that produce evidence) stay in the existing `hpc/` directory.
- `correctness/` sits beside `tools/` (Cyber) at the same level, so both C's of "CC" are
  visible in the directory tree, not only in the name.
- `evidence/` is append-only: once a version's manifest lands it is immutable; a re-run
  produces a new version directory.

---

## 6. Evidence manifest

The binding contract from the sketch is the required core. The v1 schema is a strict
superset of it — every field in the minimal contract survives, at a defined path:

| Minimal contract field | v1 schema path |
|---|---|
| `artifact` | `artifact.name` |
| `artifact_commit` | `artifact.commit` |
| `reference_version` | `reference.model` + `reference.commit_or_tag` |
| `cc_test_version` | `cc_test.version` + `cc_test.commit` |
| `environment` | `environment` (structured object) |
| `acceptance_criteria` | `cases[].acceptance` (structured rule list) |
| `result` | `result` (top level, rolled up from `cases[].result.status`) |
| `timestamp` | `timestamp` |

The schema is implemented in `schemas/evidence-manifest.v1.json` and
`schemas/acceptance.v1.json`, with a worked instance in
`schemas/examples/example-bitwise.manifest.json`. Rather than restating it here and letting
the two drift, this section records only why it expands the minimal contract:

| Expansion | Reason |
|---|---|
| `artifact` / `reference` / `cc_test` become objects | Must pin repo, commit, and human-readable version simultaneously |
| `cases[]` added | One validation is normally several cases (PI + MCO); a single flat result cannot express that |
| `acceptance` becomes a structured rule list, `gating` required on every rule | Directly resolves adjustment C — the schema makes it impossible to leave the criterion implicit |
| `acceptance.kind: bitwise \| statistical` | Covers Pipeline 2 (relative tolerance, ensemble spread) |
| `result.checks[]` mirrors `acceptance.rules[]` one-to-one | Lets the verifier prove that the claimed status follows from the declared rules |
| `status` includes `ERROR`, not just PASS/FAIL | A file-set mismatch means nothing was compared; the comparator already exits 2 for it |
| `numeric_md5_equal` records `dump_format` and `dump_tool` | The digest is only comparable across manifests that used the same dump format |
| `evidence_class: complete \| reconstructed` | Backfilled history cannot always name the compiler or reference revision; better to mark it than to invent it |
| `outputs.retention`, `outputs.assets_release`, per-file md5 | Directly resolves adjustment B; ties tier 1 and tier 2 to the manifest |
| `environment` becomes structured | A single free-text string cannot be diffed between runs |

One correction to the sketch's wording, from reading the comparator: the numeric digest is
**one md5 per output file**, taken over a single fixed-format dump of all numeric variables
in that file. Only character variables are digested individually. "Per-variable md5" would
describe the character path only.

The statistical variant of `acceptance` needs its own rule vocabulary — relative tolerance
and norm, the compared variable set, ensemble member count, and the spread test. It is
present in the schema as placeholder rules that must carry `"status": "provisional"`, and
the verifier rejects any manifest that uses them until the vocabulary is agreed; see §8, D4.

Cross-field invariants that JSON Schema cannot express — checks matching rules, the status
roll-up, commit resolution, append-only `evidence/` — are listed in `schemas/README.md` and
enforced by `correctness/verify_evidence.py` in step 3.

---

## 7. Product repository side

Each product repository gains exactly two files:

```
<product>/
├── VALIDATION.md
└── .github/workflows/validation.yml
      # uses: a85tract/CESM-CC-Test/.github/workflows/validation-callable.yml@<ref>
```

`VALIDATION.md` stays minimal — the manifest it links to is the only authority:

```markdown
# Validation Status

| | |
|---|---|
| Validated commit | `e8d68996` |
| Reference        | iCESM1.3.1_fzhu CAM, <ref-commit> |
| Validation date  | 2026-06-16 |
| Platform         | Derecho · ifx 2025.2.1 · <mpi> · Codon <ver> |
| Tests            | 2 cases (PI 6mo, MCO 6mo) — 2 passed, 0 failed |
| Criteria         | bitwise (numeric BFB, per-file digest of all numeric variables) |
| Result           | PASS |
| Evidence         | <permalink to CC-Test evidence/pycam5/v0.2.0/> |

> Current HEAD is N commits ahead of the validated commit.
```

The last line is generated and refreshed by CI — this is exactly the silent rot that
layer 2 of adjustment A exists to catch.

---

## 8. Decisions

The sketch settles three of the five decisions carried over from the earlier draft.

| # | Decision | Status |
|---|---|---|
| D1 | Repository identity: CC-Test (CAM validation hub) vs `hpc-devsecops` (generic tool) | **Settled by the sketch** — CC-Test is the central validation infrastructure. `README.md` is rewritten around two halves; the Cyber half is annotated "generic, usable standalone", keeping the current install instructions valid. |
| D2 | Version source for `evidence/<product>/<version>/` — all three repos have zero tags | **Settled in principle** — the sketch's `v0.2.0` layout means version directories are release tags, so products start tagging. Proposed bridge until a product cuts its first tag: `unreleased-<commit[:8]>`, with `artifact.commit` always authoritative. |
| D3 | How evidence reaches CC-Test from the HPC side | **Settled** — manual pull request. Derecho compute nodes generally have no outbound network, so automated push is not available. |
| D4 | Pipeline 2 statistical criteria | **Open — needs your input.** "1.24e-6 rel diff" and "within ensemble spread" must become executable: tolerance value and norm, the compared variable set, ensemble member count, and the spread test. No tool exists; `compare_stats.py` is net new work and cannot be specified without these definitions. |
| D5 | Cyber-half config gap: no product repo has `.gitleaks.toml`, `.vex/openvex.json`, or `ai_audit.py`, so those checks skip silently | **Out of scope here — owned by the security workstream.** Recorded because it is a real gap, not because this document proposes to close it. |
| D6 | Should an evidence package also record the Cyber gate's verdict for the same commit? | **Open — a proposal, and a cross-boundary one.** A `security` block on the manifest would make one package answer both "does this code compute the right answer" and "was it scanned", which is what makes CC-Test a single assurance system rather than two tools in one repository. It also imposes a contract on the gate's output (a machine-readable summary carrying a state per scan, so a zero count can be told apart from a scan that never ran). That contract has to be agreed with the security workstream, not assumed — so the schema deliberately does **not** define the block yet. |

---

## 9. Migration steps

Ordered so each step is independently reviewable.

**Who does what.** This repository provides the *framework*: the schema that says what an
evidence package is, the directory structure, and the interface contract each tool has to
satisfy. Filling those contracts in — the comparators, the manifest builder, the verifier,
and the per-product benchmark definitions — is Qinrun's. Every module under `correctness/`
is a stub that states its inputs, its outputs, and the invariants it must enforce, and
raises `NotImplementedError` rather than returning a plausible-looking wrong answer. The
Cyber half (steps 10, and D5/D6) belongs to the security workstream.

| # | Step | Lands in | Depends on |
|---|---|---|---|
| 1 | **DONE** — `evidence-manifest.v1.json` and `acceptance.v1.json`, bitwise vocabulary complete, statistical present but provisional and rejected by the verifier. Plus `schemas/README.md`, a format example, and `schemas/test_schemas.py` (3 positive + 12 negative assertions, all passing) | CC-Test `schemas/` | D2 |
| 2 | Move `compare_cesm_runpair.py` to `correctness/compare_runpair.py`; add `--json`; rename `native`/`codon` arguments to neutral `--reference-run-dir` / `--candidate-run-dir`, keeping old names as aliases | CC-Test | 1 |
| 3 | Write `make_manifest.py` (comparator JSON + environment probe → manifest) and `verify_evidence.py` | CC-Test | 1, 2 |
| 4 | Backfill the 2026-06-16 PI/MCO results from `PyCAM5/doc/internal_validation.md` as the first evidence package | CC-Test `evidence/pycam5/` | 3 |
| 5 | Write `benchmarks/pycam5/{pi,mco}-6month-allcodon.yaml`, extracting case definitions from `env_allcodon_675.sh` | CC-Test | 4 |
| 6 | Write `verify-evidence.yml` and `validation-callable.yml` | CC-Test `.github/` | 3 |
| 7 | Add `VALIDATION.md` + `validation.yml` to PyCAM5 | PyCAM5 | 6 |
| 8 | Define the statistical acceptance vocabulary, write `compare_stats.py`, extend to `jax-kernels` / `numba-kernels` / `pyphys-bridge` | CC-Test + product repos | 7, D4 |
| 9 | Extend to `freeCAM` (bitwise; the CAM-SIMA oracle gate becomes a benchmark case) | CC-Test + freeCAM | 7 |
| 10 | Close the Cyber config gap — **owned by the security workstream, not this plan** | Product repos | D5 |
| 11 | Rewrite CC-Test `README.md` around the two halves; update the overview's "Correctness later" line | CC-Test + overview | 8, 9 |

Step 2 should **move** rather than copy: PyCAM5 keeps a thin wrapper or simply a pointer in
its docs. Two comparators that can drift apart is precisely the problem the Cyber half's
"reuse the target repo's own config" rule was designed to avoid.

Step 4 is the make-or-break step. If the environment details of the 2026-06-16 run
(compiler version, reference commit, output paths) can no longer be recovered, that
manifest must be marked `"provenance": "reconstructed, incomplete"` and treated as a
format example rather than a compliance example. **This needs your confirmation that the
information is still obtainable.**

---

## 10. Non-goals

- No separate results repository.
- No NetCDF output committed into Git, and no assumption that raw model output fits in
  Release assets.
- No attempt to make GitHub Actions execute a CESM validation run.
- No changes to the Cyber half. `tools/`, `hpc/`, and `hooks/` are owned by the security
  workstream and are out of scope for this document — see D5 and D6.
- `sec-track` is out of scope (restricted access, handled separately).

