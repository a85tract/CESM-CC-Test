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
├── correctness/                    # the Correctness half (steps 2-3 DONE)
│   ├── compare_runpair.py          # migrated from PyCAM5, plus --json
│   ├── compare_stats.py            # Pipeline 2 statistical comparator (new)
│   ├── make_manifest.py            # comparator output + environment probe -> manifest
│   ├── verify_evidence.py          # schema + self-consistency check; the CI entry point
│   └── dataio.py                   # shared input adapters; not a command-line tool
│
├── tests/
│   ├── run.sh                      # Cyber half, integration
│   └── test_correctness.py         # Correctness half, synthetic inputs, no NetCDF needed
│
├── tools/  hpc/  hooks/            # Cyber half — see §11
│   ├── devsecops-local.sh          #   per-scan state + summary.json (updated)
│   ├── install-config.sh           #   installs the templates below (new)
│   └── test-ai-audit.py            #   self-test for the auditor (new)
│
├── templates/                      # NEW — the config each product repo needs
│   ├── .gitleaks.toml
│   ├── .vex/openvex.json
│   └── .github/scripts/ai_audit.py
│
├── benchmarks/                     # case definitions and acceptance baselines
│   ├── pycam5/
│   │   ├── pi-6month-allcodon.yaml
│   │   └── mco-6month-allcodon.yaml
│   ├── freecam/
│   ├── jax-kernels/
│   ├── numba-kernels/
│   ├── pyphys-bridge/
│   └── pyccpp/                     # placeholder
│
├── evidence/                       # the index — manifests and summaries only
│   ├── INDEX.md                    # generated cross-product table
│   ├── pycam5/
│   │   └── v0.2.0/
│   │       ├── manifest.json
│   │       ├── summary.md
│   │       └── report.txt
│   └── jax-kernels/
│       └── v0.1.0/
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
| `security` block, required, with a state beside every count | Makes each evidence package a joint claim — this code computes the right answer *and* it was scanned. A missing block would be indistinguishable from a clean scan, so absence is not permitted; `NOT_RUN` is |
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
| D4 | Pipeline 2 statistical criteria | **Still open — needs your input.** "1.24e-6 rel diff" and "within ensemble spread" must become executable: tolerance value and norm, the compared variable set, ensemble member count, and the spread test. `compare_stats.py` now exists and evaluates the two rule kinds the schema names, but it did **not** settle D4: it states the reading it uses for each undecided point (§8.1), the schema keeps its `provisional` marker, and `verify_evidence.py` still rejects any manifest that files evidence against it. |
| D5 | Cyber-half config gap: no product repo had `.gitleaks.toml`, `.vex/openvex.json`, or `ai_audit.py`, so those checks skipped silently | **Settled — in scope, and the CC-Test side is done.** `ai_audit.py` did not exist anywhere, so it was written rather than merely installed. Templates for all three now live in `templates/`, `tools/install-config.sh` installs them into a target repo, and the evidence manifest records the Cyber verdict (§6). Installing into the six product repos is step 10. |

### 8.1 D4 readings decided by implementation on 2026-09-03, revisit if wrong

Writing `compare_stats.py` meant choosing a meaning for every point D4 leaves open. The
alternative was a tool that picked one silently. Each choice below is the most conservative
reading available — the one least likely to call something a PASS that a stricter reading
would fail — and each is recorded here so that settling D4 is a matter of confirming or
overturning a written decision rather than reverse-engineering the code. They are also
stated in `correctness/compare_stats.py`'s docstring, beside the line that implements them.

| Open point | Reading taken | Why this one |
|---|---|---|
| Which variables are compared | Exactly those the rule names; every one must be present in both inputs and every one must pass. An absent variable is ERROR | An aggregate, or a silently skipped variable, would let a PASS cover fewer variables than it claims |
| What the tolerance applies to | The normwise ratio per variable: `‖cand − ref‖ / ‖ref‖` in the declared norm, over the whole array | Matches how the dashboard figures read. The elementwise alternative `max │d_i│/│ref_i│` is stricter but is dominated by near-zero reference elements |
| `l2` vs `rmse` | Both computed; as ratios they are arithmetically the same number, the element count cancels | Kept distinct because the rule records which norm was declared and the reported absolute norm differs |
| Reference norm is zero | The rule passes only on exact equality; no epsilon is added to the denominator | An epsilon turns "nothing to compare against" into a pass |
| Region / time mean | Whole field, every time level, no subsetting and no averaging | Averaging is what lets a large local error hide |
| Non-finite values | Same non-finite mask on both sides: those elements are excluded from the norms and the count is reported. Different masks: FAIL | CAM fill values are legitimate; a mask that moved is a real difference between the runs |
| Ensemble member count | Fewer members than the rule requires is ERROR | A smaller ensemble has a smaller spread, so accepting one silently widens nothing and hides everything |
| "Within spread" | Elementwise, and the candidate must be inside the band at **every** element. `stddev` = mean ± m·σ with ddof 0 (the tighter estimate); `minmax` = envelope midpoint ± m·half-width; `iqr` = median ± m·(IQR/2). A zero-width band admits only exact equality | The strictest of the readings on offer; `<=` and `>=` are taken literally, with no tolerance added to the band edges |

None of this removes `"status": "provisional"` from `schemas/acceptance.v1.json`. Removing
that marker is the signal that D4 has been agreed by people, and it is not a side effect of
having written the tool.

---

## 9. Migration steps

Ordered so each step is independently reviewable.

