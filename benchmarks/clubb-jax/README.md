# clubb-jax — 15 unit-differential benchmarks

One benchmark per summary that [clubb-jax](https://github.com/a85tract/clubb-jax) commits
under `summaries/`, taken from branch `main` at `99c8b22f` (RecastEngine `e3c6717`,
re-gated 2026-09-21). The product is CLUBB_core (larson-group/clubb_release `8ab3902`)
translated to NumPy and ported to JAX by RecastEngine under the `recast-clubb` extension.
Two recipes, two criteria:

- **`translate-clubb`** — the NumPy translation, gated **bit-exact**: `static.rwset` at
  `sampled`, `differential.bitexact` at `bit_exact`, `nan_mask_equal`, and
  `symbolic.notary` reported but not gated.
- **`port-clubb`** — the JAX port, gated at the **ULP tier** (`ulp_tiered`): every dominant
  element (within 1e-3 of the largest in its row) within 32 ULP of the Fortran, every
  element within 1e-12 relative, plus `nan_mask_equal`. Verdicts are taken with
  `--xla_backend_optimization_level=0 --xla_disable_hlo_passes=algsimp`, recorded in each
  file's `case.xla_flags`.

## The cases

| id | recipe | units | what it covers | reference |
|---|---|---|---|---|
| `tier0` | translate-clubb | 14 | the modules that use only `clubb_precision` and `constants_clubb` | sampled (f2py-golden-clubb) |
| `tier1` | translate-clubb | 11 | the modules that take `grid` or the PDF types | sampled |
| `tier2` | translate-clubb | 11 | the modules the step calls; eight replayed, `clip_explicit`, `mixing_length`, `pdf_closure_module` sampled | `output/recorded` (bomex, cgils_s6) + sampled |
| `tier3` | translate-clubb | 1 | `advance_clubb_core_module`, the whole step: 40 steps, 453,700 values | `output/recorded_tier3` (bomex, cgils_s6) |
| `port` | port-clubb | 11 | the whole step and the ten recorded units as JAX kernels | `output/recorded` (bomex, cgils_s6) |
| `cases-more-{numpy,jax}` | both | 13 | arm and dycoms2_rf02_nd under the hybrid-PDF flags | `output/recorded_more` |
| `cases-e3sm-{numpy,jax}` | both | 13 | bomex under upstream's `e3sm_maint32` flags (`l_call_pdf_closure_twice`, trapezoidal rules, cloud cover) | `output/recorded_e3sm` |
| `cases-scalars-{numpy,jax}` | both | 13 | gabls2 with two passive scalars (`sclr_dim = edsclr_dim = 2`) | `output/recorded_scalars` |
| `cases-late-{numpy,jax}` | both | 13 | bomex steps 201-220, where the clippers, hole filler and flux limiter take their data-dependent branches | `output/recorded_late` |
| `cases-multicol-{numpy,jax}` | both | 13 | bomex as four grid columns (`run_scm.py -multicol 4`), the one case with `ngrdcol > 1` | `output/recorded_multicol` |

The recordings are dump-replay: `clubb_standalone` instrumented so every call of a routine
writes its inputs and outputs, built with gfortran 16.1.0 `-O1 -fno-fast-math
-ffp-contract=off`, statistics off, `CLUBB_REAL_TYPE=8`. They are local data under the case's
`output/` (gitignored), not in either repository; each file's `reference.provenance` names
the cases and calls recorded.

## How the files were derived

The `unit_set_equal` list of each file was generated from its summary: every `unit` the
summary holds, spelled as the summary spells it. The `ungated` entries and the `waivers`
were written by hand from the clubb-jax README, section 1 (`git -C ~/agent/cesm/clubb-jax
show main:README.md`), and the waiver numbers checked against each summary's verdict
`detail`. Reasons that apply to several files were written once and are identical in
each.

## Exceptions: `ungated` and `waivers`

Two kinds of exception appear, and they claim different things.

**`ungated`** — on a rule, with a reason. The rule does not judge the unit, because the gate
cannot meaningfully judge it there. The unit is still listed in `unit_set_equal`, so the
gap is visible in the criterion and in the manifest rather than absent from both.

| unit | files | reason |
|---|---|---|
| `new_pdf_main` | `tier1`, all ten `cases-*` | no case reaches it (it needs LES-derived inputs); on sampled inputs its drivers reach their error stop or leave the domain. Not verified anywhere |
| `sponge_layer_damping` | `tier1`, `tier2`, all ten `cases-*` | called from `clubb_driver`, outside the recorded step; its initializer writes only the levels inside the sponge layer and leaves the rest undefined on both sides |
| `new_hybrid_pdf_main` | `tier1`, `cases-{e3sm,scalars,late,multicol}-*` | sampled: the drivers cannot build a reference on generated inputs. Replay: only the hybrid-PDF cases call it. Verified in `tier2` and `cases-more-*` instead |
| `calc_roots` | `tier0` | judged and not bit-exact: 738 of 810 points bit-exact, the other 72 one ULP out, where gfortran's complex division and NumPy's round differently. The reference itself rounds differently, so `bit_exact` is not the question here |
| `new_pdf` | `tier0` | two routines (`calc_setter_var_params`, `calc_coefs_wpxpyp_semiimpl`) have no drawable input: NaN on both sides on every draw. The complex-valued routine is bit-exact |

The ten `cases-*` summaries mark these units `stopped_by: dump-replay` (no recorded call);
`tier1` and `tier2` mark them `stopped_by: differential.bitexact`. `port` and `tier3` ungate
nothing.

**`waivers`** — on `ulp_tiered`, with a bound and a reason. The unit is judged, and accepted
beyond the 32-ULP gate up to the bound. Each waiver is backed by a measurement: moving every
`erf` and `exp` result of the bit-exact reference by one ULP moves its dominant elements by
tens of millions of ULP on the worst recorded samples, so the candidate's residual is the
reference's conditioning, not a translation defect. `max_rel` stays within 1e-12 in every
case.

| file | `advance_clubb_core_module` | `pdf_closure_module` | reference spread under one ULP of erf/exp |
|---|---|---|---|
| `cases-e3sm-jax` | 128 | 128 | 42,613,738 / 17,201,248 ULP |
| `cases-late-jax` | 128 | 192 | 39,092,448 / 39,049,408 ULP |
| `cases-multicol-jax` | 64 | 64 | 44,478,880 / 44,228,480 ULP |

The other two JAX cases (`cases-more-jax`, `cases-scalars-jax`) and `port` pass at 32 ULP
with no waiver.

## Re-evaluating

The summaries live in the case repository, not here. Extract the one to evaluate, then
build a manifest (the invocation is described in `../../correctness/README.md`):

```bash
git -C ~/agent/cesm/clubb-jax show 99c8b22f:summaries/tier0.json > /tmp/tier0.json
correctness/make_manifest.py \
    --case tier0=/tmp/tier0.json \
    --benchmark-dir benchmarks/clubb-jax \
    --artifact-repo ~/agent/cesm/clubb-jax \
    --artifact-commit 99c8b22fab697d5fb5fb14b4bfaa6a2963fed78d \
    --artifact-version unreleased-99c8b22f \
    --outputs-location https://github.com/a85tract/clubb-jax/tree/main/summaries \
    --machine laptop \
    --out evidence/clubb-jax/unreleased-99c8b22f/manifest.json
```

On 2026-09-24 all 15 evaluate PASS (exit 0) against their summaries at `99c8b22f`. As a
negative control, removing `fortran:calendar` from `tier0`'s unit list evaluates FAIL with
the detail `not named by the benchmark: fortran:calendar`. All 15 are filed together as
the acceptance record `evidence/clubb-jax/unreleased-99c8b22f/`.

To re-gate the summaries themselves after an engine change, run `python tools/regate.py
run` in the case repository (`tools/regate/jobs.json` lists the jobs); every file's
`case.notes` says the same.

## What a PASS here claims, and what it does not

A PASS says that every unit in the summary is named here, and that each judged unit met
the rule's gate or its written waiver on the recorded or sampled inputs. It says nothing
about what those inputs never reached. From the case README's "What is not covered":

- `new_pdf_main` and the sponge-layer initializer are not verified anywhere (above).
- Scalars on one case only: gabls2. Every other case ran its scalar paths on empty
  arrays. Hydrometeor terms on one case only (cgils_s6, `hydromet_dim = 6`).
- Several grid columns on one case only (bomex, `-multicol 4`); the developed regime on one
  case only (bomex steps 201-220).
- Not the LAPACK solver path (`penta_solve_method` / `tridiag_solve_method = 1`), not
  SILHS, not the tuner or the unit-test types, and statistics off (`l_stats = .false.`,
  every `stats_*` call a stub).
- Every verdict is open loop: each recorded step starts from the Fortran's state. The
  closed-loop trajectories in the case's `evidence/closed_loop/` are not part of these
  benchmarks.
