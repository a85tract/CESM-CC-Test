# Where the Correctness work lives

**Status**: decided 2026-09-24 on the two open points (D7, D8 below); migration steps 1-4 done the same day. D9 decided 2026-09-25: CC-Test is the SciRecast site's results source, and the Cyber move (step 9) is split into 9a-9e and brought forward ahead of step 6. Step 9a done 2026-09-25 (engine branch `audit-gate-summary`, not yet a PR). Step 10 done 2026-09-25 (`evidence/index.json`; the SciRecast page that fetches it is still to do in that repository).
**Date**: 2026-09-24
**Scope**: every repository that holds a piece of the numerical-correctness story of the
SciRecast modernization effort. `VALIDATION-ARCHITECTURE.md` describes the acceptance
record and the HPC/CI split and still stands; this document decides which repository
owns which part, and narrows what CC-Test is.

---

## 1. What was measured

Surveyed on 2026-09-24, local checkouts under `~/agent/`:

| Repository | What it is | Correctness content |
|---|---|---|
| `RecastEngine-Pro` | the engine (973 commits) | all comparison mechanisms: `src/recast/verify/` (bitexact, tolerance, ulp, notary, rwset, conditioning, finite_derivative, forward_workload, python_accelerators, probes), `src/recast/oracle/` (f2py-golden, dump-replay, numpy-anchor, record), the `Confidence` ladder and `Evidence.to_manifest()` in `model.py`, `conformance/`, `corpus/baseline.json` |
| `RecastEngine` | the public edition | same shape, tier-marked; no separate correctness content |
| `RecastEngine-clubb`, `RecastEngine-elm` | **not repositories** — two working copies of `RecastEngine-Pro` (same remote, different HEADs) used by the CLUBB and ELM cases to re-gate | none of their own |
| `RecastEngine-Pro-Lean` | a Lean 4 audit of the Fortran→NumPy translation path, pinned at Pro `8ff23c5` | 184 rules, 113 with obligations, 65 proved / 24 conditional / 31 refuted; 20 hand-driven probes; `rules.json`, `defects.json` |
| `recast-cesm`, `recast-clm-ml`, `recast-clubb`, `recast-elm` | domain extensions, plugins of the engine | no comparator of their own. Input domains, stubs, kinds, oracle variants, `UNGATED` tables, per-model default gates in `recipe.py`. `recast-cesm` also carries 56 promoted CAM scripts (checksum diffs, climate diagnostics, ensemble drift). `recast-elm` additionally carries the ELM *case* (`case/`, 16 GB `output/`) |
| `cesm/clubb-jax`, `cesm/clm-ml-jax` | cases: pinned upstream, recordings, generated code, verdict summaries | their own copies of L2 tooling: `tools/closed_loop.py`, `tools/run_step.py` (its own `ulp_distance`), `tools/check_derivatives.py`; `column.py`, `month_jax.py`, `gradients.py`, `compare_authors*.py` (its own ULP via `np.spacing`) |
| `cesm/PyCAM5`, `cesm/freeCAM` | products (whole-model) | `scripts/validation/compare_cesm_runpair.py` (the copy step 2 was meant to remove); `src/freecam/pi_cam/validation.py` (a second directory-level BFB comparator); `test/recast/` module gates; `validation/*.json` records |
| `CC-Test` | this repository | `schemas/`, `correctness/` (two comparators, `make_manifest.py`, `verify_evidence.py`, `dataio.py`), empty `benchmarks/` and `evidence/` |

Five distinct *claims* are being made, and today they are spread across four kinds of repository:

