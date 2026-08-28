#!/usr/bin/env bash
# The fake scanners/compilers below are emitted with printf; the single-quoted
# $1/$#/$@/$2 inside those here-strings are deliberate literal bodies for the
# generated scripts, not this script's own variables. SC2016 is a false positive
# for that pattern throughout this file.
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

export HOME="$TMP/home"
export HPC_DEVSECOPS_AUDIT_ROOT="$TMP/audits"
mkdir -p "$HOME" "$TMP/bin"

help="$("$ROOT/tools/devsecops-local.sh" --help)"
if [[ "$help" == *"set -uo pipefail"* ]]; then bad "help contains implementation"; else ok "help contains only usage"; fi
expect_rc "--base requires an argument" 2 "$ROOT/tools/devsecops-local.sh" --base
expect_rc "blocking mode fails closed when tools are missing" 2 env PATH=/usr/bin:/bin "$ROOT/tools/devsecops-local.sh" --worktree --no-ai --block "$ROOT"
expect_rc "report-only mode reports incomplete without blocking" 0 env PATH=/usr/bin:/bin "$ROOT/tools/devsecops-local.sh" --worktree --no-ai "$ROOT"
expect_rc "--require-complete blocks an incomplete gate without --block" 2 env PATH=/usr/bin:/bin "$ROOT/tools/devsecops-local.sh" --worktree --no-ai --require-complete "$ROOT"

make_fakes() {
  behavior="$1"
  printf '%s\n' '#!/usr/bin/env bash' \
    'report=""; while [ $# -gt 0 ]; do [ "$1" = --report-path ] && { report="$2"; shift; }; shift; done' \
    "[ '$behavior' = error ] && exit 9" \
    "count=0; [ '$behavior' = finding ] && count=1" \
    'printf "{\"runs\":[{\"results\":[" > "$report"' \
    '[ "$count" = 1 ] && printf "{\"level\":\"error\"}" >> "$report"' \
    'printf "]}]}" >> "$report"' > "$TMP/bin/gitleaks"
  printf '%s\n' '#!/usr/bin/env bash' \
    'out=""; for a in "$@"; do case "$a" in spdx-json=*) out="${a#spdx-json=}";; esac; done' \
    'printf "{}" > "$out"' > "$TMP/bin/syft"
  printf '%s\n' '#!/usr/bin/env bash' 'printf "{\"matches\":[]}"' > "$TMP/bin/grype"
  chmod +x "$TMP/bin/gitleaks" "$TMP/bin/syft" "$TMP/bin/grype"
}

make_fakes pass
expect_rc "all successful scanners allow blocking mode" 0 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/devsecops-local.sh" --worktree --no-ai --block "$ROOT"
# summary.json mirrors the run in machine-readable form
sumrun="$TMP/audits-sum"; rm -rf "$sumrun"
env PATH="$TMP/bin:/usr/bin:/bin" HPC_DEVSECOPS_AUDIT_ROOT="$sumrun" \
  "$ROOT/tools/devsecops-local.sh" --worktree --no-ai "$ROOT" >/dev/null 2>&1
sumjson="$(find "$sumrun" -name summary.json 2>/dev/null | head -1)"
if [ -n "$sumjson" ] && python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"]=="PASS", d["status"]; assert set(d["scans"])=={"secrets","cve","ai_audit"}' "$sumjson" 2>/dev/null; then ok "summary.json is emitted and valid"; else bad "summary.json is emitted and valid"; fi
make_fakes finding
expect_rc "secret finding blocks with exit 1" 1 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/devsecops-local.sh" --worktree --no-ai --block "$ROOT"
make_fakes error
expect_rc "scanner execution failure blocks with exit 2" 2 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/devsecops-local.sh" --worktree --no-ai --block "$ROOT"

make_fakes pass
mkdir -p "$TMP/ai-repo/.git" "$TMP/ai-repo/.github/scripts" "$TMP/ai-tool/.venv/bin"
git -C "$TMP/ai-repo" init -q
git -C "$TMP/ai-repo" config user.email test@example.invalid
git -C "$TMP/ai-repo" config user.name test
printf 'base\n' > "$TMP/ai-repo/file"
printf '# audit placeholder\n' > "$TMP/ai-repo/.github/scripts/ai_audit.py"
git -C "$TMP/ai-repo" add . && git -C "$TMP/ai-repo" commit -qm base
printf 'change\n' >> "$TMP/ai-repo/file"
printf '%s\n' '#!/usr/bin/env bash' \
  '[ "$1" = -c ] && exit 0' \
  'printf "{\"runs\":[{\"results\":[],\"invocations\":[{}]}]}" > ai-audit.sarif' > "$TMP/ai-tool/.venv/bin/python"
chmod +x "$TMP/ai-tool/.venv/bin/python"
expect_rc "AI SARIF without explicit success fails closed" 2 env PATH="$TMP/bin:/usr/bin:/bin" \
  HPC_DEVSECOPS_HOME="$TMP/ai-tool" ANTHROPIC_API_KEY=test \
  "$ROOT/tools/devsecops-local.sh" --worktree --block "$TMP/ai-repo"

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
expect_rc "ASan runner succeeds only after a clean execution" 0 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/asan.sh" "$TMP/probe.c"
make_icx 'echo "AddressSanitizer: heap-buffer-overflow" >&2; exit 1'
expect_rc "ASan finding returns exit 1" 1 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/asan.sh" "$TMP/probe.c"
make_icx 'exit 7'
expect_rc "non-ASan runtime failure is preserved" 7 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/asan.sh" "$TMP/probe.c"
expect_rc "missing ASan source is a usage error" 2 env PATH="$TMP/bin:/usr/bin:/bin" "$ROOT/tools/asan.sh" "$TMP/missing.c"

# Verify that the pre-push hook uses the SHA pair provided by Git, not HEAD's upstream.
mkdir -p "$TMP/tool/tools"
printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\n" "$*" > "$HOOK_CAPTURE"' 'exit 0' > "$TMP/tool/tools/devsecops-local.sh"
chmod +x "$TMP/tool/tools/devsecops-local.sh"
export HPC_DEVSECOPS_HOME="$TMP/tool" HOOK_CAPTURE="$TMP/hook.args"
head_sha="$(git -C "$ROOT" rev-parse HEAD)"
parent_sha="$(git -C "$ROOT" rev-parse HEAD^)"
printf 'refs/heads/main %s refs/heads/main %s\n' "$head_sha" "$parent_sha" | \
  "$ROOT/hooks/pre-push" origin example.invalid >/dev/null
if grep -q -- "--range $parent_sha..$head_sha" "$HOOK_CAPTURE"; then ok "pre-push uses Git-provided ref range"; else bad "pre-push uses Git-provided ref range"; fi

printf 'refs/heads/main %s refs/heads/main %040d\n' "$head_sha" 0 | \
  "$ROOT/hooks/pre-push" origin example.invalid >/dev/null
if grep -q -- '--range ' "$HOOK_CAPTURE"; then ok "pre-push handles new branches"; else bad "pre-push handles new branches"; fi

echo "1..$((PASS+FAIL))"
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
