# shellcheck shell=bash
# Where the engine is. Sourced by the wrappers in this directory and by
# hooks/pre-push; not a command.
#
# The gate's implementation is RecastEngine's: the `audit` recipe,
# tools/pre-push, tools/install-config.sh and templates/ there (its
# docs/cyber-gate.md is the handoff). What is here finds it. Two things are
# needed: the `recast` executable (RECAST_BIN, else `recast` on PATH) and,
# for the hook and the installers, the checkout it came from (RECAST_HOME,
# else derived from the executable: an editable install's src/recast is two
# levels under the checkout). Either missing is exit 2 -- the gate's
# "could not run", never a pass.

recast_bin() {
  local bin="${RECAST_BIN:-recast}"
  command -v "$bin" >/dev/null 2>&1 || {
    echo "cc-test: '$bin' not found; activate the environment that has recast, or set RECAST_BIN" >&2
    return 2
  }
  command -v "$bin"
}

recast_home() {
  local home="${RECAST_HOME:-}" bin py
  if [ -z "$home" ]; then
    bin="$(recast_bin)" || return 2
    py="$(dirname "$bin")/python"
    [ -x "$py" ] || py=python3
    home="$("$py" -c 'import pathlib, recast; print(pathlib.Path(recast.__file__).resolve().parents[2])' 2>/dev/null)"
  fi
  if [ ! -x "$home/tools/pre-push" ]; then
    echo "cc-test: RecastEngine checkout not found${home:+ at $home} (no tools/pre-push there); set RECAST_HOME" >&2
    return 2
  fi
  printf '%s\n' "$home"
}

# The recipe the gate runs for a repository. RECAST_AUDIT_RECIPE names it
# outright. Otherwise: `audit-cesm` -- the engine's audit plus recast-cesm's
# LLM audit plane -- for a repository that opted into the AI audit the
# hpc-devsecops way, by carrying .github/scripts/ai_audit.py; `audit` for
# any other. A repository that opted in but whose environment has no
# `audit-cesm` gets exit 2, as an unavailable AI audit made the gate
# INCOMPLETE before, rather than a quieter gate than it asked for.
audit_recipe() {
  local repo="$1" bin
  if [ -n "${RECAST_AUDIT_RECIPE:-}" ]; then printf '%s\n' "$RECAST_AUDIT_RECIPE"; return 0; fi
  if [ -f "$repo/.github/scripts/ai_audit.py" ]; then
    bin="$(recast_bin)" || return 2
    if "$bin" recipes 2>/dev/null | awk '{print $1}' | grep -qx audit-cesm; then
      echo audit-cesm
      return 0
    fi
    echo "cc-test: $repo opted into the AI audit (.github/scripts/ai_audit.py) but the 'audit-cesm' recipe is not installed here; install recast-cesm, or set RECAST_AUDIT_RECIPE=audit to run without it" >&2
    return 2
  fi
  echo audit
}