| Level | The claim | Where the mechanism is | Where the result is |
|---|---|---|---|
| L0 translator soundness | the engine's rewrite rules are sound | `RecastEngine-Pro-Lean` | `rules.json`, `defects.json`, `RESULTS.md` |
| L1 unit differential | one translated unit matches the f2py-compiled or recorded original, bit-exact or within a ULP bound | engine `verify/` + `oracle/`; extensions supply domains and stubs | one `recast.evidence.v1` record per verdict in each case's `output/evidence/` (8,498 on this machine, none committed); committed `verification.json` / `summaries/tier*.json` |
| L2 composed | closed-loop trajectory, 31-day column, gradient consistency | **each case, separately**; the engine's `forward_workload` and `finite_derivative` are generic versions nobody calls | CSV/log/PNG under each case's `evidence/` or `output/` |
| L3 whole model | a CESM run pair is bit-for-bit, or statistically within a bound | **three comparators**: CC-Test `compare_runpair.py`, PyCAM5 `compare_cesm_runpair.py`, freeCAM `pi_cam/validation.py`; CC-Test `compare_stats.py` | `/glade` paths in `PyCAM5/doc/internal_validation.md`; `freeCAM/validation/*.json` |
| record | that any of the above ran, and what it concluded | CC-Test `evidence-manifest.v1` + `verify_evidence.py`; engine `Evidence.to_manifest()` + `conformance/manifest.py`; per-product ad hoc JSON | nothing filed in `evidence/` yet |

## 2. The defects in the current arrangement

Ordered by cost.

**One name, two formats.** `RecastEngine-Pro/AGENTS.md` and `model.py` say "CC-Test owns
`evidence-manifest.v1.json`; `Evidence.to_manifest()` is the only place the two vocabularies
meet." A per-verdict record the engine wrote for `recast-elm`, labelled a CC-Test manifest at the time, (`output/evidence/fortran_soiltemperaturemod/5c958f…json`)
fails this repository's schema with 19 errors: `security` missing, `cases` empty, `result` an
object rather than `PASS|FAIL|ERROR`, `cc_test.commit` the literal `unknown`, `artifact` and
`environment` missing required keys. The engine's own `conformance/manifest.py` encodes a
*different* reading of v1 and passes the same document. This is the retrospective's lesson 4,
"one fact in two places", in the one place both sides agreed it must not happen.

**D4 was settled in code, in the wrong repository.** `schemas/acceptance.v1.json` still marks
statistical criteria `provisional` and `verify_evidence.py` rejects them. Meanwhile every JAX
product is gated by `RecastEngine-Pro/src/recast/verify/tolerance.py`: dominant elements
(within 1e-3 of the row maximum) within **32 ULP**, every element within **rel 1e-12**, with
per-unit waivers to 128 and 192 ULP justified by `conditioning.py`, and verdicts taken under
`XLA_FLAGS=--xla_backend_optimization_level=0 --xla_disable_hlo_passes=algsimp`. That *is*
the Pipeline 2 criterion in use, and the acceptance vocabulary here cannot express it.

**L2 and L3 are reimplemented per repository.** ULP distance exists three times (engine
`verify/ulp.py`, clubb-jax `tools/run_step.py`, clm-ml-jax via `np.spacing`). Closed-loop
comparison exists three times (clubb-jax, clm-ml-jax, recast-elm `case/closed_loop.py`)
beside the engine's unused `forward_workload`. Directory-level BFB exists three times.

**Recordings have no storage policy.** clubb-jax keeps 22 GB gitignored; clm-ml-jax commits
~800 MB of recordings and publishes 5.3 GB as a release asset; recast-elm holds 16 GB in a
plugin repository's `output/`. `VALIDATION-ARCHITECTURE.md` §4-B defines tiers 0/1/2 for
CESM output only.

**Cases have no CI and no `VALIDATION.md`.** The engine commit each result set was taken at
is written by hand in READMEs; nothing checks it.

**CC-Test's product list is fiction.** `benchmarks/{jax-kernels,numba-kernels,pyphys-bridge,pyccpp}/`
name repositories that do not exist. The real products are `clubb-jax`, `clm-ml-jax`, the ELM
case, `PyCAM5`, `freeCAM`.

**Two documents disagree about what CC-Test is.** This repository's README calls itself the
hub of two halves; `RecastEngine-Pro/docs/architecture.md` lists CC-Test as "the cyber half"
and has absorbed its gate as `recast.scan` and the `audit` recipe.

## 3. The ownership rule

One sentence, continuing the one already at the top of `recast/scan/__init__.py`:

