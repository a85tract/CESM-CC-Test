#!/usr/bin/env bash
#
# Install the hpc-devsecops pre-push hook into a target repo.
#
# Usage: install-hooks.sh [TARGET_REPO]     (defaults to the current repo)
#
# The hook is symlinked, so updating hpc-devsecops updates the hook everywhere.
# Uninstall: rm <repo>/.git/hooks/pre-push

set -euo pipefail

REPO="${1:-$PWD}"
REPO="$(cd "$REPO" && git rev-parse --show-toplevel)"
HOOKS_DIR="$(git -C "$REPO" rev-parse --absolute-git-dir)/hooks"
SELF="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$HOOKS_DIR"
ln -sf "$SELF/hooks/pre-push" "$HOOKS_DIR/pre-push" 2>/dev/null \
  || cp "$SELF/hooks/pre-push" "$HOOKS_DIR/pre-push"
chmod +x "$SELF/hooks/pre-push" "$HOOKS_DIR/pre-push" 2>/dev/null || true

echo "✅ installed pre-push hook → $HOOKS_DIR/pre-push"
echo "   now 'git push' from $REPO runs hpc-devsecops first and blocks on issues."
