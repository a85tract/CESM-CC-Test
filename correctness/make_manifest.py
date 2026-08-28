#!/usr/bin/env python3
"""Assemble an evidence manifest from comparator output plus environment probes.

STATUS: stub. See ../docs/VALIDATION-ARCHITECTURE.md, migration step 3.

What it does
------------
Takes one or more comparator JSON results (one per case), the benchmark
definitions those cases came from, and a probe of the machine they ran on, and
writes a manifest that validates against ../schemas/evidence-manifest.v1.json.

Inputs
------
  --case ID=PATH        comparator JSON for one case; repeatable
  --benchmark-dir DIR   where benchmarks/<product>/<id>.yaml live
  --artifact-repo DIR   the product checkout, for name/repo/commit
  --reference ...       baseline identity (model, commit_or_tag, provenance)
  --outputs-location    absolute path on HPC storage
  --outputs-retention   retention class and expected purge date
  --out PATH            where to write manifest.json

What it must fill in and how
----------------------------
`artifact`      from the product checkout: remote URL, HEAD, and a version. No
                product repo has cut a tag yet, so fall back to the D2 bridge
                form `unreleased-<commit[:8]>`.
`cc_test`       this repository's own HEAD and version, same bridge rule.
`environment`   probe the machine: compiler (`ifx --version`), MPI, python,
                codon, loaded modules. `machine` is required; the rest is
                optional but a `complete` manifest also needs `compiler`.
`cases[]`       one per --case. `acceptance` is copied from the benchmark file
                (that file is the source of truth for the criteria, not this
                tool); `result` comes from the comparator JSON.
`outputs`       location, retention, and per-file md5 + byte counts of the
                candidate output. May be empty if the data was already purged —
                the verifier warns, it is not an error.
`result`        rolled up: ERROR if any case errored, else FAIL if any failed,
                else PASS.

Two invariants this tool is responsible for
-------------------------------------------
1. `result.checks[]` must correspond one-to-one and in order with the
   benchmark's `acceptance.rules[]` — same check name, same `gating` value.
   That correspondence is what lets a reader reconstruct why a PASS is a PASS.
   The comparator reports what it measured; this tool decides which of those
   measurements gated, by reading the benchmark.
2. `evidence_class` is `complete` only when every provenance field was actually
   captured. When backfilling a historical run whose compiler version or
   reference commit is no longer recoverable, emit `reconstructed` and leave
   those fields out. Do not invent a plausible value to satisfy the schema —
   a reconstructed manifest is a format example, and the verifier says so.

Usage (target)
--------------
    make_manifest.py --case pi-6month-allcodon=pi.json \
                     --case mco-6month-allcodon=mco.json \
                     --benchmark-dir benchmarks/pycam5 \
                     --artifact-repo ~/PyCAM5 \
                     --out evidence/pycam5/unreleased-e8d68996/manifest.json
"""

from __future__ import annotations

import sys

SCHEMA_VERSION = "1.0"


def main() -> int:
    raise NotImplementedError(
        "make_manifest.py is a stub. See this module's docstring and "
        "docs/VALIDATION-ARCHITECTURE.md step 3."
    )


if __name__ == "__main__":
    sys.exit(main())
