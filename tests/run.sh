#!/usr/bin/env bash
# The Cyber half's integration tests: the wrappers under tools/ and hooks/ over
# a fake engine. `recast` is faked on PATH (behaviour through FAKE_RC and
# FAKE_RECIPES), and RECAST_HOME points at a fake checkout whose tools/pre-push
# and tools/install-config.sh record what they were called with. The engine's
# own tests cover what those do; these cover what the wrappers hand them and
# the exit contract they keep. The fake scripts are written with here-documents
# whose $1/$@ are the fakes' own, not this script's (SC2016 is that pattern).
# shellcheck disable=SC2016
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0

ok() { echo "ok - $1"; PASS=$((PASS+1)); }
bad() { echo "not ok - $1"; FAIL=$((FAIL+1)); }
expect_rc() {
  name="$1" expected="$2"; shift 2
  "$@" >"$TMP/out" 2>"$TMP/err"; actual=$?
  if [ "$actual" -eq "$expected" ]; then ok "$name"; else bad "$name (expected $expected, got $actual)"; sed -n '1,80p' "$TMP/out" "$TMP/err"; fi
}
# The last recast run's argv, one per line, as the fake recorded it.
argv_has() { grep -qxF -- "$1" "$TMP/recast.argv"; }
argv_after() { awk -v k="$1" '$0 == k { getline; print; exit }' "$TMP/recast.argv"; }

export HOME="$TMP/home"
export HPC_DEVSECOPS_AUDIT_ROOT="$TMP/audits"
export RECAST_CAPTURE="$TMP/recast.argv"
unset RECAST_AUDIT_RECIPE RECAST_HOME RECAST_BIN
mkdir -p "$HOME" "$TMP/bin"
BIN_PATH="$TMP/bin:/usr/bin:/bin"
BARE_PATH="/usr/bin:/bin"

# --- the fake engine --------------------------------------------------------

cat > "$TMP/bin/recast" <<'FAKE'
#!/usr/bin/env bash
case "${1:-}" in
  recipes) for r in ${FAKE_RECIPES:-audit}; do echo "$r   (fake)"; done ;;
  run)
    printf '%s\n' "$@" > "${RECAST_CAPTURE:-/dev/null}"
    gs=""; while [ $# -gt 0 ]; do [ "$1" = --gate-summary ] && gs="$2"; shift; done
    if [ -n "$gs" ]; then
      mkdir -p "$(dirname "$gs")"
      case "${FAKE_RC:-0}" in 0) s=PASS ;; 1) s=FINDINGS ;; *) s=INCOMPLETE ;; esac
      printf '{"tool":"recast","status":"%s","scans":{"secrets":{},"cve":{},"ai_audit":{}}}\n' "$s" > "$gs"
    fi
    exit "${FAKE_RC:-0}" ;;
  *) exit 2 ;;
esac
FAKE
chmod +x "$TMP/bin/recast"

ENGINE="$TMP/engine"
mkdir -p "$ENGINE/tools"
printf '%s\n' '#!/usr/bin/env bash' \
  'printf "%s\n" "$*" > "$HOOK_CAPTURE"' \
  'cat >> "$HOOK_CAPTURE"' \
  'printf "recipe=%s root=%s\n" "${RECAST_AUDIT_RECIPE:-}" "${RECAST_AUDIT_ROOT:-}" >> "$HOOK_CAPTURE"' \
  'exit 0' > "$ENGINE/tools/pre-push"
printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\n" "$*" > "$INSTALL_CAPTURE"' 'exit 0' > "$ENGINE/tools/install-config.sh"
chmod +x "$ENGINE/tools/pre-push" "$ENGINE/tools/install-config.sh"

