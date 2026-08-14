# Security model

`hpc-devsecops` is a preventive local gate, not a sandbox. Target repositories,
their audit scripts, and `~/.config/hpc-devsecops.env` are trusted local inputs.
The environment file is sourced only when its mode is `0600` or `0400`.

## Gate contract

Blocking mode fails closed. A configured or required scanner must produce
parseable output and an explicit successful status. Missing tools, malformed
SARIF/JSON, unavailable credentials, and scanner execution failures return 2;
security findings return 1; only completed clean checks return 0.

The AI audit is considered configured when the target repository contains
`.github/scripts/ai_audit.py`. If configured, it must report
`invocations[0].executionSuccessful: true`; an absent flag is not success.
Users may explicitly opt out with `--no-ai`.

## Trust and disclosure

Reports can contain source diffs, findings, filenames, and vulnerability data.
They are written beneath `~/audits/hpc-devsecops` (or
`HPC_DEVSECOPS_AUDIT_ROOT`) and must be protected according to the target
repository's disclosure policy. Scanner databases and external AI providers
have their own data-handling requirements.

Report defects in this gate privately to the repository owner. Do not include
live credentials or undisclosed exploit material in an issue.
