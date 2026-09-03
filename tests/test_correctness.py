#!/usr/bin/env python3
"""Tests for the Correctness half.

Synthetic inputs only: `.npz` and text tables, never NetCDF, so the suite runs
in a bare checkout with no NCO, no netCDF4 and no xarray. That is deliberate —
the tools have to be exercisable where they are reviewed, not only where they
are run.

Every tool is covered for all three outcomes it can report: a clean pass, a
finding, and a comparison that could not be carried out. The last one is the
point of the suite: the failure mode this repository's schema exists to prevent
is an absent comparison filed as a passing one, so each tool is tested for
saying ERROR / exit 2 rather than PASS when it had nothing to compare.

    python -m pytest tests/test_correctness.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# verify_evidence validates against the schemas with jsonschema, the one
# dependency the README's install line names; without it the verifier
# answers 2 ("nothing was verified") and every exit-code assertion below
# would read as a defect in the tools rather than in the environment.
pytest.importorskip("jsonschema", reason="the Correctness half needs jsonschema installed")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "correctness"))

import compare_runpair  # noqa: E402
import compare_stats  # noqa: E402
import dataio  # noqa: E402
import make_manifest  # noqa: E402
import verify_evidence  # noqa: E402


# --------------------------------------------------------------------------
# synthetic inputs


def write_run(directory: Path, files: dict, timers: dict = None) -> Path:
    """A run directory of `case.cam.<key>.npz` outputs plus GPTL timing."""
    directory.mkdir(parents=True, exist_ok=True)
    for key, variables in files.items():
        np.savez(directory / ("case.cam.%s.npz" % key), **variables)
    if timers:
        timing = directory / "timing"
        timing.mkdir(exist_ok=True)
        lines = ["name on processes threads count walltotal wallmax wallmin"]
        for name, value in timers.items():
            # extract_timer reads field 6, as the PyCAM5 script did.
            lines.append('  "%s" 128 1 4 0.0 0.0 %r 0.0' % (name, value))
        (timing / "cesm_timing_stats").write_text("\n".join(lines) + "\n")
    return directory


def field(values, dtype=float):
    return np.array(values, dtype=dtype)


BITWISE_RULES = [
    {"check": "file_set_equal", "scope": "*.cam.{h0,r,rh0,rs}.*", "gating": True},
    {"check": "numeric_md5_equal", "scope": "*.cam.{h0,r,rh0,rs}.*",
     "dump_format": "%+.17g", "dump_tool": "numpy", "gating": True},
    {"check": "char_diff_count", "expect": 0, "gating": False,
     "note": "character variables carry timestamps; reported, not gated"},
    {"check": "timing_delta_pct", "timers": ["physpkg_st1"], "gating": False,
     "note": "performance is reported alongside correctness and never gates it"},
]


def benchmark_document(case_id: str, rules=None) -> dict:
    return {
        "id": case_id,
        "product": "pycam5",
        "description": "synthetic case for the test suite",
        "case": {"compset": "F2000", "resolution": "f09_f09", "duration": "6 months",
                 "ranks": 128},
        "reference": {"model": "iCESM1.3.1_fzhu CAM",
                      "provenance": "pristine native baseline, no SourceMods"},
        "acceptance": {"kind": "bitwise", "rules": rules or BITWISE_RULES},
    }


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo)] + list(args), text=True).strip()


def init_repo(path: Path, remote: str = None) -> str:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "test")
    (path / "README.md").write_text("test\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "base")
    if remote:
        git(path, "remote", "add", "origin", remote)
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throwaway CC-Test checkout and a throwaway product checkout.

    The tools resolve benchmarks, evidence and cc_test.commit against the
    repository root, so the tests give them a real one rather than reaching
    into the developer's own working tree.
    """
    cc_test = tmp_path / "cc-test"
    cc_commit = init_repo(cc_test)
    product = tmp_path / "PyCAM5"
    artifact_commit = init_repo(product, "git@github.com:a85tract/PyCAM5.git")

    monkeypatch.setattr(make_manifest, "REPO_ROOT", cc_test)
    monkeypatch.setattr(verify_evidence, "REPO_ROOT", cc_test)
    monkeypatch.setattr(verify_evidence, "EVIDENCE_DIR", cc_test / "evidence")

    return {
        "root": tmp_path,
        "cc_test": cc_test,
        "cc_commit": cc_commit,
        "product": product,
        "artifact_commit": artifact_commit,
        "version": "unreleased-%s" % artifact_commit[:8],
    }


