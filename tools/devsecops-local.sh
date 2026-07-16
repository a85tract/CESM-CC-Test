#!/usr/bin/env bash
#
# hpc-devsecops — local DevSecOps gate for HPC.
#
# Runs the same checks as the cloud pipeline (secret scan, SBOM+CVE+VEX, AI code
# audit) against a target repo on your machine, BEFORE you push. It reuses the
# TARGET repo's own config (.gitleaks.toml, .vex/openvex.json,
# .github/scripts/ai_audit.py) so local and cloud never drift.
#
# Usage:
#   devsecops-local.sh [OPTIONS] [TARGET_REPO]
#
# Options:
#   --staged       audit staged changes (git diff --cached)
#   --worktree     audit all uncommitted changes (git diff HEAD)
#   --vs-remote    audit commits not yet on the remote (default if upstream set)
#   --base REF     base ref for --vs-remote (default: the branch upstream)
#   --block        exit non-zero if any secret / Critical CVE / high AI finding
#   --no-ai        skip the AI code audit
#   -h, --help     this help
#
# TARGET_REPO defaults to the current directory. Reports are written under
# ~/audits/hpc-devsecops/<repo>/<timestamp>/ (never under /glade/work).

set -uo pipefail

# ---- args -------------------------------------------------------------------
MODE=""            # staged | worktree | vs-remote
BASE=""
BLOCK=0
DO_AI=1
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --staged)    MODE="staged" ;;
    --worktree)  MODE="worktree" ;;
    --vs-remote) MODE="vs-remote" ;;
    --base)      BASE="$2"; shift ;;
    --block)     BLOCK=1 ;;
    --no-ai)     DO_AI=0 ;;
    -h|--help)   sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)          echo "unknown option: $1" >&2; exit 2 ;;
    *)           REPO="$1" ;;
  esac
  shift
done

REPO="${REPO:-$PWD}"
REPO="$(cd "$REPO" && pwd)" || { echo "no such repo: $REPO" >&2; exit 2; }
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repo: $REPO" >&2; exit 2; }

# Default mode: vs-remote if an upstream exists, else worktree.
if [ -z "$MODE" ]; then
  if git -C "$REPO" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then MODE="vs-remote"; else MODE="worktree"; fi
fi
if [ "$MODE" = "vs-remote" ] && [ -z "$BASE" ]; then
  BASE="$(git -C "$REPO" rev-parse --abbrev-ref '@{u}' 2>/dev/null)"
  [ -z "$BASE" ] && { echo "no upstream; use --base REF or --worktree" >&2; exit 2; }
fi

REPO_NAME="$(basename "$REPO")"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$HOME/audits/hpc-devsecops/$REPO_NAME/$TS"
mkdir -p "$OUT"

echo "hpc-devsecops ▸ repo=$REPO  mode=$MODE${BASE:+ base=$BASE}"
echo "          reports → $OUT"
echo

# ---- compute the diff -------------------------------------------------------
case "$MODE" in
  staged)    git -C "$REPO" diff --cached           > "$OUT/pr.diff" ;;
  worktree)  git -C "$REPO" diff HEAD               > "$OUT/pr.diff" ;;
  vs-remote) git -C "$REPO" diff "${BASE}...HEAD"    > "$OUT/pr.diff" ;;
esac
DIFF_LINES=$(wc -l < "$OUT/pr.diff")

SECRETS=0; CVE_CRIT=0; CVE_HIGH=0; AI_HIGH=0; AI_STATE="skipped"

# ---- 1. secret scan (gitleaks) ---------------------------------------------
if command -v gitleaks >/dev/null 2>&1; then
  GL_CFG=(); [ -f "$REPO/.gitleaks.toml" ] && GL_CFG=(--config "$REPO/.gitleaks.toml")
  if [ "$MODE" = "vs-remote" ]; then
    gitleaks git "$REPO" "${GL_CFG[@]}" --log-opts="${BASE}..HEAD" \
      --report-format sarif --report-path "$OUT/gitleaks.sarif" --exit-code 0 >/dev/null 2>&1
  else
    gitleaks dir "$REPO" "${GL_CFG[@]}" \
      --report-format sarif --report-path "$OUT/gitleaks.sarif" --exit-code 0 >/dev/null 2>&1
  fi
  SECRETS=$(python3 -c "import json,sys;print(len(json.load(open('$OUT/gitleaks.sarif'))['runs'][0]['results']))" 2>/dev/null || echo 0)
  echo "  🔑 gitleaks     : $SECRETS secret finding(s)"