| # | Step | Lands in | Depends on |
|---|---|---|---|
| 1 | **DONE** — `evidence-manifest.v1.json` and `acceptance.v1.json`, bitwise vocabulary complete, statistical present but provisional and rejected by the verifier. Plus `schemas/README.md`, a format example, and `schemas/test_schemas.py` (3 positive + 12 negative assertions, all passing) | CC-Test `schemas/` | D2 |
| 2 | **DONE** — `correctness/compare_runpair.py` carries the PyCAM5 comparator with `--json`, neutral `--reference-run-dir` / `--candidate-run-dir` (old names kept as hidden aliases), and the three-valued exit code. Removing the copy from PyCAM5 is still to do | CC-Test | 1 |
| 3 | **DONE** — `make_manifest.py` (comparator JSON + benchmark + environment probe + the Cyber gate's `summary.json` → manifest) and `verify_evidence.py` (schema + all 11 error invariants and 6 warnings from `schemas/README.md`). `tests/test_correctness.py` covers pass / findings / incomplete for each tool and the make_manifest → verify_evidence round trip | CC-Test | 1, 2 |
| 4 | Backfill the 2026-06-16 PI/MCO results from `PyCAM5/doc/internal_validation.md` as the first evidence package | CC-Test `evidence/pycam5/` | 3 |
| 5 | Write `benchmarks/pycam5/{pi,mco}-6month-allcodon.yaml`, extracting case definitions from `env_allcodon_675.sh` | CC-Test | 4 |
| 6 | **DONE** — `verify-evidence.yml` (every manifest under `evidence/`, with `--base-ref` so the append-only invariant runs on pull requests) and `validation-callable.yml` (`workflow_call`, checks a product's `VALIDATION.md` against the evidence and measures commit drift). `correctness/check_validation_md.py` was added because the drift check needs one place that reads both sides; `tests/test_validation_md.py` covers it. CI also gained a `correctness` job — `tests/test_correctness.py` had never run in CI | CC-Test `.github/` | 3 |
| 7 | Add `VALIDATION.md` + `validation.yml` to PyCAM5 | PyCAM5 | 6 |
| 8 | **Half done** — `compare_stats.py` is written and evaluates both rule kinds, under the readings recorded in §8.1. Still needed: agreement on D4 (which turns those readings from a written default into the criterion), removing the schema's `provisional` marker, and extending to `jax-kernels` / `numba-kernels` / `pyphys-bridge` | CC-Test + product repos | 7, D4 |
| 9 | Extend to `freeCAM` (bitwise; the CAM-SIMA oracle gate becomes a benchmark case) | CC-Test + freeCAM | 7 |
| 10 | **CC-Test side DONE** — `ai_audit.py` written, all three templates in `templates/`, `tools/install-config.sh` installs them, runner reports per-scan state. Remaining: run the installer against the six product repos and commit the result | Product repos | D5 |
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
- No rewrite of the Cyber half. It was originally listed here as untouched; closing D5
  changed that, and the edits are named so the claim stays honest. `tools/asan.sh`,
  `hpc/asan-cam.pbs`, and `hooks/pre-push` are unchanged. `tools/devsecops-local.sh`
  gained per-scan state tracking, a `summary.json`, and a `--require-complete` flag — see
  §11 — because the manifest's `security` block cannot be filled honestly from a runner
  that reports a zero count identically whether or not the scan ran.
- `sec-track` is out of scope (restricted access, handled separately).

---

## 11. The Cyber half

Closing D5 turned up more than missing configuration.

**`ai_audit.py` never existed.** The runner reads it from
`<target>/.github/scripts/ai_audit.py` and the README calls it "your `ai_audit.py`", but
no copy was present in any repository in the tree. The AI audit had therefore never run
against any product. `templates/.github/scripts/ai_audit.py` is a written implementation:
it reviews a unified diff with Claude under a structured-output schema, splits large
diffs by file so nothing is silently truncated, and writes `ai-audit.sarif` plus a
Markdown report.

**The false-clean bug was wider than the one already fixed.** Commit `f964acd` stopped the
AI audit reporting `reviewed` when it had failed. The same defect remained in the other
two planes: with gitleaks or grype absent, their counters stayed at zero and the gate
printed `✅ clean`. "Not scanned" and "scanned, found nothing" were indistinguishable in
the output — and would have been indistinguishable in any evidence built from it.

`tools/devsecops-local.sh` now tracks a state per scan (`scanned` / `not_installed` /
`failed` / `skipped`), reports `INCOMPLETE` rather than `clean` when any plane did not
run, and writes a machine-readable `summary.json` beside `summary.txt` for
`make_manifest.py` to read. `--require-complete` exits non-zero on an incomplete gate;
`--block` keeps its original meaning, so the pre-push hook's behaviour is unchanged unless
a repository opts in.

**The manifest records the Cyber verdict.** `security` is a required block on every
evidence manifest, with a required state beside every count and an explicit `NOT_RUN`
status. An evidence package therefore always states whether the validated code was
scanned; silence is not an available answer. This is what makes CC-Test one assurance
system rather than two tools sharing a repository — a reviewer reads a single manifest and
sees both that the code computes the right answer and that it was scanned for
vulnerabilities, at the same commit.

**Known gap.** Producing a `security` block on the HPC side needs the gate to run where
there is outbound network: grype's vulnerability database and the AI audit's API both need
egress, which Derecho compute nodes do not have. Run the gate on a login node or locally
and feed its `summary.json` into `make_manifest.py`; the schema's `INCOMPLETE` status
exists so a partial run is still recordable rather than silently omitted.
