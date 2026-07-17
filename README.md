# hpc-devsecops

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

If a config or tool is missing, that check is skipped with a warning — never a
hard error.

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
# The org repo is named `devsecops`; the toolkit installs as `hpc-devsecops` by
# convention, so all the default paths (venv, ~/.config/hpc-devsecops.env,
# ~/audits/hpc-devsecops) resolve without extra config. Clone into that dir:
git clone git@github.com:a85tract/devsecops.git ~/hpc-devsecops
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
| `--block` | exit non-zero on any secret / Critical CVE / high AI finding |
| `--no-ai` | skip the AI code audit |

`--vs-remote` (new commits only) is the quietest mode — it won't re-flag
pre-existing findings. `--worktree` scans everything and is the noisiest.

## Automatic pre-push gate

```bash
~/hpc-devsecops/tools/install-hooks.sh ~/cam_cesm2_1_rel
```

Installs a symlinked `pre-push` hook so `git push` from that repo runs
hpc-devsecops first and **blocks** the push on findings. Emergency bypass:
`git push --no-verify`. Uninstall: `rm <repo>/.git/hooks/pre-push`.

## Output

Reports are written under `~/audits/hpc-devsecops/<repo>/<timestamp>/`:

```
pr.diff            gitleaks.sarif     grype.json     sbom.spdx.json
ai-audit.sarif     ai-audit-report.md summary.txt
```

Nothing is written under `/glade/work`. Exit code is `0` unless `--block` is set
and an issue is found (then `1`).

## Notes

- A `⚠️ UNREVIEWED` note means the AI audit did not actually run (missing key or
  SDK) — that is **not** the same as reviewed-clean.
- Run the AI step on the login node (egress), or point the target repo's
  `ai_audit.py` at a local vLLM endpoint for a fully offline gate.
- The same three static binaries (gitleaks, syft, grype) run in CI and on HPC;
  the only HPC-specific step is pre-staging the grype DB for offline use.
