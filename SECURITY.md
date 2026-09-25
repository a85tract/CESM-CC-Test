# Security model

`hpc-devsecops` is a preventive local gate, not a sandbox. Since 2026-09-25 its
checks are RecastEngine's `audit` recipe and the scripts here are wrappers over
it; the engine's `SECURITY.md` and `docs/cyber-gate.md` are the gate's security
model, this file is CC-Test's own. Target repositories and their run config
(`.recast-audit.json`, `.gitleaks.toml`, `.vex/openvex.json`) are trusted local
inputs. The LLM audit's key is read by recast-cesm's provider: `ANTHROPIC_API_KEY`
in the environment, else `~/.config/recast/agent.env` only when its mode is `0600`.

## Gate contract

Blocking mode fails closed. A configured or required scanner must produce
parseable output and an explicit successful status. Missing tools, malformed
SARIF/JSON, unavailable credentials, and scanner execution failures return 2;
security findings return 1; only completed clean checks return 0.

The AI audit runs when the recipe is `audit-cesm`: chosen by the wrappers for a
target repository that contains `.github/scripts/ai_audit.py` (hpc-devsecops's
opt-in, still honoured), or named by `RECAST_AUDIT_RECIPE`. A repository that
opted in but whose environment lacks that recipe is INCOMPLETE, not quietly
gated without it. Users may explicitly opt out with `--no-ai`.

## Trust and disclosure

Reports can contain source diffs, findings, filenames, and vulnerability data.
The gate summary is written beneath `~/audits/recast` (or
`HPC_DEVSECOPS_AUDIT_ROOT` / `RECAST_AUDIT_ROOT`) and carries states and counts
only; the findings are in the engine's store (`RECAST_FINDINGS_HOME`) and must be
protected according to the target repository's disclosure policy. Scanner databases and external AI providers
have their own data-handling requirements.

Report defects in this gate privately to the repository owner. Do not include
live credentials or undisclosed exploit material in an issue.
