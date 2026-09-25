#!/usr/bin/env bash
# hpc-devsecops — local DevSecOps gate for HPC; the checks are RecastEngine's audit recipe.
#
# Usage: devsecops-local.sh [OPTIONS] [TARGET_REPO]
#   --vs-remote    audit BASE..HEAD (the default; needs an upstream or --base)
#   --base REF     base ref for --vs-remote
#   --range RANGE  audit an explicit Git revision range (used by pre-push)
#   --block        fail on findings and fail closed on scanner errors
#   --require-complete  block when any configured scan did not run (even without --block)
#   --no-ai        run the audit recipe without the LLM audit plane
#   --staged, --worktree  not available: the engine's secret scan reads history, not a patch
#   -h, --help     show this help
#
# What ran here -- gitleaks, syft/grype with VEX, the AI audit -- runs as
# `recast run <recipe> <repo> --range <range> --gate-summary <out>/summary.json`
# (step 9d of docs/CORRECTNESS-ORGANIZATION.md; RecastEngine's docs/cyber-gate.md
# is the handoff). The recipe is `audit`, or `audit-cesm` for a repository that
# opted into the AI audit (tools/engine.sh). The flags, the report directory
# and the exit contract are what they were: 0 clean or report-only, 1
# findings under --block, 2 an incomplete gate under --block /
# --require-complete or a usage or environment error. summary.json is the
# same file, written by the engine.

set -uo pipefail

usage() {
  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
}

die() { echo "hpc-devsecops: $*" >&2; exit 2; }

# shellcheck source=tools/engine.sh
. "$(cd "$(dirname "$0")" && pwd)/engine.sh"

MODE=""
BASE=""
RANGE=""
BLOCK=0
REQUIRE_COMPLETE=0
DO_AI=1
REPO=""

while [ $# -gt 0 ]; do
  case "$1" in
    --vs-remote)
      [ -z "$MODE" ] || die "choose only one audit mode"
      MODE="vs-remote"
      ;;
    --staged|--worktree)
      die "$1 is not available: the engine's secret scan reads history, not a patch; use --vs-remote, --base REF or --range RANGE"
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
    --require-complete) REQUIRE_COMPLETE=1 ;;
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

[ -n "$MODE" ] || MODE="vs-remote"
if [ "$MODE" = "vs-remote" ]; then
  if [ -z "$BASE" ]; then
    BASE="$(git -C "$REPO" rev-parse --abbrev-ref '@{u}' 2>/dev/null)" || die "no upstream; use --base REF or --range RANGE"
  fi
  git -C "$REPO" rev-parse --verify "$BASE^{commit}" >/dev/null 2>&1 || die "invalid base ref: $BASE"
  RANGE="$BASE..HEAD"
fi
git -C "$REPO" rev-list "$RANGE" --max-count=1 >/dev/null 2>&1 || die "invalid revision range: $RANGE"

REPO_NAME="$(basename "$REPO")"
TS="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT_ROOT="${HPC_DEVSECOPS_AUDIT_ROOT:-${RECAST_AUDIT_ROOT:-$HOME/audits/recast}}"
OUT="$OUT_ROOT/$REPO_NAME/$TS"
mkdir -p "$OUT" || die "cannot create report directory: $OUT"

# The exit contract. 2 is "the gate did not complete", and it blocks only
# when asked to; a report-only run says INCOMPLETE and exits 0, as before.
finish() {
  echo
  case "$1" in
    0) echo "PASS: all required/configured checks completed with no blocking findings" ;;
    1) echo "FINDINGS: see the engine's report above; findings are in its store, not in $OUT"
       [ "$BLOCK" = 1 ] && exit 1 ;;
    *) echo "INCOMPLETE: one or more configured/required checks did not complete"
       { [ "$BLOCK" = 1 ] || [ "$REQUIRE_COMPLETE" = 1 ]; } && exit 2 ;;
  esac
  exit 0
}

RECAST="$(recast_bin)" || finish 2
if [ "$DO_AI" = 0 ]; then
  RECIPE="audit"
else
  RECIPE="$(audit_recipe "$REPO")" || finish 2
fi
CONFIG=(); [ -f "$REPO/.recast-audit.json" ] && CONFIG=(--config "$REPO/.recast-audit.json")

echo "hpc-devsecops ▸ repo=$REPO mode=$MODE${BASE:+ base=$BASE} range=$RANGE recipe=$RECIPE"
echo "          reports → $OUT"
echo
"$RECAST" run "$RECIPE" "$REPO" --range "$RANGE" ${CONFIG[@]+"${CONFIG[@]}"} --gate-summary "$OUT/summary.json"
rc=$?
case "$rc" in 0|1|2) ;; *) rc=2 ;; esac
[ -f "$OUT/summary.json" ] || { echo "hpc-devsecops: no summary.json was written" >&2; rc=2; }
finish "$rc"
