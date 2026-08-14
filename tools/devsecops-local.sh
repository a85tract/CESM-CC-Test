#!/usr/bin/env bash
# hpc-devsecops — local DevSecOps gate for HPC.
#
# Usage: devsecops-local.sh [OPTIONS] [TARGET_REPO]
#   --staged       audit the staged patch
#   --worktree     audit tracked worktree changes
#   --vs-remote    audit BASE..HEAD (default when an upstream exists)
#   --base REF     base ref for --vs-remote
#   --range RANGE  audit an explicit Git revision range (used by pre-push)
#   --block        fail on findings and fail closed on scanner errors
#   --no-ai        explicitly disable the optional AI audit
#   -h, --help     show this help

set -uo pipefail

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

die() { echo "hpc-devsecops: $*" >&2; exit 2; }

MODE=""
BASE=""
RANGE=""
BLOCK=0
DO_AI=1
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --staged|--worktree|--vs-remote)
      [ -z "$MODE" ] || die "choose only one audit mode"
      MODE="${1#--}"
      ;;
    --base)
      [ $# -ge 2 ] || die "--base requires a ref"
      BASE="$2"; shift
      ;;
    --range)
      [ $# -ge 2 ] || die "--range requires a Git revision range"
      [ -z "$MODE" ] || die "--range cannot be combined with another audit mode"
      MODE="range"; RANGE="$2"; shift
      ;;
    --block) BLOCK=1 ;;
    --no-ai) DO_AI=0 ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$REPO" ] || die "only one target repo may be supplied"; REPO="$1" ;;
  esac
  shift
done

REPO="${REPO:-$PWD}"
REPO="$(cd "$REPO" 2>/dev/null && pwd)" || die "no such repo: $REPO"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || die "not a git repo: $REPO"

if [ -z "$MODE" ]; then
  if git -C "$REPO" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
    MODE="vs-remote"
  else
    MODE="worktree"
  fi
fi
if [ "$MODE" = "vs-remote" ] && [ -z "$BASE" ]; then
  BASE="$(git -C "$REPO" rev-parse --abbrev-ref '@{u}' 2>/dev/null)"
  [ -n "$BASE" ] || die "no upstream; use --base REF, --range RANGE, or --worktree"
fi
[ -z "$BASE" ] || git -C "$REPO" rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || die "invalid base ref: $BASE"
[ -z "$RANGE" ] || git -C "$REPO" rev-list "$RANGE" --max-count=1 >/dev/null 2>&1 || die "invalid revision range: $RANGE"

REPO_NAME="$(basename "$REPO")"
TS="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT_ROOT="${HPC_DEVSECOPS_AUDIT_ROOT:-$HOME/audits/hpc-devsecops}"
OUT="$OUT_ROOT/$REPO_NAME/$TS"
mkdir -p "$OUT" || die "cannot create report directory: $OUT"

case "$MODE" in
  staged)     git -C "$REPO" diff --cached --binary > "$OUT/pr.diff" || die "cannot create staged diff" ;;
  worktree)   git -C "$REPO" diff HEAD --binary > "$OUT/pr.diff" || die "cannot create worktree diff" ;;
  vs-remote)  git -C "$REPO" diff "$BASE..HEAD" --binary > "$OUT/pr.diff" || die "cannot diff $BASE..HEAD" ;;
  range)      git -C "$REPO" diff "$RANGE" --binary > "$OUT/pr.diff" || die "cannot diff $RANGE" ;;
  *) die "internal error: unsupported mode $MODE" ;;
esac

DIFF_LINES="$(wc -l < "$OUT/pr.diff")"
echo "hpc-devsecops ▸ repo=$REPO mode=$MODE${BASE:+ base=$BASE}${RANGE:+ range=$RANGE}"
echo "          reports → $OUT"
echo

SECRETS=0; CVE_CRIT=0; CVE_HIGH=0; AI_HIGH=0
GL_STATE="unavailable"; CVE_STATE="unavailable"; AI_STATE="skipped"

# Secret scanning is range-aware. Patch modes scan the exact patch through stdin.
if command -v gitleaks >/dev/null 2>&1; then
  GL_CFG=(); [ -f "$REPO/.gitleaks.toml" ] && GL_CFG=(--config "$REPO/.gitleaks.toml")
  if [ "$MODE" = "vs-remote" ] || [ "$MODE" = "range" ]; then
    LOG_RANGE="${RANGE:-$BASE..HEAD}"
    if gitleaks git "$REPO" "${GL_CFG[@]}" --log-opts="$LOG_RANGE" --report-format sarif \
      --report-path "$OUT/gitleaks.sarif" --exit-code 0 >/dev/null 2>"$OUT/gitleaks.err"; then
      GL_STATE="passed"
    else
      GL_STATE="error"
    fi
  elif gitleaks stdin "${GL_CFG[@]}" --report-format sarif \
    --report-path "$OUT/gitleaks.sarif" --exit-code 0 < "$OUT/pr.diff" \
    >/dev/null 2>"$OUT/gitleaks.err"; then
    GL_STATE="passed"
  else
    GL_STATE="error"
  fi
  if [ "$GL_STATE" = "passed" ]; then
    SECRETS="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["runs"][0].get("results", [])))' "$OUT/gitleaks.sarif" 2>/dev/null)" || GL_STATE="error"
    if [ "$GL_STATE" = "passed" ] && [ "$SECRETS" -gt 0 ]; then GL_STATE="findings"; fi
  fi
