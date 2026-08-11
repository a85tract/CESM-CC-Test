#!/usr/bin/env python3
"""Validate evidence manifests — schema plus the invariants JSON Schema can't express.

STATUS: stub. See ../docs/VALIDATION-ARCHITECTURE.md, migration step 3.

This is the CI entry point. It runs on committed manifests in seconds and needs
no HPC access, no model output, and no network beyond the repository itself.
It is the whole of what GitHub Actions can honestly check about a validation
run (see docs/VALIDATION-ARCHITECTURE.md §4, adjustment A).

Usage (target)
--------------
    verify_evidence.py [PATH ...]      # defaults to every manifest under evidence/
    verify_evidence.py --strict        # treat warnings as errors

Exit 0 when every manifest passes, 1 otherwise. Warnings do not fail the run
unless --strict.

Step 1 — schema
---------------
Load ../schemas/evidence-manifest.v1.json and ../schemas/acceptance.v1.json into
one registry (the manifest $refs the acceptance schema by $id, so a validator
given only one of them will try to resolve the other over the network and fail).
../schemas/test_schemas.py shows the two-line setup.

Step 2 — cross-field invariants
-------------------------------
The authoritative list is in ../schemas/README.md; keep the two in step. As of
schema v1 it is:

  Errors
    1. cases[].result.checks corresponds one-to-one and in order with
       cases[].acceptance.rules — same check name, same gating value.
    2. A case is PASS only if every gating check passed; FAIL if any gating
       check failed; ERROR only with an error message.
    3. Top-level result is the roll-up of the case statuses.
    4. artifact.commit resolves in artifact.repo.
    5. artifact.version equals the directory name under evidence/<product>/.
    6. cases[].benchmark names a file that exists here, and cases[].id equals
       that file's stem.
    7. cc_test.commit resolves in this repository.
    8. evidence/ is append-only: a manifest already on the base branch must not
       be modified by a pull request.
    9. acceptance.kind: statistical is rejected while its status is provisional
       (decision D4 — the vocabulary is a placeholder, not something evidence
       may be filed against yet).

  Warnings
    10. evidence_class: reconstructed — a format example, not compliance evidence.
    11. outputs.files is empty — no fingerprint retained.
    12. outputs.retention is unknown — no purge date recorded.

Invariant 8 needs the base branch, so in CI fetch it and diff; locally, skip it
and say so rather than silently passing a check that did not run.

Output
------
Print one line per finding as `path: LEVEL: message`, and a summary count. A
manifest that fails schema validation is reported and skipped for the invariant
pass — do not attempt invariants against a document whose shape is unknown.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"


def main() -> int:
    raise NotImplementedError(
        "verify_evidence.py is a stub. See this module's docstring, "
        "schemas/README.md for the invariant list, and "
        "docs/VALIDATION-ARCHITECTURE.md step 3."
    )


if __name__ == "__main__":
    sys.exit(main())