> **The comparison algorithm belongs to the engine. Knowledge of the model, and that model's
> default gate, belong to its extension. A particular recording, pinned upstream, and current
> verdict summary belong to the case. What was judged about a released version, and the
> criterion it was judged by, belong to CC-Test.**

The test for each placement is the retrospective's: the engine must translate and gate the
corpus with no extension installed; an extension must need no engine patch; a case must run
with the engine and its extension installed and nothing else.

### 3.1 Decisions

| # | Decision | Status |
|---|---|---|
| D7 | Where the whole-model comparator lives | **Settled 2026-09-24: the engine.** `correctness/compare_runpair.py` and `dataio.py` become the `fullmodel.bitwise` Verifier that the engine's `refactor-todo` recipe already names and nobody registered. The engine forbids `netCDF4` in `recast.*`, so the reader that knows CAM history files — the `*.cam.{h0,r,rh0,rs}.*.nc` patterns, the `%+.17g` ncks dump — is injected from `recast-cesm`, which already describes itself as owning "dump formats". `compare_stats.py` follows the same path once D4 is written down. PyCAM5's copy is deleted; freeCAM's `compare_pi_cam_directories` calls the same verifier. |
| D8 | What CC-Test is | **Settled 2026-09-24: its acceptance records and the criteria, nothing else.** CC-Test keeps `schemas/`, `benchmarks/`, `evidence/`, `make_manifest.py`, `verify_evidence.py`, and the architecture documents. It runs no comparison. The Cyber gate's tooling under `tools/`, `templates/`, `hooks/`, `hpc/` is owned going forward by the engine's `recast.scan` and `audit` recipe; what CC-Test keeps of it is the `security` block in the manifest, which records the verdict. README D1 is superseded by this. |
| D9 | Who reads the acceptance records, and when the Cyber tooling moves | **Settled 2026-09-25: CC-Test is the results source for the SciRecast website, and the Cyber move comes forward.** The public site (`a85tract/SciRecast`, static `index.html` + `assets/`, no build step) already links CC-Test twice; it reads `evidence/index.json`, which `correctness/index_evidence.py` emits beside `INDEX.md` (one entry per acceptance record: product, version, artifact commit, result, security status, timestamp, `evidence_class`, case count and passed count, path), instead of carrying hand-written result tables (step 10). CC-Test is the cross-product *ledger* of acceptance records, not a *case* repository: a case such as clubb-jax holds one product's recordings and summaries. The repository is not renamed (§5). The Cyber move, formerly step 9 and last, is split into 9a-9e and runs before step 6. The gate summary the engine's `audit` recipe will write is CC-Test's existing `summary.json`, not a new format: findings never enter CC-Test, only per-scan states and counts do, and `make_manifest.py` already reads that file. The LLM audit lands in recast-cesm, not the engine, by the maintainer's decision of 2026-08-21 that it stays out of the public repository. The move is owned by Chien-Wei (README "Who owns what"), so 9a is agreed with them before code moves. |

### 3.2 Per repository