# A target repository with two commits, so there is a range to audit; a second
# one that opted into the AI audit the hpc-devsecops way.
make_repo() {
  git -C "$1" init -q
  git -C "$1" config user.email test@example.invalid
  git -C "$1" config user.name test
  printf 'base\n' > "$1/file"
  [ "${2:-}" = ai ] && { mkdir -p "$1/.github/scripts"; printf '# opt-in marker\n' > "$1/.github/scripts/ai_audit.py"; }
  git -C "$1" add . && git -C "$1" commit -qm base
  printf 'change\n' >> "$1/file"
  git -C "$1" commit -qam change
}
mkdir -p "$TMP/repo" "$TMP/ai-repo"
make_repo "$TMP/repo"
make_repo "$TMP/ai-repo" ai
head_sha="$(git -C "$TMP/repo" rev-parse HEAD)"
parent_sha="$(git -C "$TMP/repo" rev-parse HEAD^)"
range="$parent_sha..$head_sha"
ai_range="$(git -C "$TMP/ai-repo" rev-parse HEAD^)..$(git -C "$TMP/ai-repo" rev-parse HEAD)"
RUNNER="$ROOT/tools/devsecops-local.sh"
# Each run's argv is read from a fresh capture, so a run that never reached
# the engine cannot pass on the previous run's record.
fresh() { rm -f "$RECAST_CAPTURE" "${HOOK_CAPTURE:-/dev/null}" 2>/dev/null; "$@"; }

# --- devsecops-local.sh: usage ------------------------------------------------

help="$("$RUNNER" --help)"
if [[ "$help" == *"set -uo pipefail"* ]]; then bad "help contains implementation"; else ok "help contains only usage"; fi
expect_rc "--base requires an argument" 2 "$RUNNER" --base
expect_rc "--staged is refused, not silently widened" 2 "$RUNNER" --staged "$TMP/repo"
if grep -q 'not available' "$TMP/err"; then ok "--staged says why"; else bad "--staged says why"; fi
expect_rc "no upstream and no base is a usage error" 2 env PATH="$BIN_PATH" "$RUNNER" "$TMP/repo"

# --- devsecops-local.sh: the exit contract ------------------------------------

expect_rc "blocking mode fails closed when recast is missing" 2 env PATH="$BARE_PATH" "$RUNNER" --range "$range" --block "$TMP/repo"
expect_rc "report-only mode reports incomplete without blocking" 0 env PATH="$BARE_PATH" "$RUNNER" --range "$range" "$TMP/repo"
if grep -q '^INCOMPLETE' "$TMP/out"; then ok "report-only run says INCOMPLETE"; else bad "report-only run says INCOMPLETE"; fi
expect_rc "--require-complete blocks an incomplete gate without --block" 2 env PATH="$BARE_PATH" "$RUNNER" --range "$range" --require-complete "$TMP/repo"

expect_rc "a clean run allows blocking mode" 0 env PATH="$BIN_PATH" FAKE_RC=0 "$RUNNER" --range "$range" --block "$TMP/repo"
expect_rc "findings block with exit 1" 1 env PATH="$BIN_PATH" FAKE_RC=1 "$RUNNER" --range "$range" --block "$TMP/repo"
expect_rc "findings do not block a report-only run" 0 env PATH="$BIN_PATH" FAKE_RC=1 "$RUNNER" --range "$range" "$TMP/repo"
expect_rc "an incomplete audit blocks with exit 2" 2 env PATH="$BIN_PATH" FAKE_RC=2 "$RUNNER" --range "$range" --block "$TMP/repo"
expect_rc "an incomplete audit blocks under --require-complete" 2 env PATH="$BIN_PATH" FAKE_RC=2 "$RUNNER" --range "$range" --require-complete "$TMP/repo"
expect_rc "an incomplete audit is reported, not blocked, by default" 0 env PATH="$BIN_PATH" FAKE_RC=2 "$RUNNER" --range "$range" "$TMP/repo"
expect_rc "an engine exit code outside the contract is incomplete" 2 env PATH="$BIN_PATH" FAKE_RC=9 "$RUNNER" --range "$range" --block "$TMP/repo"

# --- devsecops-local.sh: what reaches the engine ------------------------------

