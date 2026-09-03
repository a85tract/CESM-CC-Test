#!/usr/bin/env python3
"""Compare a reference/candidate CESM run pair — bitwise acceptance (Pipeline 1).

Ported from `PyCAM5/scripts/validation/compare_cesm_runpair.py` (migration
step 2), with `--json` added and the run-directory options renamed; see
../docs/VALIDATION-ARCHITECTURE.md.

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

What "bitwise" means here
-------------------------
Byte-identical dumps after alignment on the variables the two files share, in
sorted name order. Alignment is where a silent pass would hide, so it does not
fail quietly:

  - different file sets between the run directories        -> ERROR (unchanged)
  - a file present in both but holding different variables -> ERROR
  - no files in scope at all                               -> ERROR
  - an input this build cannot read (no NetCDF reader)     -> ERROR

None of these is a FAIL. Nothing was compared, and "not compared" has to stay
distinguishable from "compared, identical".

A shared variable whose shape or dtype differs is a genuine difference, not an
absent comparison: its dump differs, so the file's digest differs and the case
FAILs. Its per-field `max_abs` is then null, because there is nothing to
subtract.

Exit codes
----------
0 PASS  every in-scope file's numeric digest matched
1 FAIL  at least one numeric digest differed
2 ERROR the comparison could not be carried out

Character differences and timing deltas are computed and reported but do NOT
affect the exit code — that was the de facto criterion of the original script
and it is preserved deliberately. The manifest's `acceptance.rules[].gating`
flag is where the fact becomes explicit; `make_manifest.py` reads these results
and the benchmark to fill it in.

JSON contract
-------------
`files[]` and `timing` drop into `cases[].result` of an evidence manifest with
no reshaping; their field names and types are fixed by
`../schemas/evidence-manifest.v1.json` ($defs.fileComparison,
$defs.timerComparison). The remaining top-level keys are what `make_manifest.py`
needs in order to decide the acceptance rules, plus detail for the human report.

    {
      "status": "PASS" | "FAIL" | "ERROR",
      "error": "...",                     # present when status is ERROR
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
      "dump_tool": "ncks",                # which backend ran; see dataio.py
      "file_set": {"equal": true, "reference_only": [], "candidate_only": []},
      "field_detail": [                   # numpy backend only; [] under ncks
        {"key": "...", "variable": "T", "shape": [2, 3], "equal": true,
         "max_abs": 0.0, "max_rel": 0.0, "note": null}
      ],
      "notes": ["..."]                    # non-gating remarks, e.g. absent timers
    }

`delta_pct` is `(candidate / reference - 1) * 100`.

Per-field `max_abs` / `max_rel` need the values, so the in-process backend
produces them. Under `ncks` the tool holds digests and nothing else — exactly as
the original did — and `field_detail` is empty with the reason in `notes`,
rather than reporting zeros nobody measured.

Usage
-----
    compare_runpair.py --reference-run-dir DIR --candidate-run-dir DIR \
                       [--timer NAME]... [--dump-tool auto|ncks|numpy] \
                       [--dump-format FMT] [--json [PATH]]

`--json` with no value writes to stdout; the human-readable report always goes
to stderr, so the two can be used together. `--native-run-dir` and
`--codon-run-dir` remain as hidden aliases: the candidate is Codon for PyCAM5,
a Python-owned control path for freeCAM, and a GPU kernel for Pipeline 2.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import dataio
from dataio import DataError

DEFAULT_TIMERS = ("physpkg_st1", "bc_physics", "CPL:RUN_LOOP")
INCLUDE_PREFIXES = dataio.INCLUDE_PREFIXES
DUMP_FORMAT = dataio.DUMP_FORMAT
DUMP_TOOL = "ncks"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def _max_abs_rel(reference, candidate):
    """(max |d|, max |d| / |reference|) over the elements, or (None, None).

    Both are None when the shapes differ — there is no elementwise difference
    to take. max_rel is None when every reference element is zero, because a
    relative difference against zero is not a number anyone should read.
    Non-finite elements are excluded from both.
    """
    np = dataio._numpy()
    if reference.shape != candidate.shape:
        return None, None
    ref = np.asarray(reference, dtype=float).reshape(-1)
    cand = np.asarray(candidate, dtype=float).reshape(-1)
    if ref.size == 0:
        return 0.0, None
    finite = np.isfinite(ref) & np.isfinite(cand)
    if not finite.any():
        return None, None
    diff = np.abs(cand[finite] - ref[finite])
    max_abs = float(diff.max())
    base = np.abs(ref[finite])
    nonzero = base != 0.0
    max_rel = float((diff[nonzero] / base[nonzero]).max()) if nonzero.any() else None
    return max_abs, max_rel


def compare_file(key: str, reference: dataio.Reader, candidate: dataio.Reader):
    """Compare one output file. Returns (fileComparison, field_detail, error)."""
    ref_numeric, cand_numeric = reference.numeric_names(), candidate.numeric_names()
    ref_char, cand_char = reference.char_names(), candidate.char_names()

    ref_all = set(ref_numeric) | set(ref_char)
    cand_all = set(cand_numeric) | set(cand_char)
    only_reference = sorted(ref_all - cand_all)
    only_candidate = sorted(cand_all - ref_all)
    if only_reference or only_candidate:
        return None, [], (
            "%s: the two files declare different variables, so part of the file "
            "would not be compared (reference only: %s; candidate only: %s)"
            % (key, only_reference or "-", only_candidate or "-")
        )

    numeric = sorted(set(ref_numeric) & set(cand_numeric))
    chars = sorted(set(ref_char) & set(cand_char))
    if not numeric and not chars:
        return None, [], "%s: no variables in common, nothing was compared" % key

    ref_digest = reference.numeric_digest(numeric)
    cand_digest = candidate.numeric_digest(numeric)

    char_diffs = [
        name for name in chars
        if reference.char_digest(name) != candidate.char_digest(name)
    ]

    detail: List[dict] = []
    for name in numeric:
        ref_array = reference.numeric_array(name)
        cand_array = candidate.numeric_array(name)
        if ref_array is None or cand_array is None:
            continue
        equal = reference.numeric_dump([name]) == candidate.numeric_dump([name])
        max_abs, max_rel = _max_abs_rel(ref_array, cand_array)
        note = None
        if ref_array.shape != cand_array.shape:
            note = "shape differs: %s vs %s" % (
                tuple(ref_array.shape), tuple(cand_array.shape))
        detail.append({
            "key": key,
            "variable": name,
            "shape": list(ref_array.shape),
            "equal": bool(equal),
            "max_abs": max_abs,
            "max_rel": max_rel,
            "note": note,
        })

    comparison = {
        "key": key,
        "numeric_count": len(numeric),
        "numeric_equal": ref_digest == cand_digest,
        "numeric_md5_reference": ref_digest,
        "numeric_md5_candidate": cand_digest,
        "char_count": len(chars),
        "char_diff_count": len(char_diffs),
        "char_diff_vars": char_diffs,
    }
    return comparison, detail, None


def compare_timing(reference_dir: Path, candidate_dir: Path, timers):
    """Per-timer deltas, plus a note for every timer that could not be read.

    An absent timer is never silently dropped: it produces a note, and
    `make_manifest.py` turns that into an unevaluable check if a benchmark
    gates on it.
    """
    timing: Dict[str, dict] = {}
    notes: List[str] = []
    for timer in timers:
        try:
            ref_value = dataio.extract_timer(reference_dir, timer)
            cand_value = dataio.extract_timer(candidate_dir, timer)
        except DataError as exc:
            notes.append("timer %s not compared: %s" % (timer, exc))
            continue
        if ref_value == 0.0:
            notes.append("timer %s: reference is 0, delta_pct is undefined" % timer)
            continue
        timing[timer] = {
            "reference": ref_value,
            "candidate": cand_value,
            "delta_pct": (cand_value / ref_value - 1.0) * 100.0,
        }
    return timing, notes


def empty_result(dump_format: str) -> dict:
    return {
        "status": "ERROR",
        "files": [],
        "timing": {},
        "dump_format": dump_format,
        "dump_tool": None,
        "file_set": {"equal": False, "reference_only": [], "candidate_only": []},
        "field_detail": [],
        "notes": [],
    }


def build_result(args) -> dict:
    result = empty_result(args.dump_format)

    reference_files = dataio.collect_run_files(args.reference_run_dir)
    candidate_files = dataio.collect_run_files(args.candidate_run_dir)

    only_reference = sorted(set(reference_files) - set(candidate_files))
    only_candidate = sorted(set(candidate_files) - set(reference_files))
    result["file_set"] = {
        "equal": not (only_reference or only_candidate),
        "reference_only": only_reference,
        "candidate_only": only_candidate,
    }
    if not reference_files and not candidate_files:
        result["error"] = (
            "no output files in scope under %s or %s (looking for *.cam.{%s}.*)"
            % (args.reference_run_dir, args.candidate_run_dir,
               ",".join(p.rstrip(".") for p in INCLUDE_PREFIXES))
        )
        return result
    if not result["file_set"]["equal"]:
        result["error"] = (
            "file set mismatch, nothing was compared (missing from candidate: %s; "
            "missing from reference: %s)"
            % (only_reference or "-", only_candidate or "-")
        )
        return result

    backend = dataio.choose_backend(
        list(reference_files.values()) + list(candidate_files.values()), args.dump_tool)
    result["dump_tool"] = backend
    if backend == "ncks":
        result["notes"].append(
            "ncks backend: digests only, so per-field max_abs / max_rel were not measured")

    errors: List[str] = []
    for key in sorted(reference_files):
        reference = dataio.open_reader(reference_files[key], backend, args.dump_format)
        candidate = dataio.open_reader(candidate_files[key], backend, args.dump_format)
        comparison, detail, error = compare_file(key, reference, candidate)
        if error is not None:
            errors.append(error)
            continue
        result["files"].append(comparison)
        result["field_detail"].extend(detail)

    timing, notes = compare_timing(
        args.reference_run_dir, args.candidate_run_dir, args.timers)
    result["timing"] = timing
    result["notes"].extend(notes)

    if errors:
        result["error"] = "; ".join(errors)
        return result

    numeric_ok = all(entry["numeric_equal"] for entry in result["files"])
    result["status"] = "PASS" if numeric_ok else "FAIL"
    return result


def write_report(result: dict, stream) -> None:
    """The human report, in the shape the original script printed."""
    for entry in result["files"]:
        print("=== %s ===" % entry["key"], file=stream)
        for field in ("numeric_count", "numeric_equal", "numeric_md5_reference",
                      "numeric_md5_candidate", "char_count", "char_diff_count"):
            print("%s=%s" % (field, entry[field]), file=stream)
        if entry["char_diff_vars"]:
            print("char_diff_vars=" + ",".join(entry["char_diff_vars"]), file=stream)
        print(file=stream)

    if result["field_detail"]:
        print("=== fields ===", file=stream)
        for field in result["field_detail"]:
            print(
                "%s %s equal=%s max_abs=%s max_rel=%s%s"
                % (field["key"], field["variable"], field["equal"],
                   field["max_abs"], field["max_rel"],
                   " (%s)" % field["note"] if field["note"] else ""),
                file=stream,
            )
        print(file=stream)

    print("=== timing ===", file=stream)
    for name, timer in result["timing"].items():
        print("%s: reference=%.6f candidate=%.6f delta_pct=%.3f"
              % (name, timer["reference"], timer["candidate"], timer["delta_pct"]),
              file=stream)
    print(file=stream)

    for note in result["notes"]:
        print("note: %s" % note, file=stream)
    if result["files"]:
        numeric_ok = all(e["numeric_equal"] for e in result["files"])
        char_ok = all(e["char_diff_count"] == 0 for e in result["files"])
        print("overall_numeric_equal=%s" % numeric_ok, file=stream)
        print("overall_char_equal=%s" % char_ok, file=stream)
    print("dump_tool=%s dump_format=%s" % (result["dump_tool"], result["dump_format"]),
          file=stream)
    print("status=%s" % result["status"], file=stream)
    if result.get("error"):
        print("error: %s" % result["error"], file=stream)


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Compare a reference/candidate CESM run pair (bitwise acceptance).")
    parser.add_argument("--reference-run-dir", type=Path)
    parser.add_argument("--candidate-run-dir", type=Path)
    # Hidden aliases: existing scripts still call the tool this way.
    parser.add_argument("--native-run-dir", type=Path, dest="reference_run_dir",
                        help=argparse.SUPPRESS)
    parser.add_argument("--codon-run-dir", type=Path, dest="candidate_run_dir",
                        help=argparse.SUPPRESS)
    parser.add_argument("--timer", action="append", dest="timers",
                        help="GPTL timer to compare; repeatable")
    parser.add_argument("--dump-tool", default="auto", choices=("auto", "ncks", "numpy"),
                        help="which dump backend to use; recorded in the output")
    parser.add_argument("--dump-format", default=DUMP_FORMAT,
                        help="format string for the numeric dump (default %(default)s)")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH",
                        help="write the JSON result to PATH, or to stdout if given bare")
    args = parser.parse_args(argv)
    if args.reference_run_dir is None or args.candidate_run_dir is None:
        parser.error("--reference-run-dir and --candidate-run-dir are both required")
    args.timers = tuple(args.timers) if args.timers else DEFAULT_TIMERS
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = build_result(args)
    except DataError as exc:
        result = empty_result(args.dump_format)
        result["error"] = str(exc)

    write_report(result, sys.stderr)
    if args.json is not None:
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.json == "-":
            sys.stdout.write(payload)
        else:
            Path(args.json).write_text(payload)

    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "ERROR": EXIT_ERROR}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
