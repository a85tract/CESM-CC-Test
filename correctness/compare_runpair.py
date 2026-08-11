#!/usr/bin/env python3
"""Compare a reference/candidate CESM run pair — bitwise acceptance (Pipeline 1).

STATUS: stub. Port the working implementation from
`PyCAM5/scripts/validation/compare_cesm_runpair.py` and add the `--json` output
described below. See ../docs/VALIDATION-ARCHITECTURE.md, migration step 2.

What it does
------------
Compares CAM monthly history plus final restart-style outputs (`cam.h0.*.nc`,
`cam.r.*.nc`, `cam.rh0.*.nc`, `cam.rs.*.nc`) between two run directories, and
extracts GPTL timers from `cesm_timing_stats`.

It compares variable data, not whole-file blobs:

  numeric variables   one fixed-format dump of ALL numeric variables per file,
                      md5 of that dump -> ONE digest per file
  char variables      per-variable dump, md5 each -> a differing-variable count

The distinction matters and is easy to get wrong: `numeric_md5_equal` in the
acceptance vocabulary is a per-file digest, not a per-variable one. The digest
depends on the dump format string, which is why the manifest records
`dump_format` and `dump_tool` alongside it — a digest taken with a different
format is not comparable with this one.

Porting notes
-------------
1. Rename the run-directory options to `--reference-run-dir` / `--candidate-run-dir`.
   Keep `--native-run-dir` / `--codon-run-dir` as hidden aliases so existing
   scripts keep working; the candidate is not always Codon (freeCAM's is a
   Python-owned control path, Pipeline 2's is a GPU kernel).
2. Add `--json PATH` (or stdout). Text output goes to stderr so the two can be
   used together.
3. Keep the three-valued exit code: 0 PASS, 1 FAIL, 2 ERROR. The existing script
   already returns 2 on a file-set mismatch — preserve that. Nothing was
   compared in that case, which is not the same as a comparison that failed.
4. The existing script computes char differences and timing deltas but neither
   affects its exit code. Do not change that behaviour; record it instead. The
   manifest's `acceptance.rules[].gating` flag is where that fact becomes
   explicit, and `make_manifest.py` reads these results to fill it in.

JSON contract
-------------
The output drops into `cases[].result` of an evidence manifest with no
reshaping. Field names and types are fixed by
`../schemas/evidence-manifest.v1.json` ($defs.fileComparison, $defs.timerComparison):

    {
      "status": "PASS" | "FAIL" | "ERROR",
      "error": "...",                     # required when status is ERROR
      "files": [
        {
          "key": "h0.0001-01.nc",         # filename with the case name stripped
          "numeric_count": 1234,
          "numeric_equal": true,
          "numeric_md5_reference": "<32 hex>" | null,
          "numeric_md5_candidate": "<32 hex>" | null,
          "char_count": 12,
          "char_diff_count": 0,
          "char_diff_vars": []
        }
      ],
      "timing": {
        "physpkg_st1": {"reference": 0.0, "candidate": 0.0, "delta_pct": 0.0}
      },
      "dump_format": "%+.17g",            # echoed so the manifest can record it
      "dump_tool": "ncks"
    }

`delta_pct` is `(candidate / reference - 1) * 100`.

Usage (target)
--------------
    compare_runpair.py --reference-run-dir DIR --candidate-run-dir DIR \
                       [--timer NAME]... [--json PATH]
"""

from __future__ import annotations

import sys

DEFAULT_TIMERS = ("physpkg_st1", "bc_physics", "CPL:RUN_LOOP")
INCLUDE_PREFIXES = ("h0.", "r.", "rh0.", "rs.")
DUMP_FORMAT = "%+.17g"
DUMP_TOOL = "ncks"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def main() -> int:
    raise NotImplementedError(
        "compare_runpair.py is a stub. Port "
        "PyCAM5/scripts/validation/compare_cesm_runpair.py here and add --json; "
        "see this module's docstring and docs/VALIDATION-ARCHITECTURE.md step 2."
    )


if __name__ == "__main__":
    sys.exit(main())