def make_benchmark(workspace, case_id: str, rules=None, suffix: str = ".json") -> Path:
    directory = workspace["cc_test"] / "benchmarks" / "pycam5"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (case_id + suffix)
    path.write_text(json.dumps(benchmark_document(case_id, rules), indent=2))
    return directory


# --------------------------------------------------------------------------
# compare_runpair


def test_identical_runs_pass(tmp_path):
    variables = {"T": field([1.0, 2.0, 3.0]), "case_name": np.array(["pi"])}
    write_run(tmp_path / "ref", {"h0.0001-01": variables}, {"physpkg_st1": 10.0})
    write_run(tmp_path / "cand", {"h0.0001-01": variables}, {"physpkg_st1": 11.0})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"),
        "--timer", "physpkg_st1", "--json", str(out)])

    assert code == 0
    result = json.loads(out.read_text())
    assert result["status"] == "PASS"
    assert result["file_set"]["equal"] is True
    assert result["dump_tool"] == "numpy"
    assert result["dump_format"] == "%+.17g"
    entry, = result["files"]
    assert entry["key"] == "h0.0001-01.npz"
    assert entry["numeric_equal"] is True
    assert entry["numeric_count"] == 1 and entry["char_count"] == 1
    assert entry["numeric_md5_reference"] == entry["numeric_md5_candidate"]
    assert len(entry["numeric_md5_reference"]) == 32
    detail, = result["field_detail"]
    assert detail["variable"] == "T" and detail["equal"] is True
    assert detail["max_abs"] == 0.0 and detail["max_rel"] == 0.0
    assert result["timing"]["physpkg_st1"]["delta_pct"] == pytest.approx(10.0)


def test_differing_values_fail_with_field_detail(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0, 2.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0, 2.5])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 1
    result = json.loads(out.read_text())
    assert result["status"] == "FAIL"
    assert result["files"][0]["numeric_equal"] is False
    detail, = result["field_detail"]
    assert detail["equal"] is False
    assert detail["max_abs"] == pytest.approx(0.5)
    assert detail["max_rel"] == pytest.approx(0.25)


def test_char_difference_is_reported_but_does_not_gate(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0]),
                                                "date_written": np.array(["2026-06-16"])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0]),
                                                 "date_written": np.array(["2026-09-03"])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 0, "character differences must not affect the exit code"
    result = json.loads(out.read_text())
    assert result["status"] == "PASS"
    assert result["files"][0]["char_diff_count"] == 1
    assert result["files"][0]["char_diff_vars"] == ["date_written"]


def test_file_set_mismatch_is_error_not_fail(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0])},
                                 "h0.0001-02": {"T": field([1.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 2
    result = json.loads(out.read_text())
    assert result["status"] == "ERROR"
    assert result["file_set"]["equal"] is False
    assert result["file_set"]["reference_only"] == ["h0.0001-02.npz"]
    assert "file set mismatch" in result["error"]
    assert result["files"] == []


def test_no_files_in_scope_is_error(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "cand").mkdir()
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 2
    assert "no output files in scope" in json.loads(out.read_text())["error"]


def test_differing_variable_sets_are_error(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0]), "Q": field([2.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 2
    result = json.loads(out.read_text())
    assert result["status"] == "ERROR"
    assert "different variables" in result["error"]


def test_shape_change_is_a_difference_not_an_absent_comparison(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0, 1.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0, 1.0, 1.0])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 1
    result = json.loads(out.read_text())
    assert result["status"] == "FAIL"
    assert result["field_detail"][0]["max_abs"] is None
    assert "shape differs" in result["field_detail"][0]["note"]


def test_missing_timer_is_a_note_not_a_failure(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0])}})
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(out)])

    assert code == 0
    result = json.loads(out.read_text())
    assert result["timing"] == {}
    assert any("not compared" in note for note in result["notes"])


def test_hidden_native_codon_aliases_still_work(tmp_path):
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0])}})

    assert compare_runpair.main([
        "--native-run-dir", str(tmp_path / "ref"),
        "--codon-run-dir", str(tmp_path / "cand")]) == 0


