#!/usr/bin/env bash
#
# Run a Fortran/C reproducer under ifx/icx + AddressSanitizer.
#
# Compiles the given source(s) with `-fsanitize=address -g`, runs the result,
# and reports any heap-buffer-overflow / use-after-free / etc. with exact
# file:line — the gold standard for confirming a heap-OOB finding. Best for
# self-contained reproducers/PoCs; for the full model see hpc/asan-cam.pbs.
#
# Usage: asan.sh <src.f90|src.c> [more-src ...] [-- program-args]
# Exit:  1 if ASan reports a problem (or the build fails), else 0.

set -uo pipefail

SRCS=(); ARGS=(); dd=0
for a in "$@"; do
  if [ "$dd" = 1 ]; then ARGS+=("$a")
  elif [ "$a" = "--" ]; then dd=1
  else SRCS+=("$a"); fi
done
[ "${#SRCS[@]}" -gt 0 ] || { echo "usage: asan.sh <src...> [-- args]"; exit 2; }

# Pick the compiler: ifx if any Fortran source, else icx for pure C.
has_f=0; has_c=0
for s in "${SRCS[@]}"; do
  [ -f "$s" ] || { echo "source not found: $s" >&2; exit 2; }
  case "${s,,}" in
    *.f90|*.f|*.f95|*.f03|*.f08|*.ftn|*.fpp) has_f=1 ;;
    *.c) has_c=1 ;;
    *) echo "unsupported source type: $s" >&2; exit 2 ;;
  esac
done
COMP=ifx
[ "$has_f" = 0 ] && [ "$has_c" = 1 ] && COMP=icx
command -v "$COMP" >/dev/null 2>&1 || { echo "no $COMP — module load intel-oneapi (or intel)" >&2; exit 2; }

TS="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUT_ROOT="${HPC_DEVSECOPS_AUDIT_ROOT:-$HOME/audits/hpc-devsecops}"
OUT="$OUT_ROOT/asan/$TS"
mkdir -p "$OUT" || { echo "cannot create report directory: $OUT" >&2; exit 2; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
EXE="$TMP/asan_exe"

echo "▸ compiling with $COMP -fsanitize=address -g -O1 ..."
if ! "$COMP" -g -O1 -fsanitize=address "${SRCS[@]}" -o "$EXE" 2>"$OUT/build.log"; then
  echo "❌ build failed (log: $OUT/build.log):"; sed -n '1,80p' "$OUT/build.log"; exit 2
fi

echo "▸ running under AddressSanitizer ..."
# detect_leaks=0: leak reports are mostly noise here; halt_on_error=0: see them all.
ASAN_OPTIONS="${ASAN_OPTIONS:-detect_leaks=0:halt_on_error=0}" "$EXE" "${ARGS[@]}" >"$OUT/run.out" 2>"$OUT/run.err"
rc=$?

if grep -qiE "AddressSanitizer:|runtime error:" "$OUT/run.err"; then
  echo "🔴 ASan detected a problem:"
  grep -iE "ERROR:|SUMMARY:|runtime error:|#[0-9]+ |\.(f90|f|c):[0-9]+" "$OUT/run.err" | head -30
  echo "reports: $OUT"
  exit 1
fi
if [ "$rc" -ne 0 ]; then
  echo "❌ program exited $rc without a recognized ASan report (logs: $OUT)" >&2
  exit "$rc"
fi
echo "✅ no ASan error (reports: $OUT)"