sumrun="$TMP/audits-sum"; rm -rf "$sumrun"
fresh env PATH="$BIN_PATH" HPC_DEVSECOPS_AUDIT_ROOT="$sumrun" "$RUNNER" --range "$range" "$TMP/repo" >/dev/null 2>&1
sumjson="$(find "$sumrun/repo" -name summary.json 2>/dev/null | head -1)"
if [ -n "$sumjson" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"]=="PASS", d["status"]; assert set(d["scans"])=={"secrets","cve","ai_audit"}' "$sumjson" 2>/dev/null; then ok "summary.json is left under the audit root, per repo and run"; else bad "summary.json is left under the audit root, per repo and run"; fi
if [ "$(argv_after --range)" = "$range" ]; then ok "--range is passed through"; else bad "--range is passed through"; fi
if [ "$(argv_after run)" = audit ] && [ "$(argv_after audit)" = "$TMP/repo" ]; then ok "the recipe is audit and the root is the repo"; else bad "the recipe is audit and the root is the repo"; fi
if argv_has --config; then bad "--config is not passed without .recast-audit.json"; else ok "--config is not passed without .recast-audit.json"; fi

fresh env PATH="$BIN_PATH" "$RUNNER" --base "$parent_sha" "$TMP/repo" >/dev/null 2>&1
if [ "$(argv_after --range)" = "$parent_sha..HEAD" ]; then ok "--base becomes a BASE..HEAD range"; else bad "--base becomes a BASE..HEAD range"; fi

printf '{"stages": {}}\n' > "$TMP/repo/.recast-audit.json"
fresh env PATH="$BIN_PATH" "$RUNNER" --range "$range" "$TMP/repo" >/dev/null 2>&1
if [ "$(argv_after --config)" = "$TMP/repo/.recast-audit.json" ]; then ok "--config is passed when .recast-audit.json exists"; else bad "--config is passed when .recast-audit.json exists"; fi
rm "$TMP/repo/.recast-audit.json"

fresh env PATH="$BIN_PATH" FAKE_RECIPES="audit audit-cesm" "$RUNNER" --range "$ai_range" "$TMP/ai-repo" >/dev/null 2>&1
if [ "$(argv_after run)" = audit-cesm ]; then ok "a repo that opted into the AI audit runs audit-cesm"; else bad "a repo that opted into the AI audit runs audit-cesm"; fi
fresh env PATH="$BIN_PATH" FAKE_RECIPES="audit audit-cesm" "$RUNNER" --range "$ai_range" --no-ai "$TMP/ai-repo" >/dev/null 2>&1
if [ "$(argv_after run)" = audit ]; then ok "--no-ai runs audit regardless"; else bad "--no-ai runs audit regardless"; fi
fresh env PATH="$BIN_PATH" FAKE_RECIPES="audit audit-cesm" RECAST_AUDIT_RECIPE=audit "$RUNNER" --range "$ai_range" "$TMP/ai-repo" >/dev/null 2>&1
if [ "$(argv_after run)" = audit ]; then ok "RECAST_AUDIT_RECIPE overrides the choice"; else bad "RECAST_AUDIT_RECIPE overrides the choice"; fi
expect_rc "an opted-in repo without audit-cesm installed is incomplete, not quieter" 2 fresh env PATH="$BIN_PATH" FAKE_RECIPES="audit" "$RUNNER" --range "$ai_range" --block "$TMP/ai-repo"
if [ -e "$RECAST_CAPTURE" ]; then bad "the engine is not run for a recipe that is not there"; else ok "the engine is not run for a recipe that is not there"; fi

# --- hooks/pre-push: the engine's hook, after the recipe choice ---------------

export HOOK_CAPTURE="$TMP/hook.out"
push_line="refs/heads/main $head_sha refs/heads/main $parent_sha"
expect_rc "the hook runs the engine's hook" 0 fresh env PATH="$BIN_PATH" RECAST_HOME="$ENGINE" bash -c 'cd "$1" && printf "%s\n" "$2" | "$3" origin example.invalid' _ "$TMP/repo" "$push_line" "$ROOT/hooks/pre-push"
if [ "$(sed -n 1p "$HOOK_CAPTURE")" = "origin example.invalid" ]; then ok "argv reaches the engine's hook"; else bad "argv reaches the engine's hook"; fi
if [ "$(sed -n 2p "$HOOK_CAPTURE")" = "$push_line" ]; then ok "git's ref lines reach the engine's hook on stdin"; else bad "git's ref lines reach the engine's hook on stdin"; fi
if grep -q "^recipe=audit root=$TMP/audits\$" "$HOOK_CAPTURE"; then ok "recipe audit, and HPC_DEVSECOPS_AUDIT_ROOT is honoured"; else bad "recipe audit, and HPC_DEVSECOPS_AUDIT_ROOT is honoured"; sed -n 3p "$HOOK_CAPTURE"; fi

fresh env PATH="$BIN_PATH" RECAST_HOME="$ENGINE" FAKE_RECIPES="audit audit-cesm" bash -c 'cd "$1" && printf "%s\n" "$2" | "$3" origin example.invalid' _ "$TMP/ai-repo" "$push_line" "$ROOT/hooks/pre-push" >/dev/null 2>&1
if grep -q '^recipe=audit-cesm ' "$HOOK_CAPTURE"; then ok "the hook chooses audit-cesm for an opted-in repo"; else bad "the hook chooses audit-cesm for an opted-in repo"; fi

expect_rc "a missing engine checkout blocks the push" 2 env PATH="$BARE_PATH" RECAST_HOME="$TMP/nowhere" bash -c 'cd "$1" && printf "%s\n" "$2" | "$3" origin example.invalid' _ "$TMP/repo" "$push_line" "$ROOT/hooks/pre-push"
expect_rc "an opted-in repo without audit-cesm blocks the push" 2 env PATH="$BIN_PATH" RECAST_HOME="$ENGINE" FAKE_RECIPES="audit" bash -c 'cd "$1" && printf "%s\n" "$2" | "$3" origin example.invalid' _ "$TMP/ai-repo" "$push_line" "$ROOT/hooks/pre-push"

# --- tools/install-config.sh: the engine's installer --------------------------

export INSTALL_CAPTURE="$TMP/install.out"
expect_rc "install-config.sh runs the engine's installer" 0 env RECAST_HOME="$ENGINE" "$ROOT/tools/install-config.sh" --force "$TMP/repo"
if [ "$(cat "$INSTALL_CAPTURE")" = "--force $TMP/repo" ]; then ok "install-config.sh passes its arguments through"; else bad "install-config.sh passes its arguments through"; fi
expect_rc "install-config.sh without an engine checkout is an error" 2 env PATH="$BARE_PATH" RECAST_HOME="$TMP/nowhere" "$ROOT/tools/install-config.sh" "$TMP/repo"

# --- tools/install-hooks.sh: installs hooks/pre-push here, symlinked ----------

expect_rc "install-hooks.sh installs the hook" 0 "$ROOT/tools/install-hooks.sh" "$TMP/repo"
if [ "$(readlink "$TMP/repo/.git/hooks/pre-push")" = "$ROOT/hooks/pre-push" ]; then ok "the installed hook is a symlink to hooks/pre-push"; else bad "the installed hook is a symlink to hooks/pre-push"; fi

# --- tools/asan.sh: unchanged until recast-cesm's dynamic.asan is wrapped -----

printf 'int main(void) { return 0; }\n' > "$TMP/probe.c"
make_icx() {
  result="$1"
  printf '%s\n' '#!/usr/bin/env bash' \
    'out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && { out="$2"; shift; }; shift; done' \
    "printf '%s\\n' '#!/usr/bin/env bash' > \"\$out\"" \
    "printf '%s\\n' '$result' >> \"\$out\"" \
    'chmod +x "$out"' > "$TMP/bin/icx"
  chmod +x "$TMP/bin/icx"
}
make_icx 'exit 0'
expect_rc "ASan runner succeeds only after a clean execution" 0 env PATH="$BIN_PATH" "$ROOT/tools/asan.sh" "$TMP/probe.c"
make_icx 'echo "AddressSanitizer: heap-buffer-overflow" >&2; exit 1'
expect_rc "ASan finding returns exit 1" 1 env PATH="$BIN_PATH" "$ROOT/tools/asan.sh" "$TMP/probe.c"
make_icx 'exit 7'
expect_rc "non-ASan runtime failure is preserved" 7 env PATH="$BIN_PATH" "$ROOT/tools/asan.sh" "$TMP/probe.c"
expect_rc "missing ASan source is a usage error" 2 env PATH="$BIN_PATH" "$ROOT/tools/asan.sh" "$TMP/missing.c"

echo "1..$((PASS+FAIL))"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
