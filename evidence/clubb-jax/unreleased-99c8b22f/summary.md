# Acceptance record — clubb-jax unreleased-99c8b22f

| | |
|---|---|
| Artifact | `https://github.com/a85tract/clubb-jax` @ `99c8b22f` |
| Reference | CLUBB_core, larson-group/clubb_release, 8ab3902 |
| CC-Test | unreleased-86a46e8c (`86a46e8c`) |
| Machine | macOS-26.5.2-arm64-arm-64bit, Apple-silicon laptop, CPU only |
| Compiler | GNU Fortran (Homebrew GCC 16.1.0) 16.1.0, -O1 -fno-fast-math -ffp-contract=off |
| Cases | 15 |
| Result | **PASS** |
| Security gate | NOT_RUN |
| Evidence class | complete |
| Validated | 2026-09-21T19:44:00Z |

## Cases

### cases-e3sm-jax — PASS

Criteria: `benchmarks/clubb-jax/cases-e3sm-jax.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `ulp_tiered` | yes | yes | worst dominant 128 ULP (fortran:advance_clubb_core_module) vs gate 32; worst max_rel 2.48e-15 (fortran:advance_clubb_core_module) vs 1e-12; waivers applied: fortran:advance_clubb_core_module<=128, fortran:pdf_closure_module<=128; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-e3sm-numpy — PASS

Criteria: `benchmarks/clubb-jax/cases-e3sm-numpy.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-late-jax — PASS

Criteria: `benchmarks/clubb-jax/cases-late-jax.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `ulp_tiered` | yes | yes | worst dominant 192 ULP (fortran:pdf_closure_module) vs gate 32; worst max_rel 4.85e-15 (fortran:advance_clubb_core_module) vs 1e-12; waivers applied: fortran:advance_clubb_core_module<=128, fortran:pdf_closure_module<=192; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-late-numpy — PASS

Criteria: `benchmarks/clubb-jax/cases-late-numpy.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-more-jax — PASS

Criteria: `benchmarks/clubb-jax/cases-more-jax.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_pdf_main, fortran:sponge_layer_damping |
| `ulp_tiered` | yes | yes | worst dominant 32 ULP (fortran:pdf_closure_module) vs gate 32; worst max_rel 1.76e-15 (fortran:advance_clubb_core_module) vs 1e-12; ungated: fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-more-numpy — PASS

Criteria: `benchmarks/clubb-jax/cases-more-numpy.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact; ungated: fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic; ungated: fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-multicol-jax — PASS

Criteria: `benchmarks/clubb-jax/cases-multicol-jax.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `ulp_tiered` | yes | yes | worst dominant 64 ULP (fortran:advance_clubb_core_module) vs gate 32; worst max_rel 6.05e-15 (fortran:advance_clubb_core_module) vs 1e-12; waivers applied: fortran:advance_clubb_core_module<=64, fortran:pdf_closure_module<=64; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-multicol-numpy — PASS

Criteria: `benchmarks/clubb-jax/cases-multicol-numpy.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-scalars-jax — PASS

Criteria: `benchmarks/clubb-jax/cases-scalars-jax.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `ulp_tiered` | yes | yes | worst dominant 32 ULP (fortran:advance_clubb_core_module) vs gate 32; worst max_rel 4.24e-15 (fortran:advance_clubb_core_module) vs 1e-12; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### cases-scalars-numpy — PASS

Criteria: `benchmarks/clubb-jax/cases-scalars-numpy.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 13 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### port — PASS

Criteria: `benchmarks/clubb-jax/port.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 11 units, as the benchmark names them |
| `ulp_tiered` | yes | yes | worst dominant 32 ULP (fortran:advance_clubb_core_module) vs gate 32; worst max_rel 3.19e-15 (fortran:advance_clubb_core_module) vs 1e-12 |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit |

### tier0 — PASS

Criteria: `benchmarks/clubb-jax/tier0.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 14 units, as the benchmark names them; stopped before the gate completed: fortran:calc_roots, fortran:new_pdf |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:bicgstab_solvers); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:bicgstab_solvers); required at least bit_exact; ungated: fortran:calc_roots, fortran:new_pdf |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:calc_roots, fortran:new_pdf |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:bicgstab_solvers); required at least symbolic; ungated: fortran:calc_roots, fortran:new_pdf |

### tier1 — PASS

Criteria: `benchmarks/clubb-jax/tier1.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 11 units, as the benchmark names them; stopped before the gate completed: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_helper_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_helper_module); required at least bit_exact; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_helper_module); required at least symbolic; ungated: fortran:new_hybrid_pdf_main, fortran:new_pdf_main, fortran:sponge_layer_damping |

### tier2 — PASS

Criteria: `benchmarks/clubb-jax/tier2.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 11 units, as the benchmark names them; stopped before the gate completed: fortran:sponge_layer_damping |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_windm_edsclrm_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_windm_edsclrm_module); required at least bit_exact; ungated: fortran:sponge_layer_damping |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit; ungated: fortran:sponge_layer_damping |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_windm_edsclrm_module); required at least symbolic; ungated: fortran:sponge_layer_damping |

### tier3 — PASS

Criteria: `benchmarks/clubb-jax/tier3.yaml` (unit-differential)

| Check | Gating | Passed | Detail |
|---|---|---|---|
| `unit_set_equal` | yes | yes | 1 units, as the benchmark names them |
| `confidence_at_least` | yes | yes | weakest static.rwset is sampled (fortran:advance_clubb_core_module); required at least sampled |
| `confidence_at_least` | yes | yes | weakest differential.bitexact is bit_exact (fortran:advance_clubb_core_module); required at least bit_exact |
| `nan_mask_equal` | yes | yes | non-finite masks agree in every judged unit |
| `confidence_at_least` | no | yes | weakest symbolic.notary is symbolic (fortran:advance_clubb_core_module); required at least symbolic |
