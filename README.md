# CC-Test — Correctness and Cyber Test

The validation hub for the CESM/CAM modernization effort. It answers two
questions about a modernized model component, and keeps the answers as evidence
somebody else can check:

- **Correctness** — does the port compute the same answer as the Fortran it replaces?
- **Cyber** — has the code been scanned for secrets, known vulnerabilities, and defects?

The two halves are independent tools that meet in one record. A reviewer should
be able to open a single evidence package and see both verdicts for the same
commit, rather than trusting two separate green checkmarks.

| Half | What it does | Status |
|---|---|---|
| [Correctness](#correctness--does-the-port-compute-the-right-answer) | Compares a candidate run against a reference run and files the result as evidence | **Framework only.** Schema and structure in place; the tools are stubs |
| [Cyber](#cyber--the-hpc-devsecops-gate) | Secret scan, SBOM + CVE + VEX, AI code audit, AddressSanitizer | **In use.** Verified on Derecho |

The Cyber half is also usable standalone against any git repository — it does
not depend on anything CESM-specific.

## Repository layout

```
schemas/       what a validation evidence package is — JSON Schema + self-test
correctness/   the four tools that produce and check one — stubs today
benchmarks/    per-product case definitions and acceptance criteria
evidence/      the append-only index of validated versions
docs/          VALIDATION-ARCHITECTURE.md — the plan, ownership, open decisions

tools/         the Cyber gate: devsecops-local.sh, asan.sh, install-hooks.sh, install-config.sh
templates/     starter .gitleaks.toml / .vex/openvex.json / ai_audit.py for a target repo
hooks/         pre-push
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
  existing package been altered?
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
package as `complete` or `reconstructed`, so a historical run whose compiler
version can no longer be established is recorded honestly instead of having a
plausible value invented for it; and the statistical criteria for Pipeline 2 are
present but marked `provisional`, and the verifier rejects any evidence filed
against them until the tolerance, norm, variable set, and spread test are agreed
(decision D4).

## Status and where to start

Everything under `correctness/` is a **stub**. Each states its inputs, outputs,
and the invariants it must enforce, then raises `NotImplementedError` — a stub
that returned an empty result would let a caller file a *passing* evidence
package for a comparison that never ran, which is the failure mode the explicit
gating flags and `ERROR` status exist to prevent.

| Module | Step | Blocked on |
|---|---|---|
| `compare_runpair.py` | 2 | nothing — port from `PyCAM5/scripts/validation/compare_cesm_runpair.py`, add `--json` |
| `make_manifest.py` | 3 | `compare_runpair.py` |
| `verify_evidence.py` | 3 | nothing — the invariant list is in `schemas/README.md` |
| `compare_stats.py` | 8 | decision D4 |

Read `correctness/README.md` for how the four compose and the conventions they
share, then `docs/VALIDATION-ARCHITECTURE.md` for the migration order, the
open decisions, and who owns what. `schemas/test_schemas.py` is runnable:

```bash
python3 -m venv .venv && .venv/bin/pip install jsonschema
.venv/bin/python schemas/test_schemas.py
```

---

# Cyber — the hpc-devsecops gate

A reusable **local** DevSecOps gate for HPC. It runs the same checks as your
cloud CI pipeline — secret scan, SBOM + CVE + VEX, and an LLM code audit — on
your own machine, **before you push**. Catch problems (especially leaked
secrets) while they are still on your login node, not after they reach GitHub.

Built for scientific codebases on HPC (rootless install, no Docker, works
offline), but it is generic — point it at any git repo.

## Status

Verified on Derecho (NCAR) as the local + sanitizer half of a three-plane
DevSecOps setup for CAM (the cloud plane — secret + SBOM/CVE + AI audit on every
PR — lives in the target repo's `.github/`):

- **Local gate** — gitleaks, `syft → grype → VEX`, and the Claude AI audit all
  run locally against a repo's own config; a `pre-push` hook blocks pushes on
  findings. Reuses the target repo's `.gitleaks.toml` / `.vex/openvex.json` /
  `ai_audit.py`, so local and cloud results never drift.
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
| 🤖 AI code audit | your `ai_audit.py` (Claude) | `.github/scripts/ai_audit.py` |

Install the three configs into a target repo with `tools/install-config.sh <repo>`
— `templates/` holds the versions to start from, including a working `ai_audit.py`.
Commit them in the target repo so CI reads the same config the local gate does.

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

For the AI audit, create a venv with the SDK (the runner auto-detects and uses
`~/hpc-devsecops/.venv`):

```bash
python3 -m venv ~/hpc-devsecops/.venv
~/hpc-devsecops/.venv/bin/pip install anthropic
```

Put the API key in `~/.config/hpc-devsecops.env` (chmod 600) — the runner
auto-sources it, so it works even from a `git push` hook:

```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-...' > ~/.config/hpc-devsecops.env
chmod 600 ~/.config/hpc-devsecops.env
```

The login node has outbound network for the API; compute nodes usually do not.

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
```

## Usage

```bash
# report-only run against a repo
~/hpc-devsecops/tools/devsecops-local.sh ~/cam_cesm2_1_rel

# audit only what you're about to push, and BLOCK on issues
~/hpc-devsecops/tools/devsecops-local.sh --vs-remote --block ~/cam_cesm2_1_rel

# audit staged changes before committing
~/hpc-devsecops/tools/devsecops-local.sh --staged
```

### Options

| Flag | Meaning |
|---|---|
| `--staged` | audit staged changes (`git diff --cached`) |
| `--worktree` | audit all uncommitted changes (`git diff HEAD`) |
| `--vs-remote` | audit commits not yet pushed (default when the branch has an upstream) |
| `--base REF` | base ref for `--vs-remote` (default: the branch upstream) |
| `--block` | fail on findings (exit 1) and fail closed on an incomplete scan (exit 2) |
| `--require-complete` | block on an incomplete gate even without `--block` |
| `--no-ai` | skip the AI code audit |

`--vs-remote` (new commits only) is the quietest mode — it won't re-flag
pre-existing findings. `--worktree` scans everything and is the noisiest.

## Automatic pre-push gate

```bash
~/hpc-devsecops/tools/install-hooks.sh ~/cam_cesm2_1_rel
```

Installs a symlinked `pre-push` hook so `git push` from that repo runs
hpc-devsecops first and **blocks** the push on findings or an incomplete scan.
The hook reads Git's actual local/remote SHA pairs, including new branches and
multi-ref pushes. Emergency bypass: `git push --no-verify`. Uninstall:
`rm <repo>/.git/hooks/pre-push`.

## Output

Reports are written under `~/audits/hpc-devsecops/<repo>/<timestamp>/`:

```
pr.diff            gitleaks.sarif     grype.json     sbom.spdx.json
ai-audit.sarif     ai-audit-report.md summary.txt    summary.json
```

Nothing is written under `/glade/work`. `summary.json` is the machine-readable
mirror of `summary.txt` (status `PASS` / `FINDINGS` / `INCOMPLETE`). Exit codes:
`0` clean or report-only; `1` findings under `--block`; `2` an incomplete gate
under `--block` / `--require-complete`, or a usage/environment error.

## Notes

- An AI state other than `reviewed` (e.g. `unavailable`, `error`,
  `not_configured`) means the audit did not actually run — **not** the same as
  reviewed-clean, and it makes the gate `INCOMPLETE`.
- Run the AI step on the login node (egress), or point the target repo's
  `ai_audit.py` at a local vLLM endpoint for a fully offline gate.
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

- **D4** — the Pipeline 2 statistical acceptance vocabulary. Blocks
  `compare_stats.py` only; the bitwise path is unaffected.

**D6** — whether an evidence package also records the Cyber gate's verdict for the
same commit — is **resolved: yes.** The manifest carries a required `security`
block; when the gate has not run for that commit its `status` is `NOT_RUN`, so a
package is never silently missing the Cyber half rather than honestly marking it
absent. See `docs/VALIDATION-ARCHITECTURE.md` §11.
