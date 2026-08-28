#!/usr/bin/env bash
#
# Install the hpc-devsecops config files into a target repo.
#
# Usage: install-config.sh [OPTIONS] [TARGET_REPO]   (defaults to the current repo)
#
# Options:
#   --force    overwrite files that already exist
#   -h, --help this help
#
# Installs three files the gate looks for in the TARGET repo:
#
#   .gitleaks.toml               secret-scan rules and allowlist
#   .vex/openvex.json            CVE suppressions (starts empty)
#   .github/scripts/ai_audit.py  the Claude code auditor
#
# Without them each check degrades quietly: gitleaks falls back to default
# rules with no project allowlist, grype reports every CVE with no way to mark
# one not-affected, and the AI audit is skipped entirely. Copies are real files,
# not symlinks, because the target repo has to commit them so CI sees the same
# config the local gate does — and because each repo should be free to tune its
# own rules.

set -euo pipefail

FORCE=0
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --force)   FORCE=1 ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)        echo "unknown option: $1" >&2; exit 2 ;;
    *)         REPO="$1" ;;
  esac
  shift
done

REPO="${REPO:-$PWD}"
REPO="$(cd "$REPO" && git rev-parse --show-toplevel)"
SELF="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$SELF/templates"

echo "hpc-devsecops ▸ installing config into $REPO"
echo

INSTALLED=0
SKIPPED=0

install_one() {
  local rel="$1"
  local from="$SRC/$rel"
  local to="$REPO/$rel"

  if [ -e "$to" ] && [ "$FORCE" != 1 ]; then
    echo "  ⏭  $rel already exists (use --force to overwrite)"
    SKIPPED=$((SKIPPED + 1))
    return
  fi

  mkdir -p "$(dirname "$to")"
  cp "$from" "$to"
  echo "  ✅ $rel"
  INSTALLED=$((INSTALLED + 1))
}

install_one ".gitleaks.toml"
install_one ".vex/openvex.json"
install_one ".github/scripts/ai_audit.py"
chmod +x "$REPO/.github/scripts/ai_audit.py" 2>/dev/null || true

echo
echo "installed=$INSTALLED skipped=$SKIPPED"
echo
echo "Next:"
echo "  1. Commit these files — CI reads the same config the local gate does."
echo "  2. .vex/openvex.json ships with no statements, so it suppresses nothing"
echo "     yet. Add one statement per CVE you have assessed; an empty document"
echo "     means every finding is reported, which is the safe default."
echo "  3. Tune .gitleaks.toml against a full-history scan before trusting it:"
echo "       gitleaks dir \"$REPO\" --config \"$REPO/.gitleaks.toml\""
echo "  4. The AI audit needs ANTHROPIC_API_KEY and the 'anthropic' package."
echo "     Verify it end to end from a login node (compute nodes have no egress):"
echo "       cd \"$REPO\" && git diff HEAD > /tmp/pr.diff"
echo "       (cd /tmp && python3 \"$REPO/.github/scripts/ai_audit.py\" /tmp/pr.diff)"
echo "       python3 -c \"import json;print(json.load(open('/tmp/ai-audit.sarif'))['runs'][0]['invocations'][0])\""
