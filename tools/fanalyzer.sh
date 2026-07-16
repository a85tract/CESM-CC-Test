#!/usr/bin/env bash
#
# Best-effort GCC static analysis (-fanalyzer) for Fortran files.
#
# IMPORTANT REALITY: `-fanalyzer` needs a real compile (`-c`), and Fortran `use`
# statements need the referenced modules' *.mod files. So per-file analysis of an
# interdependent codebase like CAM only works if you point it at a module
# directory from a *gfortran* build (Intel/Cray .mod files are NOT compatible).
# Files whose modules can't be resolved are reported as "skipped", not failures —
# they need the full build (see the README's HPC-plane note).
#
# Usage: fanalyzer.sh [-m MODDIR] [-I INCDIR] <file.F90> [more.F90 ...]
#   -m MODDIR   directory of *.mod files from a gfortran build (repeatable via -I)
#
# Exit: 1 if any file produced analyzer warnings, else 0.

set -uo pipefail

INCS=()
while getopts "m:I:" opt; do
  case "$opt" in
    m|I) INCS+=(-I "$OPTARG") ;;
    *) echo "usage: fanalyzer.sh [-m MODDIR] <file.F90> ..." >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

command -v gfortran >/dev/null 2>&1 || { echo "gfortran not found (module load gcc?)"; exit 0; }
[ "$#" -gt 0 ] || { echo "no files given"; exit 0; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
clean=0; warned=0; skipped=0

for f in "$@"; do
  [ -f "$f" ] || { echo "  ⏭️  $f (not found)"; continue; }
  out="$(gfortran -c -fanalyzer -cpp -J "$TMP" "${INCS[@]}" "$f" -o "$TMP/x.o" 2>&1)"
  if echo "$out" | grep -qiE "Cannot open module file|Fatal Error"; then
    skipped=$((skipped + 1))
    echo "  ⏭️  $f (unresolved modules — needs -m from a gfortran build)"
  elif echo "$out" | grep -qiE "\[-Wanalyzer|warning:|error:"; then
    warned=$((warned + 1))
    echo "  ⚠️  $f"
    echo "$out" | grep -iE "warning:|error:|\[-Wanalyzer" | sed 's/^/       /' | head -20
  else
    clean=$((clean + 1))
    echo "  ✅ $f (clean)"
  fi
done

echo "fanalyzer: $clean clean, $warned with findings, $skipped skipped (unresolved modules)"
[ "$warned" -gt 0 ] && exit 1 || exit 0