def test_unreadable_netcdf_is_error(tmp_path):
    for name in ("ref", "cand"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "case.cam.h0.0001-01.nc").write_bytes(b"not really netcdf")
    out = tmp_path / "result.json"

    code = compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"),
        "--dump-tool", "numpy", "--json", str(out)])

    assert code == 2
    assert json.loads(out.read_text())["status"] == "ERROR"


def test_text_table_inputs_compare(tmp_path):
    for name, second in (("ref", "2.0"), ("cand", "2.0")):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "case.cam.h0.0001-01.txt").write_text(
            "# a table\nT Q label\n1.0 %s alpha\n3.0 4.0 beta\n" % second)

    assert compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand")]) == 0


# --------------------------------------------------------------------------
# compare_stats


def statistical(rules) -> dict:
    return {"kind": "statistical", "status": "provisional", "rules": rules}


REL_RULE = {"check": "relative_diff_max", "variables": ["T"], "norm": "l2",
            "tolerance": 1.24e-6, "gating": True}
SPREAD_RULE = {"check": "within_ensemble_spread", "variables": ["T"], "members": 3,
               "spread_metric": "stddev", "spread_multiplier": 2.0, "gating": True}


def write_source(path: Path, **variables) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, **variables)
    return path


def test_relative_diff_within_tolerance_passes(tmp_path):
    reference = write_source(tmp_path / "ref.npz", T=field([1.0, 2.0, 3.0]))
    candidate = write_source(tmp_path / "cand.npz", T=field([1.0, 2.0, 3.0 + 1e-9]))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([REL_RULE])))
    out = tmp_path / "stats.json"

    code = compare_stats.main([
        "--reference", str(reference), "--candidate", str(candidate),
        "--acceptance", str(acceptance), "--json", str(out)])

    assert code == 0
    result = json.loads(out.read_text())
    assert result["status"] == "PASS"
    rule, = result["rules"]
    assert rule["passed"] is True
    assert rule["variables"]["T"]["relative"] < 1.24e-6
    assert any("provisional" in note for note in result["notes"])


def test_relative_diff_beyond_tolerance_fails(tmp_path):
    reference = write_source(tmp_path / "ref.npz", T=field([1.0, 1.0, 1.0, 1.0]))
    candidate = write_source(tmp_path / "cand.npz", T=field([1.001, 1.001, 1.001, 1.001]))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([REL_RULE])))
    out = tmp_path / "stats.json"

    code = compare_stats.main([
        "--reference", str(reference), "--candidate", str(candidate),
        "--acceptance", str(acceptance), "--json", str(out)])

    assert code == 1
    result = json.loads(out.read_text())
    assert result["status"] == "FAIL"
    # normwise ratio, the D4 reading recorded in the module docstring
    assert result["rules"][0]["variables"]["T"]["relative"] == pytest.approx(1e-3, rel=1e-6)


def test_absent_variable_is_error_not_a_skipped_pass(tmp_path):
    reference = write_source(tmp_path / "ref.npz", T=field([1.0]))
    candidate = write_source(tmp_path / "cand.npz", Q=field([1.0]))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([REL_RULE])))
    out = tmp_path / "stats.json"

    code = compare_stats.main([
        "--reference", str(reference), "--candidate", str(candidate),
        "--acceptance", str(acceptance), "--json", str(out)])

    assert code == 2
    result = json.loads(out.read_text())
    assert result["status"] == "ERROR"
    assert "absent from the candidate" in result["error"]


def test_ensemble_spread_pass_and_fail(tmp_path):
    members = [write_source(tmp_path / ("m%d.npz" % i), T=field([value]))
               for i, value in enumerate((1.0, 2.0, 3.0))]
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([SPREAD_RULE])))

    inside = write_source(tmp_path / "inside.npz", T=field([2.5]))
    argv = ["--acceptance", str(acceptance), "--candidate", str(inside)]
    for member in members:
        argv += ["--reference", str(member)]
    assert compare_stats.main(argv) == 0

    outside = write_source(tmp_path / "outside.npz", T=field([99.0]))
    argv = ["--acceptance", str(acceptance), "--candidate", str(outside)]
    for member in members:
        argv += ["--reference", str(member)]
    out = tmp_path / "stats.json"
    assert compare_stats.main(argv + ["--json", str(out)]) == 1
    assert json.loads(out.read_text())["rules"][0]["variables"]["T"]["outside"] == 1