| Repository | Keeps | Receives | Gives up |
|---|---|---|---|
| `RecastEngine-Pro` | every comparison mechanism, the `Confidence` ladder, the `Evidence` producer, recipes | `fullmodel.bitwise` (from CC-Test `compare_runpair.py` + `dataio.py`); the generic parts of clubb-jax `closed_loop.py`/`run_step.py`, clm-ml-jax `column.py`/`gradients.py`, recast-elm `case/gradients.py`, folded into `forward_workload` and `finite_derivative`; a `port` recipe base for the three near-identical `*PortRecipe` stage lists | its private reading of v1 in `conformance/manifest.py`, replaced by an identity test against this repository's schema |
| `recast-cesm` / `-clm-ml` / `-clubb` / `-elm` | domains, stubs, kinds, oracle variants, `UNGATED` tables, the model's *default* gate values | the CAM NetCDF reader for `fullmodel.bitwise` (recast-cesm) | recast-elm's `case/` and 16 GB `output/` — they become an `elm-jax` case repository shaped like the other two |
| cases: `clubb-jax`, `clm-ml-jax`, `elm-jax`, `PyCAM5`, `freeCAM` | pinned upstream, recordings with `RECORDING.md` provenance, `configs/`, committed `verification.json` (current state, diffable), `VALIDATION.md`, a `validation.yml` that checks the declared commit against HEAD | nothing | every comparison script; PyCAM5 `compare_cesm_runpair.py`; freeCAM's comparator body |
| `CC-Test` | `schemas/`, `benchmarks/` (the only place a criterion is written), `evidence/`, `make_manifest.py`, `verify_evidence.py`, docs; `evidence/index.json`, which the SciRecast site reads (D9) | Lean audit results registered as evidence (product `recastengine-pro`, version = the pinned engine commit) | `compare_runpair.py`, `compare_stats.py`, `dataio.py`; ownership of the Cyber tooling: the gate summary to the engine's `audit` recipe; the LLM audit, ASan and the audit prompts to recast-cesm |
| `RecastEngine-Pro-Lean` | itself, unchanged; it audits the engine, not a product | | its 31 refuted rules become engine issues |
| `RecastEngine-clubb`, `RecastEngine-elm` | nothing — retired. Cases already pin the engine per unit in `generated/MANIFEST.json`; install with `pip install 'recast-engine @ git+…@<sha>'` | | |

### 3.3 Criteria written once

The benchmark file is the only place a criterion is written. The extension's `recipe.py`
carries the same value as the run's default, and `make_manifest.py` checks that the gate the
manifest records equals the benchmark's — equality is asserted by a test, not assumed from a
copy. The acceptance vocabulary gains what L1 needs:

```yaml
acceptance:
  kind: unit-differential          # beside bitwise and statistical
  summary_schema: 1                # the `schema` of the engine's verification.json
  rules:
    - check: unit_set_equal        # always gating: the units the case must cover
      units: ["fortran:advance_clubb_core_module", "fortran:pdf_closure_module"]
      gating: true
    - check: confidence_at_least   # the engine's Confidence ladder
      verifier: differential.bitexact
      level: bit_exact
      gating: true
    - check: ulp_tiered            # decision D4, as recast.verify.tolerance enforces it
      verifier: differential.tolerance
      dominant_at: 1.0e-3
      ulp_gate: 32
      rel_gate: 1.0e-12
      waivers:
        "fortran:pdf_closure_module": {ulp_gate: 192, reason: "measured conditioning, see ..."}
      gating: true
    - check: nan_mask_equal
      verifier: differential.tolerance
      gating: true
```

The XLA flags a verdict was taken under are a property of the run, not of the criterion;
they are recorded in the manifest's `environment` (`xla_flags`), which admits any string
field.

This is D4, transcribed from `tolerance.py` and the two case READMEs rather than invented,
and it landed in `schemas/acceptance.v1.json` on 2026-09-24 (step 1). The ensemble-spread
family stays `provisional` until a whole-model statistical case actually uses it.

### 3.4 One evidence flow

```
engine writes one record per verdict        case/output/evidence/       tier 0, not committed (audit trail)
case commits verification.json              case/                       tier 0, committed  (current state, diffable)
release: make_manifest bundles              CC-Test evidence/<product>/<version>/
    verification.json + benchmark criteria      manifest.json summary.md report.txt
pull request into CC-Test, CI runs verify_evidence
```

The 8,498 per-verdict records do not enter CC-Test. One acceptance record per product version does;
`cases[]` holds one row per benchmark case, and each case's rules range over every unit
in the summary. The per-verdict record cannot honestly be a CC-Test acceptance record — it does not
know the product repository, the benchmark, the machine or the compiler, and forcing it
into that shape is how the engine came to write documents CC-Test's schema rejected on 19
counts. So the engine's record is its own format, `recast.evidence.v1`
(`Evidence.to_record()`, checked by `recast.conformance.evidence_record`), and the two
vocabularies meet in one place: CC-Test's `make_manifest.py`, which reads the summary
(`schema: 1`) under a `unit-differential` benchmark. The summary's shape is therefore the
interface between the repositories, and `tests/fixtures/recast-summary.toy_physics.json`
pins the copy CC-Test is tested against, with the engine commit it came from.

