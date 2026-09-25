#!/usr/bin/env bash
#
# Install the gate's config files into a target repo.
#
# Usage: install-config.sh [--force] [-h] [TARGET_REPO]   (defaults to the current repo)
#
# This is the engine's tools/install-config.sh (RecastEngine), which it calls;
# step 9d of docs/CORRECTNESS-ORGANIZATION.md. It writes .gitleaks.toml,
# .vex/openvex.json and .recast-audit.json from the engine's templates/. The
# third file hpc-devsecops's installer wrote, .github/scripts/ai_audit.py, is a
# scanner now (recast-cesm's llm-audit) and needs no copy in the target: to
# run it, set RECAST_AUDIT_RECIPE=audit-cesm (or keep the file, which
# hooks/pre-push still reads as the opt-in).

set -euo pipefail
# shellcheck source=tools/engine.sh
. "$(cd "$(dirname "$0")" && pwd)/engine.sh"
home="$(recast_home)" || exit 2
exec "$home/tools/install-config.sh" "$@"