def test_too_few_ensemble_members_is_error(tmp_path):
    members = [write_source(tmp_path / ("m%d.npz" % i), T=field([value]))
               for i, value in enumerate((1.0, 2.0))]
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([SPREAD_RULE])))
    candidate = write_source(tmp_path / "cand.npz", T=field([1.5]))
    argv = ["--acceptance", str(acceptance), "--candidate", str(candidate)]
    for member in members:
        argv += ["--reference", str(member)]
    out = tmp_path / "stats.json"

    assert compare_stats.main(argv + ["--json", str(out)]) == 2
    assert "ensemble needs 3 members" in json.loads(out.read_text())["error"]


def test_bitwise_acceptance_is_refused_by_compare_stats(tmp_path):
    reference = write_source(tmp_path / "ref.npz", T=field([1.0]))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"kind": "bitwise", "rules": BITWISE_RULES}))

    assert compare_stats.main([
        "--reference", str(reference), "--candidate", str(reference),
        "--acceptance", str(acceptance)]) == 2


def test_zero_reference_norm_demands_exact_equality(tmp_path):
    reference = write_source(tmp_path / "ref.npz", T=field([0.0, 0.0]))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps(statistical([REL_RULE])))

    same = write_source(tmp_path / "same.npz", T=field([0.0, 0.0]))
    assert compare_stats.main([
        "--reference", str(reference), "--candidate", str(same),
        "--acceptance", str(acceptance)]) == 0

    tiny = write_source(tmp_path / "tiny.npz", T=field([0.0, 1e-30]))
    assert compare_stats.main([
        "--reference", str(reference), "--candidate", str(tiny),
        "--acceptance", str(acceptance)]) == 1


# --------------------------------------------------------------------------
# make_manifest and the round trip through verify_evidence


def run_pair(tmp_path, reference_values, candidate_values, timers=True) -> Path:
    timing = {"physpkg_st1": 10.0} if timers else None
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field(reference_values)}}, timing)
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field(candidate_values)}},
              {"physpkg_st1": 10.5} if timers else None)
    out = tmp_path / "case.json"
    compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"),
        "--timer", "physpkg_st1", "--json", str(out)])
    return out


def manifest_argv(workspace, case_json: Path, extra=None) -> list:
    out = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
           / "manifest.json")
    return [
        "--case", "pi-6month=%s" % case_json,
        "--benchmark-dir", str(workspace["cc_test"] / "benchmarks" / "pycam5"),
        "--artifact-repo", str(workspace["product"]),
        "--outputs-location", "/glade/derecho/scratch/test/case/run",
        "--machine", "derecho", "--no-probe",
        "--out", str(out),
    ] + (extra or [])


def test_round_trip_pass(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0, 2.0], [1.0, 2.0])

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 0

    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")
    manifest = json.loads(path.read_text())
    assert manifest["result"] == "PASS"
    assert manifest["schema_version"] == "1.0"
    assert manifest["artifact"]["repo"] == "https://github.com/a85tract/PyCAM5"
    assert manifest["artifact"]["commit"] == workspace["artifact_commit"]
    assert manifest["artifact"]["version"] == workspace["version"]
    assert manifest["cc_test"]["commit"] == workspace["cc_commit"]
    assert manifest["evidence_class"] == "reconstructed"  # no compiler was captured
    assert manifest["security"] == {"gate": "hpc-devsecops", "status": "NOT_RUN"}

    case, = manifest["cases"]
    assert case["benchmark"] == "benchmarks/pycam5/pi-6month.json"
    assert case["ranks"] == 128 and case["duration"] == "6 months"
    checks = case["result"]["checks"]
    rules = case["acceptance"]["rules"]
    assert [c["check"] for c in checks] == [r["check"] for r in rules]
    assert [c["gating"] for c in checks] == [r["gating"] for r in rules]
    assert checks[3]["passed"] is None  # unbounded timing reaches no verdict

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "ERROR" not in out
    assert "WARNING" in out  # reconstructed, empty outputs, unknown retention, NOT_RUN


