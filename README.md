# hpc-devsecops

A reusable **local** DevSecOps gate for HPC. It runs the same checks as the cloud
CI pipeline — secret scan, SBOM + CVE + VEX, and the Claude AI code audit — on
your machine, **before you push**. Catch problems (especially leaked secrets)
while they are still on your laptop/login node, not after they hit GitHub.

It is **generic**: point it at any target repo and it reuses *that repo's own*
config, so local and cloud never drift:

| Check | Uses from the target repo |
|---|---|
| 🔑 secret scan (gitleaks) | `.gitleaks.toml` |
| 📦 SBOM + CVE (syft → grype) | `.vex/openvex.json` |
| 🤖 AI code audit (Claude) | `.github/scripts/ai_audit.py` |

## Requirements

Single static binaries in `~/bin` (no root): `gitleaks`, `syft`, `grype`.
For the AI audit: `pip install anthropic` and `export ANTHROPIC_API_KEY=...`
(the login node has outbound network; compute nodes do not).

One-time, so grype can run offline later:

```bash
grype db update        # then export GRYPE_DB_AUTO_UPDATE=false
```

## Usage

```bash
# manual run against a repo (report-only)
~/hpc-devsecops/tools/devsecops-local.sh ~/cam_cesm2_1_rel

# audit only what you're about to push, and BLOCK on issues
~/hpc-devsecops/tools/devsecops-local.sh --vs-remote --block ~/cam_cesm2_1_rel

# audit staged changes before committing
~/hpc-devsecops/tools/devsecops-local.sh --staged
```

Modes: `--staged` (staged), `--worktree` (all uncommitted), `--vs-remote`
(commits not yet pushed — the default when the branch has an upstream).
Add `--block` to exit non-zero on any secret / Critical CVE / high AI finding.
`--no-ai` skips the AI audit.

Reports are written under `~/audits/hpc-devsecops/<repo>/<timestamp>/`
(`pr.diff`, `gitleaks.sarif`, `grype.json`, `ai-audit.sarif`,
`ai-audit-report.md`, `summary.txt`). Nothing is written under `/glade/work`.

## Make it automatic (pre-push hook)

```bash
~/hpc-devsecops/tools/install-hooks.sh ~/cam_cesm2_1_rel
```

Now `git push` from that repo runs hpc-devsecops first and **blocks** the push
if it finds secrets / Critical CVEs / high AI findings. Emergency bypass:
`git push --no-verify`.

## Notes

- The AI audit needs network + `ANTHROPIC_API_KEY`. Run it on the login node, or
  point the target repo's `ai_audit.py` at a local vLLM endpoint for a fully
  offline gate.
- A `⚠️ UNREVIEWED` note means the AI audit did not actually run (missing key /
  SDK) — that is **not** the same as reviewed-clean.
