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
#   --require-complete
#                  exit non-zero if any check did not actually run (a gate with
#                  zero findings but a skipped scan is not a clean result)
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
REQUIRE_COMPLETE=0
DO_AI=1
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --staged)    MODE="staged" ;;
    --worktree)  MODE="worktree" ;;
    --vs-remote) MODE="vs-remote" ;;
    --base)      BASE="$2"; shift ;;
    --block)     BLOCK=1 ;;
    --require-complete) REQUIRE_COMPLETE=1 ;;
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
# Per-scan state. A count of 0 is meaningless without it: "scanned, found
# nothing" and "never ran" both leave the counter at 0, and reporting the
# latter as clean is a false assurance. Same failure the AI audit had before
# it started reading executionSuccessful.
GL_STATE="skipped"; CVE_STATE="skipped"
GL_CFG_USED=0; VEX_USED=0

# ---- 1. secret scan (gitleaks) ---------------------------------------------
if command -v gitleaks >/dev/null 2>&1; then
  GL_CFG=(); [ -f "$REPO/.gitleaks.toml" ] && { GL_CFG=(--config "$REPO/.gitleaks.toml"); GL_CFG_USED=1; }
  if [ "$MODE" = "vs-remote" ]; then
    gitleaks git "$REPO" "${GL_CFG[@]}" --log-opts="${BASE}..HEAD" \
      --report-format sarif --report-path "$OUT/gitleaks.sarif" --exit-code 0 >/dev/null 2>&1
  else
    gitleaks dir "$REPO" "${GL_CFG[@]}" \
      --report-format sarif --report-path "$OUT/gitleaks.sarif" --exit-code 0 >/dev/null 2>&1
  fi
  # A missing or unparsable SARIF means the scan did not complete; do not let
  # the fallback 0 masquerade as a clean result.
  if SECRETS=$(python3 -c "import json;print(len(json.load(open('$OUT/gitleaks.sarif'))['runs'][0]['results']))" 2>/dev/null); then
    GL_STATE="scanned"
    echo "  🔑 gitleaks     : $SECRETS secret finding(s)$([ "$GL_CFG_USED" = 1 ] || echo '  (default rules — no .gitleaks.toml in target)')"
  else
    SECRETS=0; GL_STATE="failed"
    echo "  🔑 gitleaks     : ⚠️ produced no usable report — NOT SCANNED"
  fi
else
  GL_STATE="not_installed"
  echo "  🔑 gitleaks     : ⚠️ not installed — NOT SCANNED"
fi

