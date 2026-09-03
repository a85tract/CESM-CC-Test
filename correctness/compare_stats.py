#!/usr/bin/env python3
"""Compare a reference/candidate run pair — statistical acceptance (Pipeline 2).

Pipeline 2 (jax-kernels, numba-kernels, pyphys-bridge) does not reproduce the
Fortran bit for bit, so `compare_runpair.py` does not apply. Its criteria are
statistical — the dashboard records figures like "1.24e-6 relative difference"
for Held-Suarez and "within ensemble spread" for TJ2016.

Decision D4 is still open, and this module does not close it
------------------------------------------------------------
Those dashboard figures are results, not criteria. Making them executable needs
four things nobody has agreed yet: the tolerance AND the norm it applies to, the
compared variable set and whether every variable must pass, the ensemble member
count and what "within spread" means, and whether the comparison covers the
whole field or a region or a time mean.

`../schemas/acceptance.v1.json` therefore still marks statistical acceptance
`"status": "provisional"`, and `verify_evidence.py` still rejects any manifest
that uses it. That has NOT changed: this tool computes and reports, but no
evidence package built on it is accepted while the marker stands. Removing the
marker from the schema is D4's to do, not this module's.

What this module does instead is refuse to leave the semantics unstated. Each
reading below is the most conservative one available — the one least likely to
call something a PASS that a stricter reading would fail — is named here, and is
recorded in `../docs/VALIDATION-ARCHITECTURE.md` §8 as "decided by
implementation on 2026-09-03, revisit if wrong".

The readings
------------
1.  **Variable set.** Every variable named by the rule must be present in both
    the reference and the candidate, and EVERY one must pass. No aggregate, no
    average over variables, no skipping a variable that is absent — an absent
    variable is ERROR, because a rule that silently compared fewer variables
    than it names would report a PASS for a comparison that did not happen.

2.  **The norm is applied normwise to the difference field, relative to the
    reference field**, per variable, over the whole array:

        l2    ||cand - ref||_2   / ||ref||_2
        rmse  rms(cand - ref)    / rms(ref)
        linf  max|cand - ref|    / max|ref|

    As ratios, `l2` and `rmse` are arithmetically the same number (the element
    count cancels); both are kept because the rule records which norm was
    declared, and the absolute norm reported alongside differs. The elementwise
    alternative, max_i |d_i| / |ref_i|, is stricter still but is dominated by
    near-zero reference elements, which is why it was not chosen; if D4 wants
    it, this is the line to change.

3.  **Degenerate denominator.** When the reference norm is zero, the rule passes
    only if the difference is exactly zero. No epsilon is added to the
    denominator, because that turns "nothing to compare against" into a pass.

4.  **Scope is the whole field**, every time level, no regional subsetting and
    no time mean. Averaging is what would let a large local error hide.

5.  **Non-finite elements.** If the two fields have the same non-finite mask
    (CAM fill values, say), those elements are excluded from the norms and the
    excluded count is reported. If the masks differ, that is a real difference
    between the runs and the rule FAILs. Non-finite values are never treated as
    equal to each other by default.

6.  **Ensemble spread** is elementwise, and the candidate must be inside the
    band at EVERY element. Fewer members than the rule requires is ERROR, not a
    smaller ensemble silently accepted. With `spread_multiplier` m:

        stddev  mean ± m · population stddev (ddof = 0 — the smaller estimate,
                so the band is the tighter one)
        minmax  midpoint of the member envelope ± m · half its width
        iqr     median ± m · half the interquartile range

    A zero-width band admits only exact equality. No tolerance is added to the
    band edges: `<=` and `>=` are taken literally.

Exit codes and JSON follow `compare_runpair.py`. One difference, and it is
inherent: a bitwise comparison has a criterion of its own (identical or not),
a statistical one does not, so this tool must be given the acceptance block —
`--acceptance` is required. Its exit code reflects every declared rule
regardless of `gating`; `gating` belongs to the manifest, and the verdict that
honours it is the one `make_manifest.py` writes.

    0 PASS   every declared rule passed
    1 FAIL   at least one declared rule failed
    2 ERROR  at least one rule could not be evaluated

Usage
-----
    compare_stats.py --reference PATH [--reference PATH]... \
                     --candidate PATH --acceptance BENCHMARK_OR_ACCEPTANCE \
                     [--json [PATH]]

A PATH is one data file, or a directory whose data files are merged into one
variable namespace. `--reference` repeated supplies the ensemble members for
`within_ensemble_spread`; `relative_diff_max` requires exactly one reference.
`--reference-run-dir` / `--candidate-run-dir` are accepted as aliases so the
two comparators can be driven the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import dataio
from dataio import DataError

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def rule_key(rule: dict) -> str:
    """Identity of an acceptance rule, ignoring `gating` and `note`.

    `make_manifest.py` matches a benchmark rule to the measurement this tool
    produced by this key rather than by list position, so a benchmark edited
    between the comparison and the manifest is caught as an unevaluable rule
    instead of quietly binding a verdict to the wrong criterion.
    """
    body = {k: v for k, v in rule.items() if k not in ("gating", "note")}
    return json.dumps(body, sort_keys=True)


class Unevaluable(Exception):
    """The rule could not be evaluated. Becomes ERROR, never FAIL and never PASS."""


def _norm(values, norm: str) -> float:
    np = dataio._numpy()
    flat = np.asarray(values, dtype=float).reshape(-1)
    if flat.size == 0:
        return 0.0
    if norm == "linf":
        return float(np.abs(flat).max())
    if norm == "l2":
        return float(np.sqrt((flat * flat).sum()))
    if norm == "rmse":
        return float(np.sqrt((flat * flat).mean()))
    raise Unevaluable("unknown norm %r" % norm)


def _aligned(name: str, reference, candidate):
    """Reference and candidate flattened onto their shared finite elements."""
    np = dataio._numpy()
    ref = np.asarray(reference)
    cand = np.asarray(candidate)
    if ref.shape != cand.shape:
        raise Unevaluable(
            "%s: shapes differ (%s vs %s), no difference field exists"
            % (name, tuple(ref.shape), tuple(cand.shape)))
    ref = ref.astype(float).reshape(-1)
    cand = cand.astype(float).reshape(-1)
    ref_finite = np.isfinite(ref)
    cand_finite = np.isfinite(cand)
    if not np.array_equal(ref_finite, cand_finite):
        return None, None, int((ref_finite != cand_finite).sum())
    return ref[ref_finite], cand[ref_finite], int((~ref_finite).sum())


def evaluate_relative_diff_max(rule: dict, references: List[dict], candidate: dict) -> dict:
    if len(references) != 1:
        raise Unevaluable(
            "relative_diff_max needs exactly one reference, %d were given"
            % len(references))
    reference = references[0]
    norm = rule["norm"]
    tolerance = float(rule["tolerance"])
    measured: Dict[str, dict] = {}
    passed = True
    for name in rule["variables"]:
        if name not in reference or name not in candidate:
            raise Unevaluable(
                "%s: absent from the %s"
                % (name, "reference" if name not in reference else "candidate"))
        ref, cand, excluded = _aligned(name, reference[name], candidate[name])
        if ref is None:
            measured[name] = {
                "relative": None, "absolute": None, "tolerance": tolerance,
                "norm": norm, "passed": False, "excluded": excluded,
                "detail": "non-finite masks differ at %d elements" % excluded,
            }
            passed = False
            continue
        diff_norm = _norm(cand - ref, norm)
        ref_norm = _norm(ref, norm)
        if ref_norm == 0.0:
            relative = 0.0 if diff_norm == 0.0 else None
            ok = diff_norm == 0.0
            detail = ("reference norm is zero; exact equality required, "
                      "difference norm %g" % diff_norm)
        else:
            relative = diff_norm / ref_norm
            ok = relative <= tolerance
            detail = "%s relative %.6g vs tolerance %.6g" % (norm, relative, tolerance)
        measured[name] = {
            "relative": relative, "absolute": diff_norm, "tolerance": tolerance,
            "norm": norm, "passed": bool(ok), "excluded": excluded, "detail": detail,
        }
        passed = passed and ok
    worst = max(
        (m["relative"] for m in measured.values() if m["relative"] is not None),
        default=None)
    return {
        "passed": bool(passed),
        "detail": "%d variables, worst %s relative %s (tolerance %g)"
                  % (len(measured), norm,
                     "%.6g" % worst if worst is not None else "n/a", tolerance),
        "variables": measured,
    }


def evaluate_within_ensemble_spread(rule: dict, references: List[dict], candidate: dict) -> dict:
    np = dataio._numpy()
    required = int(rule["members"])
    if len(references) < required:
        raise Unevaluable(
            "ensemble needs %d members, %d references were given"
            % (required, len(references)))
    metric = rule["spread_metric"]
    multiplier = float(rule.get("spread_multiplier", 1.0))
    measured: Dict[str, dict] = {}
    passed = True
    for name in rule["variables"]:
        if name not in candidate:
            raise Unevaluable("%s: absent from the candidate" % name)
        missing = [i for i, member in enumerate(references) if name not in member]
        if missing:
            raise Unevaluable(
                "%s: absent from ensemble members %s"
                % (name, ", ".join(str(i) for i in missing)))
        cand = np.asarray(candidate[name], dtype=float)
        stack = []
        for index, member in enumerate(references):
            array = np.asarray(member[name], dtype=float)
            if array.shape != cand.shape:
                raise Unevaluable(
                    "%s: member %d has shape %s, candidate has %s"
                    % (name, index, tuple(array.shape), tuple(cand.shape)))
            stack.append(array)
        members = np.stack(stack, axis=0)
        if not np.isfinite(members).all() or not np.isfinite(cand).all():
            raise Unevaluable(
                "%s: non-finite values in the ensemble or the candidate; the "
                "spread band is undefined" % name)

        if metric == "stddev":
            center = members.mean(axis=0)
            half = multiplier * members.std(axis=0, ddof=0)
        elif metric == "minmax":
            low, high = members.min(axis=0), members.max(axis=0)
            center = (low + high) / 2.0
            half = multiplier * (high - low) / 2.0
        elif metric == "iqr":
            q1 = np.percentile(members, 25, axis=0)
            q3 = np.percentile(members, 75, axis=0)
            center = np.median(members, axis=0)
            half = multiplier * (q3 - q1) / 2.0
        else:
            raise Unevaluable("unknown spread_metric %r" % metric)

        inside = (cand >= center - half) & (cand <= center + half)
        outside = int((~inside).sum())
        excess = np.abs(cand - center) - half
        worst = float(excess.max()) if excess.size else 0.0
        ok = outside == 0
        measured[name] = {
            "members": len(references), "spread_metric": metric,
            "spread_multiplier": multiplier, "elements": int(cand.size),
            "outside": outside, "worst_excess": worst, "passed": bool(ok),
            "detail": "%d/%d elements outside the band, worst excess %.6g"
                      % (outside, cand.size, worst),
        }
        passed = passed and ok
    return {
        "passed": bool(passed),
        "detail": "%d variables, %d members, %s band x%g"
                  % (len(measured), len(references), metric, multiplier),
        "variables": measured,
    }


EVALUATORS = {
    "relative_diff_max": evaluate_relative_diff_max,
    "within_ensemble_spread": evaluate_within_ensemble_spread,
}


def load_acceptance(path: Path) -> dict:
    """The acceptance block, from a benchmark file or from a bare block."""
    document = dataio.load_document(path)
    acceptance = document.get("acceptance", document)
    if not isinstance(acceptance, dict) or "rules" not in acceptance:
        raise DataError("%s holds no acceptance block with rules" % path)
    if acceptance.get("kind") != "statistical":
        raise DataError(
            "%s declares acceptance kind %r; compare_stats.py evaluates "
            "'statistical' only (use compare_runpair.py for 'bitwise')"
            % (path, acceptance.get("kind")))
    return acceptance


def build_result(args) -> dict:
    result = {
        "status": "ERROR",
        "kind": "statistical",
        "files": [],
        "timing": {},
        "rules": [],
        "notes": [],
    }
    acceptance = load_acceptance(args.acceptance)
    if acceptance.get("status") == "provisional":
        result["notes"].append(
            "acceptance is marked provisional (decision D4): verify_evidence.py "
            "rejects any manifest that uses it")

    references = [dataio.load_source(path) for path in args.reference]
    candidate = dataio.load_source(args.candidate)

    errors: List[str] = []
    failures = 0
    for rule in acceptance["rules"]:
        entry = {
            "key": rule_key(rule),
            "check": rule.get("check"),
            "passed": None,
            "detail": "",
            "variables": {},
        }
        evaluator = EVALUATORS.get(rule.get("check"))
        if evaluator is None:
            entry["detail"] = "no evaluator for check %r" % rule.get("check")
            errors.append(entry["detail"])
        else:
            try:
                entry.update(evaluator(rule, references, candidate))
            except Unevaluable as exc:
                entry["detail"] = "not evaluated: %s" % exc
                errors.append("%s: %s" % (rule.get("check"), exc))
        result["rules"].append(entry)
        if entry["passed"] is False:
            failures += 1

    if errors:
        result["error"] = "; ".join(errors)
        return result
    result["status"] = "FAIL" if failures else "PASS"
    return result


def write_report(result: dict, stream) -> None:
    for entry in result["rules"]:
        print("=== %s ===" % entry["check"], file=stream)
        print("passed=%s" % entry["passed"], file=stream)
        print("detail=%s" % entry["detail"], file=stream)
        for name, measured in sorted(entry["variables"].items()):
            print("  %s: %s" % (name, measured["detail"]), file=stream)
        print(file=stream)
    for note in result["notes"]:
        print("note: %s" % note, file=stream)
    print("status=%s" % result["status"], file=stream)
    if result.get("error"):
        print("error: %s" % result["error"], file=stream)


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Compare a reference/candidate run pair (statistical acceptance).")
    # No list default: argparse's append action would share one list across calls.
    parser.add_argument("--reference", action="append", type=Path,
                        help="reference data source; repeat for ensemble members")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--reference-run-dir", action="append", type=Path,
                        dest="reference", help=argparse.SUPPRESS)
    parser.add_argument("--candidate-run-dir", type=Path, dest="candidate",
                        help=argparse.SUPPRESS)
    parser.add_argument("--acceptance", type=Path, required=True,
                        help="benchmark file, or a bare acceptance block (YAML or JSON)")
    parser.add_argument("--json", nargs="?", const="-", metavar="PATH",
                        help="write the JSON result to PATH, or to stdout if given bare")
    args = parser.parse_args(argv)
    if not args.reference or args.candidate is None:
        parser.error("--reference (at least one) and --candidate are required")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = build_result(args)
    except DataError as exc:
        result = {
            "status": "ERROR", "error": str(exc), "kind": "statistical",
            "files": [], "timing": {}, "rules": [], "notes": [],
        }

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
