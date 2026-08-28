#!/usr/bin/env python3
"""AI code audit for the hpc-devsecops gate.

Reads a unified diff, asks Claude to review it, and writes two files into the
current working directory:

    ai-audit.sarif        machine-readable findings (the gate reads this)
    ai-audit-report.md    human-readable summary

The SARIF contract matters more than the exit code. tools/devsecops-local.sh
reads runs[0].invocations[0].executionSuccessful and only trusts the findings
when it is true, because this script writes a SARIF file even when the audit
could not run. Without that flag a 401 would read as "reviewed, zero findings"
- a clean bill of health for code nobody looked at.

Usage:
    ai_audit.py <diff-file>

Environment:
    ANTHROPIC_API_KEY   required
    AI_AUDIT_MODEL      model id (default: claude-opus-5)
    AI_AUDIT_EFFORT     low | medium | high | xhigh | max (default: high)
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

MODEL = os.environ.get("AI_AUDIT_MODEL", "claude-opus-5")
EFFORT = os.environ.get("AI_AUDIT_EFFORT", "high")
MAX_TOKENS = 16000

# Diffs are split into batches under this many characters so a large pull
# request is reviewed in full rather than silently truncated. Roughly 35k
# tokens - far inside the context window, and small enough that the model
# attends to every hunk.
BATCH_CHARS = 120_000

SEVERITY_TO_SARIF = {"high": "error", "medium": "warning", "low": "note"}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description": "Path as it appears on the + side of the diff.",
                    },
                    "line": {
                        "type": "integer",
                        "description": "Line number in the post-change file. Use 1 if unknown.",
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "injection",
                            "secret",
                            "path-traversal",
                            "memory-safety",
                            "concurrency",
                            "input-validation",
                            "crypto",
                            "permissions",
                            "resource-leak",
                            "error-handling",
                            "correctness",
                        ],
                    },
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "title": {"type": "string"},
                    "detail": {
                        "type": "string",
                        "description": "What goes wrong, the inputs or state that trigger it, and the fix.",
                    },
                },
                "required": [
                    "file",
                    "line",
                    "category",
                    "severity",
                    "confidence",
                    "title",
                    "detail",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You review diffs from the CESM/CAM modernization effort: Fortran, C, and Python \
(some of it Codon- or JAX-compiled) that runs on HPC systems under MPI.

Report every issue you find in the changed lines, including ones you are \
uncertain about. Do not filter for importance - assign a severity and a \
confidence to each finding and let the caller rank them. It is better to \
surface a finding that gets filtered out than to drop a real defect.

Severity is about consequence: high means it can corrupt results, crash a run, \
leak a credential, or let untrusted input reach a privileged operation. Medium \
means it degrades correctness or robustness in narrower conditions. Low is a \
maintainability or hygiene concern.

Confidence is about whether the defect is really there given only the diff. \
Say low when the surrounding code you cannot see could make the finding moot.

What matters here: out-of-bounds indexing and uninitialized memory; assumed \
array shapes or unit-stride slices; rank-dependent behavior and collective \
calls on divergent paths; unchecked allocation and file I/O; hardcoded \
credentials, tokens, and absolute scratch paths; shell and subprocess calls \
built from unvalidated input; silent precision changes and reordered floating \
point that break bit-for-bit reproduction.

Report only defects in the added or modified lines. Do not review unchanged \
context, do not restate what the diff does, and do not propose refactors or \
stylistic changes. If the diff contains no defects, return an empty list.\
"""

USER_TEMPLATE = """\
Review this diff{part}.

<diff>
{diff}
</diff>\
"""


# --------------------------------------------------------------------------
# diff splitting
# --------------------------------------------------------------------------


def split_by_file(diff: str) -> list[str]:
    """Split a unified diff into one chunk per file."""
    if not diff.strip():
        return []
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    chunks = [p for p in parts if p.strip()]
    return chunks or [diff]


def batch(chunks: list[str], budget: int = BATCH_CHARS) -> list[str]:
    """Group per-file chunks into batches under the character budget.

    A single file larger than the budget becomes its own batch rather than
    being cut in half: the model sees the whole file's diff or the call fails
    loudly, but nothing is silently dropped.
    """
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for chunk in chunks:
        if current and size + len(chunk) > budget:
            batches.append("".join(current))
            current, size = [], 0
        current.append(chunk)
        size += len(chunk)
    if current:
        batches.append("".join(current))
    return batches


# --------------------------------------------------------------------------
# model call
# --------------------------------------------------------------------------


def audit_batch(client: Any, diff: str, part: str) -> list[dict]:
    """Send one batch to the model and return its findings.

    Raises on any failure - the caller turns that into executionSuccessful=false
    rather than an empty findings list.
    """
    request = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": FINDINGS_SCHEMA},
        },
        "messages": [
            {"role": "user", "content": USER_TEMPLATE.format(part=part, diff=diff)}
        ],
    }

    # Security review is exactly the benign work the cyber safety classifiers
    # are most likely to decline by mistake, so ask the API to re-serve a
    # declined request on a fallback model. If this deployment does not have
    # the beta, fall back to a plain request rather than failing the gate.
    try:
        with client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **request,
        ) as stream:
            message = stream.get_final_message()
    except Exception as exc:  # noqa: BLE001 - narrow by inspection below
        if not _is_unsupported_request(exc):
            raise
        with client.messages.stream(**request) as stream:
            message = stream.get_final_message()

    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) if detail else None
        raise RuntimeError(
            f"model declined to review this diff (category={category or 'unknown'})"
        )

    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError("model returned no text block")
    return json.loads(text).get("findings", [])