else
  echo "  🔑 gitleaks     : ⚠️ not installed (skip)"
fi

# ---- 2. SBOM + CVE + VEX (syft -> grype) -----------------------------------
if command -v syft >/dev/null 2>&1 && command -v grype >/dev/null 2>&1; then
  syft scan "dir:$REPO" -o "spdx-json=$OUT/sbom.spdx.json" -q >/dev/null 2>&1
  VEX=(); [ -f "$REPO/.vex/openvex.json" ] && VEX=(--vex "$REPO/.vex/openvex.json")
  if grype "sbom:$OUT/sbom.spdx.json" --add-cpes-if-none "${VEX[@]}" -o json > "$OUT/grype.json" 2>"$OUT/grype.err"; then
    read -r CVE_CRIT CVE_HIGH < <(python3 -c "
import json
m=json.load(open('$OUT/grype.json')).get('matches',[])
sev=[x['vulnerability']['severity'] for x in m]
print(sev.count('Critical'), sev.count('High'))" 2>/dev/null || echo "0 0")
    echo "  📦 grype        : $CVE_CRIT Critical, $CVE_HIGH High CVE(s)"
  else
    echo "  📦 grype        : ⚠️ failed (DB not staged? see $OUT/grype.err)"
  fi
else
  echo "  📦 syft/grype   : ⚠️ not installed (skip)"
fi

# ---- 3. AI code audit (reuse the target repo's ai_audit.py) -----------------
AUDIT="$REPO/.github/scripts/ai_audit.py"
if [ "$DO_AI" = 1 ] && [ -f "$AUDIT" ]; then
  if ! python3 -c "import anthropic" >/dev/null 2>&1; then
    echo "  🤖 ai-audit     : ⚠️ 'anthropic' not installed — run: pip install anthropic"
    AI_STATE="unavailable"
  elif [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  🤖 ai-audit     : ⚠️ ANTHROPIC_API_KEY not set (login node has egress) — UNREVIEWED"
    AI_STATE="unreviewed"
  else
    ( cd "$OUT" && python3 "$AUDIT" "$OUT/pr.diff" >/dev/null 2>&1 )
    if [ -f "$OUT/ai-audit.sarif" ]; then
      AI_HIGH=$(python3 -c "import json;print(sum(1 for r in json.load(open('$OUT/ai-audit.sarif'))['runs'][0]['results'] if r.get('level')=='error'))" 2>/dev/null || echo 0)
      AI_STATE="reviewed"
      echo "  🤖 ai-audit     : $AI_HIGH high finding(s)  (report: $OUT/ai-audit-report.md)"
    else
      echo "  🤖 ai-audit     : ⚠️ produced no output"
      AI_STATE="error"
    fi
  fi
elif [ "$DO_AI" = 0 ]; then
  echo "  🤖 ai-audit     : skipped (--no-ai)"
else
  echo "  🤖 ai-audit     : ⚠️ $AUDIT not found in target repo (skip)"
fi

# ---- verdict ----------------------------------------------------------------
echo
{
  echo "# hpc-devsecops report — $REPO_NAME @ $TS"
  echo "mode=$MODE base=${BASE:-} diff_lines=$DIFF_LINES"
  echo "secrets=$SECRETS cve_critical=$CVE_CRIT cve_high=$CVE_HIGH ai_high=$AI_HIGH ai_state=$AI_STATE"
} > "$OUT/summary.txt"

FAIL=0
[ "${SECRETS:-0}" -gt 0 ] && FAIL=1
[ "${CVE_CRIT:-0}" -gt 0 ] && FAIL=1
[ "${AI_HIGH:-0}" -gt 0 ] && FAIL=1

if [ "$FAIL" = 1 ]; then
  echo "❌ hpc-devsecops: issues found (secrets=$SECRETS crit=$CVE_CRIT ai_high=$AI_HIGH)"
  [ "$BLOCK" = 1 ] && { echo "   --block set → blocking."; exit 1; }
  echo "   (report-only; pass --block to gate)"
else
  echo "✅ hpc-devsecops: clean (secrets=0 crit=0 ai_high=0, ai_state=$AI_STATE)"
  [ "$AI_STATE" = "unreviewed" ] || [ "$AI_STATE" = "unavailable" ] && echo "   ⚠️ note: AI audit did not run — not the same as reviewed-clean."
fi
exit 0