def test_round_trip_fail(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0, 2.0], [1.0, 9.0])

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 1

    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")
    manifest = json.loads(path.read_text())
    assert manifest["result"] == "FAIL"
    case, = manifest["cases"]
    assert case["result"]["status"] == "FAIL"
    assert case["result"]["checks"][1]["passed"] is False
    assert case["result"]["checks"][0]["passed"] is True

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 0, "a FAIL manifest is still valid evidence"
    assert "ERROR" not in capsys.readouterr().out


def test_round_trip_error(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    write_run(tmp_path / "ref", {"h0.0001-01": {"T": field([1.0])},
                                 "h0.0001-02": {"T": field([1.0])}})
    write_run(tmp_path / "cand", {"h0.0001-01": {"T": field([1.0])}})
    case_json = tmp_path / "case.json"
    assert compare_runpair.main([
        "--reference-run-dir", str(tmp_path / "ref"),
        "--candidate-run-dir", str(tmp_path / "cand"), "--json", str(case_json)]) == 2

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 2

    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")
    manifest = json.loads(path.read_text())
    assert manifest["result"] == "ERROR"
    case, = manifest["cases"]
    assert case["result"]["status"] == "ERROR"
    assert "file set mismatch" in case["result"]["error"]
    # A gating check may not carry a null verdict, so it is written false with
    # the reason; the ERROR status is what says it was never evaluated.
    assert case["result"]["checks"][0]["passed"] is False
    assert case["result"]["checks"][1]["passed"] is False
    assert "could not be evaluated" in case["result"]["checks"][1]["detail"]

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 0
    assert "ERROR" not in capsys.readouterr().out


def test_gating_rule_with_no_measurement_is_error(workspace, tmp_path):
    rules = list(BITWISE_RULES[:2]) + [
        {"check": "timing_delta_pct", "timers": ["physpkg_st1"], "max_abs_pct": 5.0,
         "gating": True}]
    make_benchmark(workspace, "pi-6month", rules)
    case_json = run_pair(tmp_path, [1.0], [1.0], timers=False)

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 2

    manifest = json.loads((workspace["cc_test"] / "evidence" / "pycam5"
                           / workspace["version"] / "manifest.json").read_text())
    case, = manifest["cases"]
    assert case["result"]["status"] == "ERROR"
    assert "timers not measured" in case["result"]["error"]
    assert case["result"]["checks"][2]["passed"] is False


def test_scope_matching_no_files_is_error(workspace, tmp_path):
    rules = [
        {"check": "file_set_equal", "scope": "*.cam.h0.*", "gating": True},
        {"check": "numeric_md5_equal", "scope": "*.cam.rs.*.nc",
         "dump_format": "%+.17g", "gating": True},
    ]
    make_benchmark(workspace, "pi-6month", rules)
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 2
    manifest = json.loads((workspace["cc_test"] / "evidence" / "pycam5"
                           / workspace["version"] / "manifest.json").read_text())
    assert "matched none of the" in manifest["cases"][0]["result"]["error"]


def test_complete_evidence_class_refuses_to_invent_provenance(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(
        manifest_argv(workspace, case_json, ["--evidence-class", "complete"])) == 2
    assert not (workspace["cc_test"] / "evidence").exists()
    assert "reference.commit_or_tag" in capsys.readouterr().err


def test_complete_evidence_class_when_provenance_is_present(workspace, tmp_path):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json, [
        "--reference-commit", "abc1234",
        "--env", "compiler=ifx 2025.2.1",
        "--evidence-class", "complete"])) == 0

    manifest = json.loads((workspace["cc_test"] / "evidence" / "pycam5"
                           / workspace["version"] / "manifest.json").read_text())
    assert manifest["evidence_class"] == "complete"
    assert manifest["environment"]["compiler"] == "ifx 2025.2.1"
    assert manifest["reference"]["commit_or_tag"] == "abc1234"