def _is_unsupported_request(exc: Exception) -> bool:
    """True when the failure is the fallback beta not being available here."""
    if isinstance(exc, TypeError):
        return True
    status = getattr(exc, "status_code", None)
    return status == 400 and "fallback" in str(exc).lower()


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def sarif_level(finding: dict) -> str:
    """Map a finding to a SARIF level.

    `error` is the only level the gate blocks on, so it is reserved for a
    high-severity finding the model is also confident about. A high-severity
    finding it is unsure of is reported as a warning rather than blocking the
    push on a guess — the model is asked for coverage, and the confidence
    filter belongs here rather than in the prompt. Raise this bar by dropping
    the confidence test if a repository would rather stop on every high.
    """
    if finding["severity"] == "high":
        return "error" if finding["confidence"] == "high" else "warning"
    return SEVERITY_TO_SARIF[finding["severity"]]


def to_sarif(findings: list[dict], ok: bool, notes: list[str]) -> dict:
    rules = {}
    results = []
    for f in findings:
        rule_id = f"ai-audit/{f['category']}"
        rules.setdefault(
            rule_id,
            {
                "id": rule_id,
                "name": f["category"],
                "shortDescription": {"text": f"{f['category']} issue"},
                "defaultConfiguration": {"level": SEVERITY_TO_SARIF[f["severity"]]},
            },
        )
        results.append(
            {
                "ruleId": rule_id,
                "level": sarif_level(f),
                "message": {
                    "text": f"{f['title']}\n\n{f['detail']}\n\n"
                    f"(severity={f['severity']} confidence={f['confidence']})"
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": f["file"]},
                            "region": {"startLine": max(1, int(f["line"]))},
                        }
                    }
                ],
            }
        )

    invocation: dict[str, Any] = {"executionSuccessful": ok}
    if notes:
        invocation["toolExecutionNotifications"] = [
            {"level": "error" if not ok else "note", "message": {"text": n}}
            for n in notes
        ]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ai_audit",
                        "informationUri": "https://github.com/a85tract/CESM-CC-Test",
                        "rules": list(rules.values()),
                    }
                },
                "invocations": [invocation],
                "results": results,
            }
        ],
    }


def to_markdown(findings: list[dict], ok: bool, notes: list[str]) -> str:
    lines = ["# AI code audit", ""]
    if not ok:
        lines += [
            "**The audit did not complete. These results are not a clean bill of health.**",
            "",
        ]
        lines += [f"- {n}" for n in notes] + [""]
        return "\n".join(lines)

    for n in notes:
        lines += [f"> {n}", ""]

    if not findings:
        lines += ["No findings.", ""]
        return "\n".join(lines)

    order = {"high": 0, "medium": 1, "low": 2}
    findings = sorted(findings, key=lambda f: (order[f["severity"]], f["file"]))
    blocking = sum(
        1 for f in findings if f["severity"] == "high" and f["confidence"] == "high"
    )
    lines += [
        f"{len(findings)} finding(s); {blocking} blocking "
        f"(high severity and high confidence).",
        "",
    ]
    for f in findings:
        lines += [
            f"## {f['title']}",
            "",
            f"`{f['file']}:{f['line']}` - {f['category']} - "
            f"severity {f['severity']}, confidence {f['confidence']}",
            "",
            f["detail"],
            "",
        ]
    return "\n".join(lines)


def write(findings: list[dict], ok: bool, notes: list[str]) -> None:
    Path("ai-audit.sarif").write_text(
        json.dumps(to_sarif(findings, ok, notes), indent=2) + "\n"
    )
    Path("ai-audit-report.md").write_text(to_markdown(findings, ok, notes))


# --------------------------------------------------------------------------


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    try:
        diff = Path(sys.argv[1]).read_text(errors="replace")
    except OSError as exc:
        write([], False, [f"could not read the diff: {exc}"])
        return 1

    batches = batch(split_by_file(diff))
    if not batches:
        write([], True, ["empty diff - nothing to review"])
        return 0

    try:
        import anthropic
    except ImportError:
        write([], False, ["the 'anthropic' package is not installed"])
        return 1

    if not os.environ.get("ANTHROPIC_API_KEY"):
        write([], False, ["ANTHROPIC_API_KEY is not set"])
        return 1

    client = anthropic.Anthropic()
    findings: list[dict] = []
    notes: list[str] = []
    if len(batches) > 1:
        notes.append(f"diff reviewed in {len(batches)} batches ({len(diff)} chars)")

    for i, chunk in enumerate(batches, 1):
        part = f" (part {i} of {len(batches)})" if len(batches) > 1 else ""
        try:
            findings.extend(audit_batch(client, chunk, part))
        except Exception as exc:  # noqa: BLE001 - any failure invalidates the run
            notes.append(f"batch {i} of {len(batches)} failed: {exc}")
            traceback.print_exc(file=sys.stderr)
            # Partial coverage is not coverage: one failed batch means the diff
            # was not fully reviewed, so the whole audit is reported as failed.
            write(findings, False, notes)
            return 1

    write(findings, True, notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