# ---- 2. SBOM + CVE + VEX (syft -> grype) -----------------------------------
if command -v syft >/dev/null 2>&1 && command -v grype >/dev/null 2>&1; then
  syft scan "dir:$REPO" -o "spdx-json=$OUT/sbom.spdx.json" -q >/dev/null 2>&1
  VEX=(); [ -f "$REPO/.vex/openvex.json" ] && { VEX=(--vex "$REPO/.vex/openvex.json"); VEX_USED=1; }
  if grype "sbom:$OUT/sbom.spdx.json" --add-cpes-if-none "${VEX[@]}" -o json > "$OUT/grype.json" 2>"$OUT/grype.err"; then
    if read -r CVE_CRIT CVE_HIGH < <(python3 -c "
import json
m=json.load(open('$OUT/grype.json')).get('matches',[])
sev=[x['vulnerability']['severity'] for x in m]
print(sev.count('Critical'), sev.count('High'))" 2>/dev/null); then
      CVE_STATE="scanned"
      echo "  📦 grype        : $CVE_CRIT Critical, $CVE_HIGH High CVE(s)$([ "$VEX_USED" = 1 ] || echo '  (no VEX suppression — no .vex/openvex.json in target)')"
    else
      CVE_CRIT=0; CVE_HIGH=0; CVE_STATE="failed"
      echo "  📦 grype        : ⚠️ report unparsable — NOT SCANNED"
    fi
  else
    CVE_STATE="failed"
    echo "  📦 grype        : ⚠️ failed (DB not staged? see $OUT/grype.err) — NOT SCANNED"
  fi
else
  CVE_STATE="not_installed"
  echo "  📦 syft/grype   : ⚠️ not installed — NOT SCANNED"
fi

# ---- 3. AI code audit (reuse the target repo's ai_audit.py) -----------------
# Pick up the API key from an optional 0600 env file if not already exported.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$HOME/.config/hpc-devsecops.env" ]; then
  # shellcheck source=/dev/null
  . "$HOME/.config/hpc-devsecops.env"
fi

AUDIT="$REPO/.github/scripts/ai_audit.py"
# Prefer the hpc-devsecops venv (which has the anthropic SDK) over system python.
PYBIN="${HPC_DEVSECOPS_HOME:-$HOME/hpc-devsecops}/.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN=python3
if [ "$DO_AI" = 1 ] && [ -f "$AUDIT" ]; then
  if ! "$PYBIN" -c "import anthropic" >/dev/null 2>&1; then
    echo "  🤖 ai-audit     : ⚠️ 'anthropic' not installed — run: pip install anthropic"
    AI_STATE="unavailable"
  elif [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "  🤖 ai-audit     : ⚠️ ANTHROPIC_API_KEY not set (login node has egress) — UNREVIEWED"
    AI_STATE="unreviewed"
  else
    ( cd "$OUT" && "$PYBIN" "$AUDIT" "$OUT/pr.diff" >/dev/null 2>&1 )
    if [ -f "$OUT/ai-audit.sarif" ]; then
      # Only trust the audit if the SARIF marks the run successful. ai_audit.py
      # writes the SARIF even on API/parse errors (empty results), so
      # file-existence alone is a FALSE "reviewed" — a 401 would read as clean.
      read -r AI_OK AI_HIGH < <(python3 -c "
import json
r=json.load(open('$OUT/ai-audit.sarif'))['runs'][0]
ok=(r.get('invocations') or [{}])[0].get('executionSuccessful', True)
high=sum(1 for x in r['results'] if x.get('level')=='error')
print(int(bool(ok)), high)" 2>/dev/null || echo "0 0")
      if [ "${AI_OK:-0}" = 1 ]; then
        AI_STATE="reviewed"
        echo "  🤖 ai-audit     : $AI_HIGH high finding(s)  (report: $OUT/ai-audit-report.md)"
      else
        AI_HIGH=0
        AI_STATE="unreviewed"
        echo "  🤖 ai-audit     : ⚠️ did NOT complete (bad key / API error) — UNREVIEWED (see $OUT/ai-audit-report.md)"
      fi
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
  echo "secrets=$SECRETS cve_critical=$CVE_CRIT cve_high=$CVE_HIGH ai_high=$AI_HIGH"
  echo "gitleaks_state=$GL_STATE cve_state=$CVE_STATE ai_state=$AI_STATE"
  echo "gitleaks_config=$GL_CFG_USED vex=$VEX_USED"
} > "$OUT/summary.txt"

FAIL=0
[ "${SECRETS:-0}" -gt 0 ] && FAIL=1
[ "${CVE_CRIT:-0}" -gt 0 ] && FAIL=1
[ "${AI_HIGH:-0}" -gt 0 ] && FAIL=1

# A gate is only complete when every plane actually ran. An incomplete gate with
# zero findings is not a clean result and must never be reported as one.
COMPLETE=1
[ "$GL_STATE"  = "scanned"  ] || COMPLETE=0
[ "$CVE_STATE" = "scanned"  ] || COMPLETE=0
[ "$AI_STATE"  = "reviewed" ] || COMPLETE=0

if [ "$FAIL" = 1 ]; then
  STATUS="FAIL"
elif [ "$COMPLETE" = 1 ]; then
  STATUS="PASS"
else
  STATUS="INCOMPLETE"
fi

# Machine-readable twin of summary.txt. correctness/make_manifest.py reads this
# to fill the `security` block of an evidence manifest, so every field the
# manifest needs must be present here — including the states, without which a
# zero count cannot be told apart from a scan that never ran.
CC_TEST_DIR="$(cd "$(dirname "$0")/.." && pwd)"
GATE_STATUS="$STATUS" GL_STATE="$GL_STATE" CVE_STATE="$CVE_STATE" AI_STATE="$AI_STATE" \
SECRETS="$SECRETS" CVE_CRIT="$CVE_CRIT" CVE_HIGH="$CVE_HIGH" AI_HIGH="$AI_HIGH" \
GL_CFG_USED="$GL_CFG_USED" VEX_USED="$VEX_USED" MODE="$MODE" BASE="${BASE:-}" \
DIFF_LINES="$DIFF_LINES" TS="$TS" REPO_NAME="$REPO_NAME" \
SCANNED_SHA="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)" \
CC_TEST_SHA="$(git -C "$CC_TEST_DIR" rev-parse HEAD 2>/dev/null || echo unknown)" \
GL_VER="$(command -v gitleaks >/dev/null 2>&1 && gitleaks version 2>/dev/null | head -1 || echo '')" \
GRYPE_VER="$(command -v grype >/dev/null 2>&1 && grype version -o json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || echo '')" \
SYFT_VER="$(command -v syft >/dev/null 2>&1 && syft version -o json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || echo '')" \
python3 - "$OUT/summary.json" <<'PY'
import json, os, sys
from datetime import datetime, timezone

def i(name):
    try:
        return int(os.environ.get(name, "0") or 0)
    except ValueError:
        return 0

def iso(compact):
    """20260810T231942Z -> 2026-08-10T23:19:42Z, the form the manifest wants."""
    try:
        return (datetime.strptime(compact, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return compact

doc = {
    "gate": "hpc-devsecops",
    "cc_test_commit": os.environ.get("CC_TEST_SHA", "unknown"),
    "scanned_repo": os.environ.get("REPO_NAME", ""),
    "scanned_commit": os.environ.get("SCANNED_SHA", "unknown"),
    "mode": os.environ.get("MODE", ""),
    "base": os.environ.get("BASE", "") or None,
    "diff_lines": i("DIFF_LINES"),
    "timestamp": iso(os.environ.get("TS", "")),
    "status": os.environ.get("GATE_STATUS", "INCOMPLETE"),
    "scans": {
        "secrets": {
            "tool": "gitleaks",
            "tool_version": os.environ.get("GL_VER", "") or None,
            "state": os.environ.get("GL_STATE", "skipped"),
            "findings": i("SECRETS"),
            "target_config": bool(i("GL_CFG_USED")),
        },
        "vulnerabilities": {
            "tool": "syft -> grype",
            "tool_version": os.environ.get("GRYPE_VER", "") or None,
            "sbom_tool_version": os.environ.get("SYFT_VER", "") or None,
            "state": os.environ.get("CVE_STATE", "skipped"),
            "critical": i("CVE_CRIT"),
            "high": i("CVE_HIGH"),
            "vex_applied": bool(i("VEX_USED")),
        },
        "ai_audit": {
            "tool": "ai_audit.py",
            "state": os.environ.get("AI_STATE", "skipped"),
            "high_findings": i("AI_HIGH"),
        },
    },
}
with open(sys.argv[1], "w") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
PY

if [ "$FAIL" = 1 ]; then
  echo "❌ hpc-devsecops: issues found (secrets=$SECRETS crit=$CVE_CRIT ai_high=$AI_HIGH)"
elif [ "$COMPLETE" = 1 ]; then
  echo "✅ hpc-devsecops: clean — all three planes ran (secrets=0 crit=0 ai_high=0)"
else
  echo "⚠️  hpc-devsecops: INCOMPLETE — no blocking findings, but not every check ran."
  [ "$GL_STATE"  = "scanned"  ] || echo "     secret scan  : $GL_STATE"
  [ "$CVE_STATE" = "scanned"  ] || echo "     CVE scan     : $CVE_STATE"
  [ "$AI_STATE"  = "reviewed" ] || echo "     AI audit     : $AI_STATE"
  echo "     This is NOT the same as reviewed-clean."
fi
echo "   report: $OUT/summary.json"

if [ "$FAIL" = 1 ] && [ "$BLOCK" = 1 ]; then
  echo "   --block set → blocking."
  exit 1
fi
if [ "$COMPLETE" = 0 ] && [ "$REQUIRE_COMPLETE" = 1 ]; then
  echo "   --require-complete set → blocking on an incomplete gate."
  exit 1
fi
[ "$FAIL" = 1 ] && echo "   (report-only; pass --block to gate)"
exit 0