def test_outputs_are_fingerprinted_when_the_data_is_still_there(workspace, tmp_path):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json, [
        "--case-outputs", "pi-6month=%s" % (tmp_path / "cand")])) == 0

    manifest = json.loads((workspace["cc_test"] / "evidence" / "pycam5"
                           / workspace["version"] / "manifest.json").read_text())
    files = manifest["cases"][0]["outputs"]["files"]
    assert [f["name"] for f in files] == ["h0.0001-01.npz"]
    assert len(files[0]["md5"]) == 32 and files[0]["bytes"] > 0


def test_purged_outputs_warn_rather_than_fail(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json, [
        "--case-outputs", "pi-6month=%s" % (tmp_path / "gone")])) == 0
    assert "no fingerprint retained" in capsys.readouterr().err


def test_security_summary_is_translated_and_a_commit_mismatch_is_caught(
        workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({
        "tool": "hpc-devsecops", "status": "INCOMPLETE",
        "commit": "0" * 40, "timestamp": "20260903T000000Z-1",
        "scans": {
            "secrets": {"state": "passed", "findings": 0},
            "cve": {"state": "unavailable", "critical": 0, "high": 0},
            "ai_audit": {"state": "not_configured", "high": 0},
        }}))

    assert make_manifest.main(manifest_argv(workspace, case_json, [
        "--security-summary", str(summary),
        "--security-timestamp", "2026-09-03T00:00:00Z"])) == 0
    assert "scanned 00000000" in capsys.readouterr().err

    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")
    security = json.loads(path.read_text())["security"]
    assert security["status"] == "INCOMPLETE"
    assert security["scans"]["secrets"]["state"] == "scanned"
    assert security["scans"]["vulnerabilities"]["state"] == "not_installed"
    assert security["scans"]["ai_audit"]["state"] == "unreviewed"
    assert security["scans"]["secrets"]["target_config"] is False

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 1
    assert "is not artifact.commit" in capsys.readouterr().out


def test_missing_benchmark_writes_nothing(workspace, tmp_path, capsys):
    (workspace["cc_test"] / "benchmarks" / "pycam5").mkdir(parents=True)
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 2
    assert "no benchmark for case" in capsys.readouterr().err
    assert not (workspace["cc_test"] / "evidence").exists()


