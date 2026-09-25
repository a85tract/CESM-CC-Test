#!/usr/bin/env bash
#
# Install CC-Test's pre-push hook into a target repo.
#
# Usage: install-hooks.sh [--force] [TARGET_REPO]
#
# The hook is symlinked, so updating this checkout updates the hook everywhere.
# Uninstall: rm <repo>/.git/hooks/pre-push
#
# Deliberately not a wrapper over the engine's tools/install-hooks.sh: that
# one installs the engine's hook, which runs a fixed recipe. This installs
# hooks/pre-push here, which runs the engine's hook after choosing the recipe
# for the repository (audit, or audit-cesm with the LLM audit plane; see
# tools/engine.sh). Same script otherwise, including the refusal to overwrite
# a hook that is not ours without --force.

set -euo pipefail

FORCE=0
if [ "${1:-}" = "--force" ]; then FORCE=1; shift; fi
[ $# -le 1 ] || { echo "usage: install-hooks.sh [--force] [TARGET_REPO]" >&2; exit 2; }
REPO="${1:-$PWD}"
REPO="$(cd "$REPO" && git rev-parse --show-toplevel)"
HOOKS_DIR="$(git -C "$REPO" rev-parse --absolute-git-dir)/hooks"
SELF="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOOKS_DIR/pre-push"

mkdir -p "$HOOKS_DIR"
if [ -e "$DEST" ] || [ -L "$DEST" ]; then
  current="$(readlink -f "$DEST" 2>/dev/null || true)"
  desired="$(readlink -f "$SELF/hooks/pre-push")"
  if [ "$current" != "$desired" ] && [ "$FORCE" -ne 1 ]; then
    echo "refusing to overwrite existing hook: $DEST" >&2
    echo "Re-run with --force after reviewing the existing hook." >&2
    exit 2
  fi
fi
ln -sfn "$SELF/hooks/pre-push" "$DEST" 2>/dev/null || {
  [ "$FORCE" -eq 1 ] || { echo "cannot symlink hook; use --force to install a copy" >&2; exit 2; }
  cp "$SELF/hooks/pre-push" "$DEST"
}
chmod +x "$SELF/hooks/pre-push" "$DEST" 2>/dev/null || true

echo "✅ installed pre-push hook → $DEST"
echo "   now 'git push' from $REPO runs the recast audit gate first and blocks on issues."
