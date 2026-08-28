#!/usr/bin/env python3
"""Self-test for the CC-Test schemas.

The format example must validate, and every deliberate mutation below must be
rejected. Run from the repository root:

    python3 -m venv .venv && .venv/bin/pip install jsonschema
    .venv/bin/python schemas/test_schemas.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "evidence-manifest.v1.json").read_text())
ACCEPT = json.loads((HERE / "acceptance.v1.json").read_text())
EXAMPLE = json.loads((HERE / "examples" / "example-bitwise.manifest.json").read_text())

REGISTRY = Registry().with_resources(
    [
        (MANIFEST["$id"], Resource.from_contents(MANIFEST)),
        (ACCEPT["$id"], Resource.from_contents(ACCEPT)),
    ]
)
VALIDATOR = Draft202012Validator(MANIFEST, registry=REGISTRY)


def mutate(fn) -> dict:
    """Deep-copy the example and apply one breaking change to it."""
    doc = copy.deepcopy(EXAMPLE)
    fn(doc)
    return doc


def _complete_provenance(doc: dict) -> None:
    doc["evidence_class"] = "complete"
    doc["reference"]["commit_or_tag"] = "abc1234"
    doc["environment"]["compiler"] = "ifx 2025.2.1"



POSITIVE = [
    ("format example validates", EXAMPLE),
    ("complete evidence_class with full provenance", mutate(_complete_provenance)),
    (
        "statistical acceptance is schema-legal while marked provisional",
        mutate(
            lambda d: d["cases"][0].__setitem__(
                "acceptance",
                {
                    "kind": "statistical",
                    "status": "provisional",
                    "rules": [
                        {
                            "check": "relative_diff_max",
                            "variables": ["T"],
                            "norm": "l2",
                            "tolerance": 1.24e-6,
                            "gating": True,
                        }
                    ],
                },
            )
        ),
    ),
]

NEGATIVE = [
    (
        "acceptance block in which nothing gates",
        mutate(
            lambda d: d["cases"][0]["acceptance"].__setitem__(
                "rules", [{"check": "char_diff_count", "expect": 0, "gating": False}]
            )
        ),
    ),
    (
        "gating check that reaches no verdict",
        mutate(lambda d: d["cases"][0]["result"]["checks"][1].__setitem__("passed", None)),
    ),
    (
        "numeric_md5_equal without dump_format",
        mutate(lambda d: d["cases"][0]["acceptance"]["rules"][1].pop("dump_format")),
    ),
    (
        "version without the v prefix",
        mutate(lambda d: d["artifact"].__setitem__("version", "0.2.0")),
    ),
    (
        "complete evidence_class missing reference.commit_or_tag",
        mutate(lambda d: d.__setitem__("evidence_class", "complete")),
    ),
    (
        "gating timing rule without max_abs_pct",
        mutate(lambda d: d["cases"][0]["acceptance"]["rules"][3].__setitem__("gating", True)),
    ),
    (
        "statistical acceptance without the provisional marker",
        mutate(
            lambda d: d["cases"][0].__setitem__(
                "acceptance",
                {
                    "kind": "statistical",
                    "rules": [
                        {
                            "check": "relative_diff_max",
                            "variables": ["T"],
                            "norm": "l2",
                            "tolerance": 1e-6,
                            "gating": True,
                        }
                    ],
                },
            )
        ),
    ),
    (
        "case status ERROR without an error message",
        mutate(lambda d: d["cases"][0]["result"].__setitem__("status", "ERROR")),
    ),
    ("unknown top-level property", mutate(lambda d: d.__setitem__("verdict", "PASS"))),
    ("outputs without retention", mutate(lambda d: d["cases"][0]["outputs"].pop("retention"))),
    ("commit that is not hex", mutate(lambda d: d["artifact"].__setitem__("commit", "zzzzzzz"))),
    (
        "benchmark path outside benchmarks/",
        mutate(lambda d: d["cases"][0].__setitem__("benchmark", "cases/pi.yaml")),
    ),
]


def main() -> int:
    failures = 0

    for name, schema in (("evidence-manifest.v1", MANIFEST), ("acceptance.v1", ACCEPT)):
        Draft202012Validator.check_schema(schema)
        print(f"  ok   well-formed draft 2020-12: {name}")

    print("\nmust validate:")
    for label, doc in POSITIVE:
        errors = sorted(VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"  FAIL {label}\n       {errors[0].message}")
        else:
            print(f"  ok   {label}")

    print("\nmust be rejected:")
    for label, doc in NEGATIVE:
        if list(VALIDATOR.iter_errors(doc)):
            print(f"  ok   {label}")
        else:
            failures += 1
            print(f"  FAIL accepted but should not be: {label}")

    print(f"\n{'ALL PASS' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
