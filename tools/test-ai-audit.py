#!/usr/bin/env python3
"""Self-test for templates/.github/scripts/ai_audit.py.

Covers the parts that must be right without an API key: diff splitting,
batching, and the SARIF mapping the gate reads. Run from the repository root:

    python3 tools/test-ai-audit.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parent.parent / "templates/.github/scripts/ai_audit.py"
spec = importlib.util.spec_from_file_location("ai_audit", AUDIT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

failures = 0


def check(label: str, got, want) -> None:
    global failures
    if got == want:
        print(f"  ok   {label}")
    else:
        failures += 1
        print(f"  FAIL {label}\n       got  {got}\n       want {want}")


DIFF = "".join(
    f"diff --git a/f{i}.f90 b/f{i}.f90\n--- a/f{i}.f90\n+++ b/f{i}.f90\n"
    f"@@ -1 +1,2 @@\n x=1\n+y={i}\n"
    for i in range(5)
)

FINDINGS = [
    dict(file="a.f90", line=7, category="memory-safety", severity="high",
         confidence="high", title="out-of-bounds write", detail="d"),
    dict(file="b.f90", line=1, category="concurrency", severity="high",
         confidence="low", title="possible race", detail="d"),
    dict(file="c.py", line=3, category="secret", severity="medium",
         confidence="high", title="token in source", detail="d"),
    dict(file="d.py", line=0, category="error-handling", severity="low",
         confidence="high", title="bare except", detail="d"),
]


def main() -> int:
    print("diff splitting:")
    chunks = m.split_by_file(DIFF)
    check("one chunk per file", len(chunks), 5)
    check("chunks reassemble to the original", "".join(chunks), DIFF)
    check("empty diff yields no chunks", m.split_by_file("   \n"), [])
    check(
        "a diff with no 'diff --git' header is still one chunk",
        len(m.split_by_file("--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n")),
        1,
    )

    print("\nbatching:")
    check("everything fits in one batch by default", len(m.batch(chunks)), 1)
    check("a tiny budget splits per file", len(m.batch(chunks, budget=10)), 5)
    check("no content is lost when batching", "".join(m.batch(chunks, budget=100)), DIFF)
    check(
        "a single oversized chunk gets its own batch rather than being cut",
        len(m.batch(["x" * 500, "y" * 10], budget=100)),
        2,
    )

    print("\nSARIF level mapping:")
    check("high severity, high confidence blocks",
          m.sarif_level(FINDINGS[0]), "error")
    check("high severity, low confidence reports without blocking",
          m.sarif_level(FINDINGS[1]), "warning")
    check("medium severity is a warning", m.sarif_level(FINDINGS[2]), "warning")
    check("low severity is a note", m.sarif_level(FINDINGS[3]), "note")

    print("\nSARIF document:")
    doc = m.to_sarif(FINDINGS, True, [])
    run = doc["runs"][0]
    check("executionSuccessful is carried through",
          run["invocations"][0]["executionSuccessful"], True)
    check("one rule per distinct category", len(run["tool"]["driver"]["rules"]), 4)
    check("line 0 is clamped to 1",
          run["results"][3]["locations"][0]["physicalLocation"]["region"]["startLine"], 1)
    check("a failed run never reports success",
          m.to_sarif([], False, ["boom"])["runs"][0]["invocations"][0]["executionSuccessful"],
          False)

    print("\nread back exactly as tools/devsecops-local.sh reads it:")
    for ok_flag, findings, want in ((True, FINDINGS, (1, 1)), (False, [], (0, 0))):
        r = m.to_sarif(findings, ok_flag, ["n"])["runs"][0]
        parsed_ok = int(bool((r.get("invocations") or [{}])[0].get("executionSuccessful", True)))
        high = sum(1 for x in r["results"] if x.get("level") == "error")
        check(f"executionSuccessful={ok_flag} -> ok={want[0]} ai_high={want[1]}",
              (parsed_ok, high), want)

    print("\nmarkdown report:")
    check("blocking count is stated", "1 blocking" in m.to_markdown(FINDINGS, True, []), True)
    check("a failed run refuses to read as clean",
          "not a clean bill of health" in m.to_markdown([], False, ["api error"]), True)

    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
