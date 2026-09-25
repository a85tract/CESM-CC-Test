# CC-Test — Correctness and Cyber Test

The validation hub for the CESM/CAM modernization effort. It answers two
questions about a modernized model component, and keeps the answers as evidence
somebody else can check:

- **Correctness** — does the port compute the same answer as the Fortran it replaces?
- **Cyber** — has the code been scanned for secrets, known vulnerabilities, and defects?

The two halves are independent tools that meet in one record. A reviewer should
be able to open a single acceptance record and see both verdicts for the same
commit, rather than trusting two separate green checkmarks.

| Half | What it does | Status |
|---|---|---|
| [Correctness](#correctness--does-the-port-compute-the-right-answer) | Compares a candidate run against a reference run and files the result as evidence | **Tools in place.** Schema, comparators, manifest builder and verifier all implemented; benchmarks written for clubb-jax (15) and clm-ml-jax (2); first acceptance record filed (clubb-jax, 15 cases, PASS, security NOT_RUN); `verify-evidence.yml` verifies every record and the index on each pull request and push to main |
| [Cyber](#cyber--the-hpc-devsecops-gate) | Secret scan, SBOM + CVE + VEX, AI code audit, AddressSanitizer | **In use.** Verified on Derecho. Since 2026-09-25 the checks are RecastEngine's `audit` recipe and the scripts here are wrappers over it (step 9d); the sanitizer plane and the AI audit's own script follow once recast-cesm's scanners are merged |

The Cyber half is also usable standalone against any git repository — it does
not depend on anything CESM-specific.

## Repository layout

```
schemas/       what an acceptance record is — JSON Schema + self-test
correctness/   the four tools that produce and check one, plus their shared input adapter
benchmarks/    per-product case definitions and acceptance criteria — clubb-jax (15), clm-ml-jax (2)
evidence/      acceptance records, one per validated version, append-only — one so far (clubb-jax)
tests/         run.sh (Cyber, integration) and test_correctness.py (Correctness, pytest)
docs/          VALIDATION-ARCHITECTURE.md — the plan, ownership, open decisions
               CORRECTNESS-ORGANIZATION.md — which repository owns which part (D7, D8)

tools/         the Cyber gate's entry points: devsecops-local.sh, install-config.sh (wrappers
               over RecastEngine's audit recipe and installer; engine.sh finds the engine),
               install-hooks.sh, asan.sh (not wrapped yet)
templates/     hpc-devsecops's starter .gitleaks.toml / .vex/openvex.json / ai_audit.py;
               install-config.sh installs the engine's templates now, these go with step 9e
hooks/         pre-push: chooses the recipe, then runs the engine's hook
hpc/           asan-cam.pbs
SECURITY.md    the gate's security model, trust boundaries, and disclosure policy
```

---

# Correctness — does the port compute the right answer?

## The constraint that shapes everything

A real validation run is a CESM build plus a multi-year integration on Derecho:
the ifx toolchain, input data, hours of compute, and `/glade` storage. **A GitHub
runner cannot do any of that.** So the work splits in two, and the split is the
reason the rest of the design looks the way it does:

```
Layer 1 — produce evidence          (HPC, offline, PBS or by hand)
  Derecho: run reference + candidate
        → correctness/compare_runpair.py --json
        → make_manifest.py
        → evidence/<product>/<version>/manifest.json
        → pull request into this repository

Layer 2 — verify evidence           (GitHub Actions, every PR, seconds)
  verify_evidence.py: does the manifest validate? does the commit it names
  exist? do the claimed results follow from the declared criteria? has an
  existing record been altered?
```

Layer 2 is everything CI can honestly check, and it is worth checking: it
catches the case where a `VALIDATION.md` says PASS but points at a commit that
stopped being the current code months ago.

## What the evidence has to say

`schemas/evidence-manifest.v1.json` and `schemas/acceptance.v1.json` define the
record. Three things they make impossible to leave implicit:

**Every acceptance rule states whether it gates.** The existing comparator
measures character-variable differences and GPTL timing, but neither affects its
exit code — the real criterion is numeric bit-for-bit only. That was true and
unwritten, so a reader could not tell what a PASS covered. The schema requires a
`gating` flag on every rule and rejects a criteria block in which nothing gates.

**`ERROR` is not `FAIL`.** When the two run directories hold different file sets,
nothing was compared. That is an absent comparison, not a failed one, and the
comparator already exits `2` for it. The schema keeps them distinct.

**A digest records how it was taken.** The numeric md5 is one digest per output
file, over a fixed-format dump of all numeric variables in it — not one per
variable. It is only comparable against a digest taken with the same format
string, so the rule carries `dump_format` and `dump_tool` rather than assuming
them.

Two more, for the cases that come up in practice: `evidence_class` marks a
record as `complete` or `reconstructed`, so a historical run whose compiler
version can no longer be established is recorded honestly instead of having a
plausible value invented for it; and the statistical criteria for Pipeline 2 are
present but marked `provisional`, and the verifier rejects any evidence filed
against them until the tolerance, norm, variable set, and spread test are agreed
(decision D4).

## Status and where to start

The four tools under `correctness/` are implemented. What is still missing is
data, not code: benchmarks exist for clubb-jax (15) and clm-ml-jax (2), and the
first acceptance record is filed as `evidence/clubb-jax/unreleased-99c8b22f/` (15 cases,
all PASS, security `NOT_RUN` because the Cyber gate has not run against that commit).
`.github/workflows/verify-evidence.yml` verifies every record and the index on each pull
request and push to main (migration step 6 of `docs/VALIDATION-ARCHITECTURE.md`, the
`verify-evidence.yml` half). clubb-jax carries the `VALIDATION.md` rendered from that
record and a `validation.yml` that calls `.github/workflows/validation-callable.yml` here
(step 8 of `docs/CORRECTNESS-ORGANIZATION.md`, first product; `correctness/check_validation.py`
renders and checks the file).

| Module | Step | State |
|---|---|---|
| `compare_runpair.py` | 2 | done — the PyCAM5 comparator with `--json`, neutral run-directory options, and the three-valued exit code |
| `make_manifest.py` | 3 | done — comparator JSON + benchmark + environment probe + the Cyber gate's `summary.json` → a manifest |
| `verify_evidence.py` | 3 | done — schema plus all 11 error invariants and 6 warnings from `schemas/README.md` |
| `index_evidence.py` | 4 | done — regenerates `evidence/INDEX.md` and `evidence/index.json` from the manifests; `--check` exits 1 if either is stale or missing |
| `compare_stats.py` | 8 | written, and decision **D4 is still open**. It evaluates both rule kinds under the readings recorded in `docs/VALIDATION-ARCHITECTURE.md` §8.1; the schema keeps its `provisional` marker and the verifier still rejects statistical evidence |
| benchmarks, first acceptance record | 5, 4 | **both done for clubb-jax.** clubb-jax has 15 benchmarks, all PASS in the acceptance record filed 2026-09-24 (`verify_evidence.py`: 0 errors, 1 warning for `NOT_RUN`); clm-ml-jax has 2, blocked until the case commits the engine's schema-1 summary (`benchmarks/clm-ml-jax/README.md`). `verify-evidence.yml` verifies the record on every pull request and push to main (step 6) |

Each tool exits `0` PASS, `1` FAIL, `2` ERROR, and `2` genuinely means *nothing
was compared*: a missing file, a mismatched file set, an unreadable format, an
acceptance rule with no measurement behind it. That distinction is the point —
a stub that returned an empty result, or a tool that reported an absent
comparison as a clean one, would let a caller file a *passing* acceptance record
for a comparison that never ran, which is the failure mode the explicit gating
flags and `ERROR` status exist to prevent.

Read `correctness/README.md` for how the five compose, what they depend on, and
the conventions they share, then `docs/VALIDATION-ARCHITECTURE.md` for the
migration order, the open decisions, and who owns what. Both test suites are
runnable, and neither needs a NetCDF stack:

```bash
python3 -m venv .venv && .venv/bin/pip install numpy jsonschema pyyaml pytest
.venv/bin/python schemas/test_schemas.py          # schema self-test
.venv/bin/python -m pytest tests/test_correctness.py
```

---

# Cyber — the hpc-devsecops gate

A reusable **local** DevSecOps gate for HPC. It runs the same checks as your
cloud CI pipeline — secret scan, SBOM + CVE + VEX, and an LLM code audit — on
your own machine, **before you push**. Catch problems (especially leaked
secrets) while they are still on your login node, not after they reach GitHub.

Built for scientific codebases on HPC (rootless install, no Docker, works
offline), but it is generic — point it at any git repo.

Since 2026-09-25 (step 9d of `docs/CORRECTNESS-ORGANIZATION.md`) the checks
themselves are [RecastEngine](https://github.com/a85tract/RecastEngine)'s `audit`
recipe — the same gitleaks and syft/grype/VEX stages, gating the same way — run
as `recast run audit <repo> --range <range> --gate-summary <out>/summary.json`.
`tools/devsecops-local.sh`, `tools/install-config.sh` and `hooks/pre-push` are
wrappers over the engine's scripts (`tools/engine.sh` finds it), keeping the
flags, the report location and the exit contract below; a user of the pre-push
hook sees no change. What the wrappers add is the choice of recipe: `audit-cesm`,
which carries recast-cesm's LLM audit plane, for a repository that opted into the
AI audit. The engine's `docs/cyber-gate.md` is the handoff: what moved, what was
kept, what was changed on purpose.

## Status

Verified on Derecho (NCAR) as the local + sanitizer half of a three-plane
DevSecOps setup for CAM (the cloud plane — secret + SBOM/CVE + AI audit on every
PR — lives in the target repo's `.github/`):

- **Local gate** — gitleaks, `syft → grype → VEX`, and the Claude AI audit all
  run locally against a repo's own config; a `pre-push` hook blocks pushes on
  findings. Reuses the target repo's `.gitleaks.toml` / `.vex/openvex.json` /
  `.recast-audit.json`, so local and cloud results never drift.
- **Sanitizer plane** — `tools/asan.sh` compiles and runs a Fortran/C reproducer
  under `ifx -fsanitize=address`; confirmed it catches a Fortran
  heap-buffer-overflow with exact `file:line`. `hpc/asan-cam.pbs` scaffolds the
  full-model run.

## Why run it locally first?

- 🔒 **Secrets never leave your machine.** Once a key is pushed it is compromised
  even if you delete it. A local gate stops it before the first `git push`.
- ⚡ **Seconds, not CI minutes.** Fast feedback; no waiting on a runner, no noisy
  red PRs, no burned Actions minutes.
- 🕵️ **Private.** Findings stay on your box — useful for pre-disclosure security
  work.
- 🔧 **Does what the cloud can't.** Run native sanitizers (`ifx -fsanitize=address`)
  that need the real HPC toolchain — see the sanitizer plane below.

## What it checks

It is **config-agnostic**: you point it at a target repo and it reuses *that
repo's own* configuration, so local and cloud never drift.

| Check | Tool | Config it reuses from the target repo |
|---|---|---|
| 🔑 Secret scan | `gitleaks` | `.gitleaks.toml` |
| 📦 SBOM + CVE + VEX | `syft` → `grype` | `.vex/openvex.json` |
| 🤖 AI code audit | recast-cesm's `llm-audit` scanner (Claude), a stage of the `audit-cesm` recipe | opted in by `.github/scripts/ai_audit.py` being present, or `RECAST_AUDIT_RECIPE=audit-cesm` |

Install the configs into a target repo with `tools/install-config.sh <repo>`: the
engine's `.gitleaks.toml`, `.vex/openvex.json` and `.recast-audit.json` (the run
config the hook hands to `recast`). Commit them in the target repo so CI reads the
same config the local gate does. `ai_audit.py` is no longer installed — the audit
is a scanner now — but a repository that still carries it is treated as opted in.

The gate **fails closed**: if a configured or required check does not actually run
(missing tool, unavailable key, malformed output), it reports **INCOMPLETE**, never
`clean` — a finding count of zero from a scan that never happened is not a clean
result. Under `--block` an incomplete gate blocks the push (exit 2); pass
`--require-complete` to block on incompleteness even without `--block`.

## Requirements

Single static binaries in `~/bin` (no root needed):

```bash
# gitleaks, syft, grype — grab the linux_x64 release tarballs into ~/bin
gitleaks version && syft version && grype version
```

And the engine: a RecastEngine checkout with `recast` installed into an
environment that is active when you push (an editable install, `uv pip install -e`,
is what the wrappers expect). `RECAST_BIN` names the executable if it is not on
PATH; `RECAST_HOME` names the checkout if the wrappers cannot derive it from the
executable. A missing engine blocks the push (exit 2), as a missing scanner did.

For the AI audit, install recast-cesm into the same environment (its `llm-audit`
scanner and the `audit-cesm` recipe), and put the key where its provider reads it:
`ANTHROPIC_API_KEY` in the environment, else `~/.config/recast/agent.env` with mode
0600. The login node has outbound network for the API; compute nodes usually do not.

One-time, so `grype` can run offline afterwards:

```bash
grype db update
export GRYPE_DB_AUTO_UPDATE=false
```

## Sanitizer plane — ifx + AddressSanitizer (heap OOB / UAF)

Runtime memory-safety analysis with the **native** Intel compiler. This is the
heavy, on-demand/nightly counterpart to the fast pre-push gate (which uses the
AI audit for Fortran). Verified on Derecho: `ifx 2025.2.1 -fsanitize=address`
catches a Fortran heap-buffer-overflow with exact `file:line`.

Confirm a reproducer / PoC:

```bash
module load intel-oneapi
~/hpc-devsecops/tools/asan.sh mybug.F90            # or several sources, [-- args]
# 🔴 ASan detected a problem:  heap-buffer-overflow ... mybug.F90:7
```

Run the whole model under ASan (heavy — build + run with instrumentation):

```bash
qsub ~/hpc-devsecops/hpc/asan-cam.pbs             # fill the TODOs for your case
```

`hpc/asan-cam.pbs` injects `-fsanitize=address` into FFLAGS/CFLAGS/**LDFLAGS**,
builds a tiny CAM case, and runs it with MPI-aware `ASAN_OPTIONS`
(`detect_leaks=0:halt_on_error=0`) — the CIME `create_newcase` bits are TODOs for
your CAM version. Why not the fast gate? ASan is **dynamic** (must build + run
CAM with inputs) and ~2–3× slower, so it lives here, not in `git push`.

> `-fanalyzer` (GCC static analyzer) was evaluated and dropped: it is GCC-only
> (ifx has no equivalent) and needs a non-native gfortran build with resolved
> `.mod` files. `ifx + ASan` is the native, higher-signal choice for heap OOB.

## Install

```bash
# Clone into ~/hpc-devsecops so all the default paths (venv,
# ~/.config/hpc-devsecops.env, ~/audits/hpc-devsecops) resolve with no extra config.
git clone git@github.com:a85tract/CESM-CC-Test.git ~/hpc-devsecops
# Cloned somewhere else? point the toolkit at it:
#   export HPC_DEVSECOPS_HOME=/path/to/your/checkout
# The engine: see Requirements (RECAST_BIN, RECAST_HOME).
```

## Usage

```bash
# report-only run against a repo
~/hpc-devsecops/tools/devsecops-local.sh ~/cam_cesm2_1_rel

# audit only what you're about to push, and BLOCK on issues
~/hpc-devsecops/tools/devsecops-local.sh --vs-remote --block ~/cam_cesm2_1_rel

# audit an explicit range (what the pre-push hook does)
~/hpc-devsecops/tools/devsecops-local.sh --range origin/main..HEAD --block
```

### Options

| Flag | Meaning |
|---|---|
| `--vs-remote` | audit commits not yet pushed (the default; needs an upstream or `--base`) |
| `--base REF` | base ref for `--vs-remote` (default: the branch upstream) |
| `--range RANGE` | audit an explicit revision range (what the pre-push hook passes) |
| `--block` | fail on findings (exit 1) and fail closed on an incomplete scan (exit 2) |
| `--require-complete` | block on an incomplete gate even without `--block` |
| `--no-ai` | run the `audit` recipe, without the LLM audit plane |
| `--staged`, `--worktree` | **not available**: the engine's secret scan reads history, not a patch; the wrapper refuses them (exit 2) rather than scan something wider than asked |

## Automatic pre-push gate

```bash
~/hpc-devsecops/tools/install-hooks.sh ~/cam_cesm2_1_rel
```

Installs a symlinked `pre-push` hook so `git push` from that repo runs the
engine's audit recipe first and **blocks** the push on findings or an incomplete
scan. The hook here chooses the recipe (`audit`, or `audit-cesm` for a repository
that opted into the AI audit; `RECAST_AUDIT_RECIPE` overrides) and runs the
engine's `tools/pre-push`, which reads Git's actual local/remote SHA pairs,
including new branches and multi-ref pushes, and audits exactly the range each
push would publish. A repository that opted in but whose environment has no
`audit-cesm` is blocked (exit 2), as an unavailable AI audit blocked before, rather
than gated more quietly than it asked for. Emergency bypass: `git push --no-verify`.
Uninstall: `rm <repo>/.git/hooks/pre-push`.

## Output

The gate summary is written under `~/audits/recast/<repo>/<timestamp>-<pid>/`
(`HPC_DEVSECOPS_AUDIT_ROOT` or `RECAST_AUDIT_ROOT`, if set; the hook adds a
`<branch>/` level):

```
summary.json
```

That is the file `correctness/make_manifest.py --security-summary` reads into an
acceptance record: a state and counts per scan and a status `PASS` / `FINDINGS` /
`INCOMPLETE`, never a finding. The findings themselves are records in the engine's
store (`RECAST_FINDINGS_HOME`, default `~/.recast/findings`), where they are
adjudicated before anyone decides on disclosure; the per-scanner raw output
(`gitleaks.sarif`, `grype.json`, the SBOM) is no longer kept beside the summary.
Nothing is written under `/glade/work`. Exit codes:
`0` clean or report-only; `1` findings under `--block`; `2` an incomplete gate
under `--block` / `--require-complete`, or a usage/environment error.

## Notes

- An AI state other than `reviewed` (e.g. `unavailable`, `error`,
  `not_configured`) means the audit did not actually run — **not** the same as
  reviewed-clean, and it makes the gate `INCOMPLETE`.
- Run the AI step on the login node (egress); compute nodes have none.
- The same three static binaries (gitleaks, syft, grype) run in CI and on HPC;
  the only HPC-specific step is pre-staging the grype DB for offline use.

---

# Who owns what

| Area | Owner |
|---|---|
| Correctness framework — schema, structure, contracts | lewisychen |
| Correctness implementation — comparators, manifest builder, verifier, benchmarks | Qinrun |
| Cyber half — `tools/`, `hooks/`, `hpc/`, and the product-repo config | Chien-Wei |

`docs/VALIDATION-ARCHITECTURE.md` §8 tracks the open decisions. One still needs a
person, not more code:

- **D4** — the Pipeline 2 acceptance vocabulary. The ULP family is settled
  (2026-09-24) as the `unit-differential` kind, read from a RecastEngine
  summary. The ensemble-spread family is not: `compare_stats.py` is written, but
  it did not settle it: it states the reading it takes for each
  undecided point (`docs/VALIDATION-ARCHITECTURE.md` §8.1) and those readings
  need confirming or overturning by a person. Until then the schema keeps its
  `provisional` marker and no Pipeline 2 evidence is accepted. The bitwise path
  is unaffected.

**D6** — whether an acceptance record also carries the Cyber gate's verdict for the
same commit — is **resolved: yes.** The manifest carries a required `security`
block; when the gate has not run for that commit its `status` is `NOT_RUN`, so a
record is never silently missing the Cyber half rather than honestly marking it
absent. See `docs/VALIDATION-ARCHITECTURE.md` §11.

**D7** and **D8** — where the whole-model comparator lives, and what CC-Test is —
were settled on 2026-09-24: the comparators move to the engine as `fullmodel.bitwise`,
and CC-Test narrows to its acceptance records and the criteria. `correctness/` is
transitional until migration step 5 of `docs/CORRECTNESS-ORGANIZATION.md` lands.