fi
echo "  gitleaks : $GL_STATE${SECRETS:+ (findings=$SECRETS)}"

# Dependency analysis intentionally describes the resulting repository state,
# rather than only the patch. The summary distinguishes it from diff-scoped scans.
if command -v syft >/dev/null 2>&1 && command -v grype >/dev/null 2>&1; then
  if syft scan "dir:$REPO" -o "spdx-json=$OUT/sbom.spdx.json" -q \
      >/dev/null 2>"$OUT/syft.err" && [ -s "$OUT/sbom.spdx.json" ]; then
    VEX=(); [ -f "$REPO/.vex/openvex.json" ] && VEX=(--vex "$REPO/.vex/openvex.json")
    if grype "sbom:$OUT/sbom.spdx.json" --add-cpes-if-none "${VEX[@]}" \
        -o json > "$OUT/grype.json" 2>"$OUT/grype.err"; then
      COUNTS="$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])).get("matches", []); s=[x.get("vulnerability",{}).get("severity") for x in m]; print(s.count("Critical"),s.count("High"))' "$OUT/grype.json" 2>/dev/null)"
      if read -r CVE_CRIT CVE_HIGH <<< "$COUNTS" && [[ "$CVE_CRIT" =~ ^[0-9]+$ ]] && [[ "$CVE_HIGH" =~ ^[0-9]+$ ]]; then
        CVE_STATE="passed"
        [ "$CVE_CRIT" -gt 0 ] && CVE_STATE="findings"
      else
        CVE_STATE="error"
      fi
    else
      CVE_STATE="error"
    fi
  else
    CVE_STATE="error"
  fi
fi
echo "  syft/grype: $CVE_STATE (Critical=$CVE_CRIT High=$CVE_HIGH; full repository state)"

AUDIT="$REPO/.github/scripts/ai_audit.py"
PYBIN="${HPC_DEVSECOPS_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/.venv/bin/python"
[ -x "$PYBIN" ] || PYBIN=python3
ENV_FILE="$HOME/.config/hpc-devsecops.env"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
  ENV_MODE="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo unknown)"
  case "$ENV_MODE" in
    600|400)
      # shellcheck source=/dev/null
      . "$ENV_FILE"
      ;;
    *) echo "  ai-audit: refusing insecure env file mode $ENV_MODE ($ENV_FILE)" >&2 ;;
  esac
fi

if [ "$DO_AI" = 0 ]; then
  AI_STATE="skipped_by_user"
elif [ ! -f "$AUDIT" ]; then
  AI_STATE="not_configured"
elif ! "$PYBIN" -c 'import anthropic' >/dev/null 2>&1; then
  AI_STATE="unavailable"
elif [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  AI_STATE="unavailable"
else
  if (cd "$OUT" && "$PYBIN" "$AUDIT" "$OUT/pr.diff" >/dev/null 2>"$OUT/ai-audit.err"); then
    :
  fi
  if [ -f "$OUT/ai-audit.sarif" ]; then
    AI_RESULT="$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1]))["runs"][0]; inv=r.get("invocations") or []; ok=bool(inv) and inv[0].get("executionSuccessful") is True; high=sum(x.get("level")=="error" for x in r.get("results",[])); print(int(ok),high)' "$OUT/ai-audit.sarif" 2>/dev/null)"
    if read -r AI_OK AI_HIGH <<< "$AI_RESULT" && [ "${AI_OK:-0}" = 1 ] && [[ "$AI_HIGH" =~ ^[0-9]+$ ]]; then
      AI_STATE="reviewed"
      [ "$AI_HIGH" -gt 0 ] && AI_STATE="findings"
    else
      AI_HIGH=0; AI_STATE="error"
    fi
  else
    AI_STATE="error"
  fi
fi
echo "  ai-audit : $AI_STATE (high=$AI_HIGH)"

FINDINGS=0; ERRORS=0
[ "$GL_STATE" = "findings" ] && FINDINGS=1
[ "$CVE_STATE" = "findings" ] && FINDINGS=1
[ "$AI_STATE" = "findings" ] && FINDINGS=1
case "$GL_STATE" in unavailable|error) ERRORS=1 ;; esac
case "$CVE_STATE" in unavailable|error) ERRORS=1 ;; esac
case "$AI_STATE" in unavailable|error) ERRORS=1 ;; esac

OVERALL="passed"
[ "$FINDINGS" = 1 ] && OVERALL="findings"
[ "$ERRORS" = 1 ] && OVERALL="incomplete"
{
  echo "# hpc-devsecops report — $REPO_NAME @ $TS"
  echo "overall=$OVERALL mode=$MODE base=${BASE:-} range=${RANGE:-} diff_lines=$DIFF_LINES"
  echo "gitleaks_state=$GL_STATE secrets=$SECRETS"
  echo "cve_state=$CVE_STATE cve_scope=full-repository cve_critical=$CVE_CRIT cve_high=$CVE_HIGH"
  echo "ai_state=$AI_STATE ai_high=$AI_HIGH"
} > "$OUT/summary.txt"

echo
if [ "$ERRORS" = 1 ]; then
  echo "INCOMPLETE: one or more configured/required checks did not complete"
  [ "$BLOCK" = 1 ] && exit 2
elif [ "$FINDINGS" = 1 ]; then
  echo "FINDINGS: secrets=$SECRETS critical_cves=$CVE_CRIT ai_high=$AI_HIGH"
  [ "$BLOCK" = 1 ] && exit 1
else
  echo "PASS: all required/configured checks completed with no blocking findings"
fi
exit 0