def test_missing_comparator_result_writes_nothing(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")

    assert make_manifest.main(
        manifest_argv(workspace, tmp_path / "absent.json")) == 2
    assert "no comparator result" in capsys.readouterr().err


def test_yaml_benchmark_is_read_when_pyyaml_is_installed(workspace, tmp_path):
    pytest.importorskip("yaml")
    import yaml

    directory = workspace["cc_test"] / "benchmarks" / "pycam5"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pi-6month.yaml").write_text(yaml.safe_dump(benchmark_document("pi-6month")))
    case_json = run_pair(tmp_path, [1.0], [1.0])

    assert make_manifest.main(manifest_argv(workspace, case_json)) == 0
    manifest = json.loads((workspace["cc_test"] / "evidence" / "pycam5"
                           / workspace["version"] / "manifest.json").read_text())
    assert manifest["cases"][0]["benchmark"] == "benchmarks/pycam5/pi-6month.yaml"


def test_summary_markdown_is_written_on_request(workspace, tmp_path):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    summary = workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"] / "summary.md"

    assert make_manifest.main(manifest_argv(workspace, case_json,
                                            ["--summary", str(summary)])) == 0
    text = summary.read_text()
    assert "| Result | **PASS** |" in text
    assert "`numeric_md5_equal`" in text


# --------------------------------------------------------------------------
# verify_evidence on its own


def test_no_manifests_is_incomplete_not_clean(workspace, capsys):
    (workspace["cc_test"] / "evidence").mkdir()
    assert verify_evidence.main([]) == 2
    assert "Nothing was checked" in capsys.readouterr().err


def test_strict_promotes_warnings(workspace, tmp_path):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")

    assert verify_evidence.main([str(path)]) == 0
    assert verify_evidence.main([str(path), "--strict"]) == 1


def test_tampered_result_is_caught(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0, 9.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")

    manifest = json.loads(path.read_text())
    manifest["result"] = "PASS"
    manifest["cases"][0]["result"]["status"] = "PASS"
    path.write_text(json.dumps(manifest))

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 1
    assert "status PASS with a failing gating check" in capsys.readouterr().out


def test_gating_flag_must_match_the_benchmark_rule(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")

    manifest = json.loads(path.read_text())
    manifest["cases"][0]["result"]["checks"][2]["gating"] = True
    path.write_text(json.dumps(manifest))

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 1
    assert "the rule says False" in capsys.readouterr().out


def test_version_directory_must_match(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    original = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"])
    moved = original.parent / "v9.9.9"
    original.rename(moved)

    capsys.readouterr()
    assert verify_evidence.main([str(moved / "manifest.json")]) == 1
    assert "the directory is evidence/pycam5/v9.9.9/" in capsys.readouterr().out


def test_provisional_statistical_acceptance_is_rejected(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")

    manifest = json.loads(path.read_text())
    case = manifest["cases"][0]
    case["acceptance"] = statistical([REL_RULE])
    case["result"]["checks"] = [{"check": "relative_diff_max", "gating": True,
                                 "passed": True, "detail": "l2 relative 0"}]
    path.write_text(json.dumps(manifest))

    capsys.readouterr()
    assert verify_evidence.main([str(path)]) == 1
    assert "still provisional" in capsys.readouterr().out


def test_append_only_catches_a_modified_manifest(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")
    git(workspace["cc_test"], "add", ".")
    git(workspace["cc_test"], "commit", "-qm", "evidence")
    base = git(workspace["cc_test"], "rev-parse", "HEAD")

    capsys.readouterr()
    assert verify_evidence.main([str(path), "--base-ref", base]) == 0

    manifest = json.loads(path.read_text())
    manifest["notes"] = "edited after the fact"
    path.write_text(json.dumps(manifest))

    capsys.readouterr()
    assert verify_evidence.main([str(path), "--base-ref", base]) == 1
    assert "append-only" in capsys.readouterr().out


def test_append_only_is_skipped_not_passed_without_a_base_ref(workspace, tmp_path, capsys):
    make_benchmark(workspace, "pi-6month")
    case_json = run_pair(tmp_path, [1.0], [1.0])
    make_manifest.main(manifest_argv(workspace, case_json))
    path = (workspace["cc_test"] / "evidence" / "pycam5" / workspace["version"]
            / "manifest.json")

    capsys.readouterr()
    verify_evidence.main([str(path)])
    assert "SKIP: append-only not checked" in capsys.readouterr().out


def test_schema_failure_skips_the_invariant_pass(workspace, tmp_path, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": "1.0", "verdict": "PASS"}))

    assert verify_evidence.main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "schema:" in out
    assert "invariants not checked" in out


def test_the_shipped_format_example_is_not_accepted_as_evidence(capsys):
    """The example manifest is schema-legal but names benchmarks that do not exist yet."""
    example = ROOT / "schemas" / "examples" / "example-bitwise.manifest.json"

    assert verify_evidence.main([str(example)]) == 1
    out = capsys.readouterr().out
    assert "does not exist in this repository" in out
    assert "reconstructed" in out


# --------------------------------------------------------------------------
# dataio and scope matching


def test_brace_expansion_and_scope_matching():
    assert make_manifest.expand_braces("*.cam.{h0,r}.*.nc") == [
        "*.cam.h0.*.nc", "*.cam.r.*.nc"]
    assert make_manifest.in_scope("h0.0001-01.nc", "*.cam.{h0,r,rh0,rs}.*.nc")
    assert not make_manifest.in_scope("h0.0001-01.nc", "*.cam.rs.*.nc")
    assert make_manifest.in_scope("anything", None)


def test_cam_key_strips_the_case_name():
    assert dataio.cam_key(Path("b.e13.pi.cam.h0.0001-01.nc")) == "h0.0001-01.nc"
    assert dataio.cam_key(Path("rpointer.atm")) is None


def test_reading_a_file_with_no_variables_raises(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("")
    with pytest.raises(dataio.DataError):
        dataio.read_variables(path)


def test_dump_is_stable_and_format_sensitive(tmp_path):
    path = write_source(tmp_path / "a.npz", T=field([1.0 / 3.0, 2.0 / 7.0]))
    default = dataio.ArrayReader(path).numeric_digest(["T"])
    coarse = dataio.ArrayReader(path, "%+.3g").numeric_digest(["T"])
    assert default == dataio.ArrayReader(path).numeric_digest(["T"])
    assert default != coarse, "a digest must depend on the dump format it records"