### 3.5 Storage tiers, extended to recordings

| Tier | Content | Where | Now |
|---|---|---|---|
| 0 | manifests, `verification.json`, `summaries/*.json` | git | fine |
| 1 | recordings and closed-loop CSV/PNG under 2 GiB | release asset of the case repo, sha256 in the manifest | clm-ml-jax already does this for `recording-31day-20260830`; its ~800 MB of committed recordings move here |
| 2 | full-case recordings (13 GB `recorded_full_gabls2`, the 2.6 GB ELM tower months) | local or HPC storage; manifest records location, sha256, byte count, expected purge | clubb-jax and recast-elm, once `RECORDING.md` gains the fingerprint |

## 4. Migration order

Each step is one reviewable pull request; none depends on a later one.

Step numbers are identities, not positions: other files cite "step 5", "step 6", "step 8"
of this document, so they do not change. Since D9 (2026-09-25) the execution order is
1-5 (done or next), then 9a-9e, then 10, then 6, 7, 8. The numbers are this table's only:
`VALIDATION-ARCHITECTURE.md` §9 has its own step table, and its step 10 (install the Cyber
config into the product repos) is a different step, absorbed here into 9d.

| # | Step | Lands in | Why this position |
|---|---|---|---|
| 1 | **DONE 2026-09-24.** `unit-differential` acceptance kind in `acceptance.v1.json` with `unit_set_equal`, `confidence_at_least`, `ulp_tiered`, `nan_mask_equal`; `make_manifest.py` evaluates them from a RecastEngine summary and fingerprints it; format example and tests. Engine: `Evidence.to_manifest()` → `to_record()` emitting `recast.evidence.v1`, `conformance/manifest.py` → `evidence_record.py`, `cc_test` slot removed, docs corrected | CC-Test, engine | smallest change, largest defect |
| 2 | **DONE 2026-09-24.** `benchmarks/clubb-jax/`: 15 cases, one per committed summary (`tier0`-`tier3`, `port`, `cases-{more,e3sm,scalars,late,multicol}-{numpy,jax}`), unit lists from the summaries, ungated units and conditioning waivers from the case README; every one evaluates PASS against clubb-jax `main` (`99c8b22f`, engine `e3c6717`). `benchmarks/clm-ml-jax/`: `port-day1`, `port-day15`, schema-valid but not evaluable until the case commits an engine `--summary` file (its `run_port.py` writes a merged verdict-string file instead). Rule-level `ungated` added to the acceptance vocabulary for known coverage gaps | CC-Test | criteria before evidence |
| 3 | **DONE 2026-09-24.** `benchmarks/` holds `pycam5`, `freecam`, `clubb-jax`, `clm-ml-jax`; the four directories for products that do not exist are gone. `elm-jax` is added when step 7 creates the case repository | CC-Test | |
| 4 | **DONE 2026-09-24, from clubb-jax rather than clm-ml-jax**, which is still blocked on its summary format (step 2). `evidence/clubb-jax/unreleased-99c8b22f/`: clubb-jax `99c8b22f` against CLUBB_core `8ab3902`, engine `e3c6717` under `recast-clubb`, validated 2026-09-21T19:44Z (the re-gate in clubb-jax PR #13); 15 cases, one per benchmark, all PASS; `evidence_class: complete`; `security.status: NOT_RUN`, because the Cyber gate has not been run against that commit. Each case's `outputs.files` fingerprints the summary it was judged from; the 14 GB of recordings stay local to the case and are not retained. Assembled with `make_manifest.py --no-probe` and explicit `--machine`/`--env` (invocation in `benchmarks/clubb-jax/README.md` "Re-evaluating"); `verify_evidence.py --artifact-checkout clubb-jax=...` reports 0 errors, 1 warning (NOT_RUN), 1 skipped check (append-only, no `--base-ref`). `correctness/index_evidence.py` regenerates `evidence/INDEX.md` (`--check` for staleness). Caveat: `cc_test.commit` is `86a46e8c`, the commit that holds the `unit-differential` kind, the benchmarks and the `make_manifest.py` changes that produced the record: those were committed first, the record assembled at that commit and committed after it. Invariant 7 only checks that the commit resolves, so this ordering is procedure, not something the verifier enforces. The PyCAM5 backfill (`VALIDATION-ARCHITECTURE.md` step 4) still waits on recovering the 2026-06-16 environment and is filed `reconstructed` if that fails | CC-Test `evidence/clubb-jax/` | first real run of the whole flow |
| 5 | Move `compare_runpair.py` + `dataio.py` into the engine as `fullmodel.bitwise`; CAM reader into `recast-cesm`; delete PyCAM5's copy; freeCAM's `verify_pi_cam.py` calls the verifier. `compare_stats.py` follows as `fullmodel.statistical` | engine, recast-cesm, PyCAM5, freeCAM, CC-Test | D7 |
| 6 | Fold the three cases' closed-loop, step-replay and gradient scripts into `forward_workload` / `finite_derivative`; cases keep only `recast run` invocations | engine, three cases | now follows step 9 (D9) |
| 7 | Split `recast-elm/case/` + `output/` into an `elm-jax` case repository; retire `RecastEngine-clubb` and `RecastEngine-elm` | recast-elm, new repo | |
| 8 | `VALIDATION.md` + `validation.yml` in every case; register the Lean audit under `evidence/recastengine-pro/<commit>/` | cases, CC-Test | |
| 9a | **DONE 2026-09-25, on the engine branch `audit-gate-summary` (not yet a PR).** `recast run <recipe> <root> --gate-summary PATH` writes the gate summary CC-Test already reads: the exact shape `tools/devsecops-local.sh` writes as `summary.json` (`tool`, `status`, `repo`, `commit`, `mode`, `base`, `range`, `diff_lines`, `timestamp`, `scans` with `secrets` {state, findings}, `cve` {state, critical, high, scope}, `ai_audit` {state, high}) plus one field `"schema": 1`. `commit` is HEAD of the scanned tree, read from the `.git` files without spawning a process (`unknown` if not a checkout). Per-plane state is the script's vocabulary: `passed`/`reviewed`, `findings` (at or above the scanner's `blocks_on` bar: any secret, only a Critical CVE), `unavailable` (tool not on PATH; `ScannerUnavailable` gained a `missing_tool` keyword, set by the `secret` and `composition` scanners), `error` (any other failure to run), `skipped` (declared, never ran), `not_configured` (not in the recipe). Roll-up is the script's: any `unavailable`/`error` → `INCOMPLETE`; else any `findings` → `FINDINGS`; else `PASS`; `not_configured` does not make the gate incomplete. Never a finding: a scanner's finding is `PLAUSIBLE` and lands in the local finding store, and it reaches Sec-Track only after adjudication and a human's disclosure decision, none of which CC-Test sees. Implementation: `RecipeRun.gate_summary()` in `src/recast/run.py`, a `ScanReport` per scanner stage on `UnitRun.scans`, `RecipeRun.scanners` (plugin → family); six tests in `tests/test_run.py`. End-to-end on this machine (gitleaks, syft, grype installed), `recast run audit ~/agent/cesm/CC-Test --gate-summary …`: secrets passed (0), cve passed (0 Critical, 3 High), ai_audit `not_configured`, status `PASS`, commit `1865fa70`; `make_manifest.py --security-summary` read it unchanged into a manifest's `security` block (gate `recast audit`, secrets scanned, vulnerabilities scanned 0/3, ai_audit unreviewed). One reconciliation, in CC-Test's `make_manifest.py` and nowhere else: the script's `PASS` means "nothing blocking among the checks that ran" and does not count a `not_configured` plane against it; the schema's `PASS` (`evidence-manifest.v1.json`, `security.status`) means every plane ran and nothing blocking was found, and `verify_evidence.py` invariant 11 enforces that. So a gate summary that says `PASS` with a plane that did not run is recorded as `INCOMPLETE`, with a warning saying so. This applied to `devsecops-local.sh` output before today too; the engine's own `audit` recipe, which never has the LLM plane (9b), is what surfaced it. Two tests in `tests/test_correctness.py`; `--security-summary` help text names both producers. `devsecops-local.sh` stays readable until 9e; nothing in CC-Test's `tools/` changed. Agreed with Chien-Wei before any code moved (decided with the maintainer 2026-09-25) | engine | first, because the manifest's `security` block would otherwise lose its source mid-move |
| 9b | recast-cesm gains the LLM-audit scanner doing what `templates/.github/scripts/ai_audit.py` (418 lines) does: diff → structured verdict → SARIF, registered through the engine's `Scanner` contract and added to recast-cesm's `audit-cesm` recipe beside the prompts (`security/adjudicator.py`) and credentials (`security/provider.py`) it already holds. The engine's own `audit` recipe keeps `secret` (gitleaks) and `composition` (syft→grype) only: the maintainer decided on 2026-08-21 that the LLM audit stays out of the public repository (`recast/scan/__init__.py`, module docstring), and the engine and its public edition ship the same scanners | recast-cesm | the one Cyber capability with no home yet other than a CC-Test template |
| 9c | `tools/asan.sh` (64) + `hpc/asan-cam.pbs` (84) move to recast-cesm as the `dynamic.asan` stage the engine roadmap already names; the Derecho module loads and the CAM case setup are site and domain knowledge | recast-cesm | independent of 9b; before 9d so the wrappers have somewhere to point |
| 9d | CC-Test's `tools/`, `hooks/`, `templates/` become thin wrappers that call the engine's `audit` recipe and tools; the drifted `hooks/pre-push` / `tools/install-hooks.sh` copies (34 and 24 lines of diff from the engine's) are resolved in favour of the engine's; `tools/install-config.sh` installs the engine's templates. Users of the hook see no change in behaviour | CC-Test | the gate is in use, verified on Derecho, with real pre-push users: its replacement runs before anything is deleted |
| 9e | Delete the wrappers, `hpc/`, `templates/`, `tools/test-ai-audit.py`, and the `summary.json` reader in `make_manifest.py`; `SECURITY.md` keeps CC-Test's own disclosure policy and points at the engine for the gate's security model; CC-Test README rewritten around D8 | CC-Test | only after 9d has run in place |
| 10 | **DONE 2026-09-25.** `correctness/index_evidence.py` writes `evidence/index.json` beside `evidence/INDEX.md`, both from the manifests under `evidence/<product>/<version>/manifest.json`. The JSON is `{"schema": 1, "source": ..., "records": [...]}`, newest validation first, one record per acceptance record: `product`, `version`, `path` (`<product>/<version>/`), `artifact` {name, repo, commit}, `reference` {model, commit_or_tag}, `cases` {total, passed, ids}, `result`, `security` (the gate status), `evidence_class`, `validated` (the manifest timestamp), `cc_test_commit`. Nothing in it is generated at write time, so two runs over the same records give the same bytes. `index_evidence.py --check` exits 1 if either file is stale or missing, and CI's existing `--check` step in `.github/workflows/verify-evidence.yml` now covers both. The append-only check (invariant 8) already exempts top-level files under `evidence/`, so `index.json` is exempt like `INDEX.md` and `README.md`. The index test in `tests/test_correctness.py` checks `index.json`'s content and that `--check` catches an edited or missing `index.json`. Still to do, in the SciRecast repository and not here: the static page fetching `evidence/index.json` from the CC-Test repository in place of its hand-written result tables | CC-Test | D9; small, any time after step 4 |

## 5. Non-goals

- No change to the Cyber gate's behaviour while it moves; D8 changes who owns the code, not what it does.
- The repository is not renamed. The SciRecast site's links and the schema `$id`s carry the name, and CC-Test still records both a Correctness and a Cyber verdict in every manifest, so "Correctness and Cyber Test" still describes it.
- No committed model output or recordings above tier 1 anywhere.
- No attempt to make the Lean audit cover the JAX or Numba emitters; it is registered as evidence for the path it covers.
- `RecastEngine` (public edition) is not reorganised here; mechanisms landing in Pro follow the existing tier boundary in `docs/tier/`.
