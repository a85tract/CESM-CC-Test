"""Tests for correctness/check_validation_md.py.

Synthetic git repositories and hand-written manifests only — no product
checkout, no network, no NetCDF. The point of this tool is catching a claim
that has drifted from the code, so most of what is exercised here is the
distance between a validated commit and HEAD.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "correctness"))

import check_validation_md  # noqa: E402


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(("git", "-C", str(repo)) + args,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def product(tmp_path):
    """A product checkout with three commits, and its evidence package."""
    repo = tmp_path / "PyCAM5"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    shas = []
    for n in range(3):
        (repo / "f.txt").write_text("%d\n" % n)
        git(repo, "add", "f.txt")
        git(repo, "commit", "-q", "-m", "commit %d" % n)
        shas.append(git(repo, "rev-parse", "HEAD"))
    evidence = tmp_path / "evidence" / "pycam5" / "unreleased-abcdef12"
    evidence.mkdir(parents=True)
    return repo, shas, tmp_path / "evidence", evidence


def write_manifest(evidence_dir: Path, commit: str, result: str = "PASS") -> None:
    (evidence_dir / "manifest.json").write_text(json.dumps({
        "artifact": {"name": "PyCAM5", "commit": commit},
        "result": result,
    }))


def write_validation(repo: Path, commit: str, result: str = "PASS",
                     drift: int = None, evidence_link: str = "https://example.invalid/e",
                     ) -> Path:
    lines = [
        "# Validation Status",
        "",
        "| | |",
        "|---|---|",
        "| Validated commit | `%s` |" % commit,
        "| Result | %s |" % result,
        "| Evidence | %s |" % evidence_link,
        "",
    ]
    if drift is not None:
        lines.append("> Current HEAD is %d commits ahead of the validated commit." % drift)
    path = repo / "VALIDATION.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def run(validation_file, repo, evidence_root, product_name="pycam5", strict=False):
    argv = ["--validation-file", str(validation_file), "--repo", str(repo),
            "--evidence-root", str(evidence_root), "--product", product_name]
    if strict:
        argv.append("--strict")
    return check_validation_md.main(argv)


def test_claim_matching_head_is_clean(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    vf = write_validation(repo, shas[-1][:8])
    assert run(vf, repo, root) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_undeclared_drift_is_a_warning_with_the_real_count(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[0])
    vf = write_validation(repo, shas[0][:8])
    assert run(vf, repo, root) == 0             # a warning alone is not a failure
    out = capsys.readouterr().out
    assert "WARNING" in out and "2 commit(s) ahead" in out


def test_undeclared_drift_fails_under_strict(product):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[0])
    vf = write_validation(repo, shas[0][:8])
    assert run(vf, repo, root, strict=True) == 1


def test_correctly_declared_drift_is_clean(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[0])
    vf = write_validation(repo, shas[0][:8], drift=2)
    assert run(vf, repo, root) == 0
    assert "0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_a_stale_drift_count_is_an_error(product, capsys):
    """A wrong number reads as reassurance, so it is worse than none."""
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[0])
    vf = write_validation(repo, shas[0][:8], drift=1)
    assert run(vf, repo, root) == 1
    assert "the real distance is 2" in capsys.readouterr().out


def test_declared_drift_when_the_commit_is_head_is_an_error(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    vf = write_validation(repo, shas[-1][:8], drift=3)
    assert run(vf, repo, root) == 1
    assert "the validated commit is HEAD" in capsys.readouterr().out


def test_result_disagreeing_with_the_manifest_is_an_error(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1], result="FAIL")
    vf = write_validation(repo, shas[-1][:8], result="PASS")
    assert run(vf, repo, root) == 1
    assert "The manifest" in capsys.readouterr().out


def test_commit_absent_from_the_product_repo_is_an_error(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, "0" * 40)
    vf = write_validation(repo, "0" * 40)
    assert run(vf, repo, root) == 1
    assert "does not resolve" in capsys.readouterr().out


def test_manifest_recording_a_different_commit_is_an_error(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[0])
    vf = write_validation(repo, shas[-1][:8], drift=0)
    ret = run(vf, repo, root)
    assert ret == 1
    assert "records" in capsys.readouterr().out


def test_missing_evidence_link_is_a_warning(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    vf = write_validation(repo, shas[-1][:8], evidence_link="TBD")
    assert run(vf, repo, root) == 0
    assert "no evidence link" in capsys.readouterr().out


def test_absent_validation_file_is_exit_2(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    assert run(repo / "nope.md", repo, root) == 2
    assert "nothing was checked" in capsys.readouterr().err


def test_no_evidence_for_the_product_is_exit_2(product, capsys):
    """Absent evidence is not a passing claim — it is an unverifiable one."""
    repo, shas, root, evidence = product
    (evidence / "manifest.json").unlink(missing_ok=True)
    vf = write_validation(repo, shas[-1][:8])
    assert run(vf, repo, root) == 2
    assert "nothing was checked" in capsys.readouterr().err


def test_unknown_product_is_exit_2(product):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    vf = write_validation(repo, shas[-1][:8])
    assert run(vf, repo, root, product_name="freecam") == 2


def test_a_table_without_the_required_rows_is_exit_2(product, capsys):
    repo, shas, root, evidence = product
    write_manifest(evidence, shas[-1])
    vf = repo / "VALIDATION.md"
    vf.write_text("# Validation Status\n\n| | |\n|---|---|\n| Platform | Derecho |\n")
    assert run(vf, repo, root) == 2
    assert "Validated commit" in capsys.readouterr().err
