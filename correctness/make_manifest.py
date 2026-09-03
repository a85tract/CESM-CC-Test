#!/usr/bin/env python3
"""Assemble an evidence manifest from comparator output plus environment probes.

Migration step 3; see ../docs/VALIDATION-ARCHITECTURE.md.

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
  --reference-model     baseline identity; --reference-commit, --reference-provenance
  --outputs-location    absolute path on HPC storage
  --outputs-retention   retention class and expected purge date
  --security-summary    summary.json from tools/devsecops-local.sh
  --out PATH            where to write manifest.json

Every value comes from the benchmark, the comparator, a probe, or an explicit
flag. Nothing is defaulted into existence: a field that could not be
established is left out and pulls `evidence_class` down to `reconstructed`.

What it fills in and how
------------------------
`artifact`      from the product checkout: remote URL, HEAD, and a version. No
                product repo has cut a tag yet, so the version falls back to the
                D2 bridge form `unreleased-<commit[:8]>` unless HEAD is on a
                `vX.Y.Z` tag.
`cc_test`       this repository's own HEAD and version, same bridge rule.
`environment`   probes the machine: compiler (`ifx --version`), MPI, python,
                codon, cuda, loaded modules. `machine` is required; a probe that
                finds nothing omits its field rather than writing "unknown".
`cases[]`       one per --case. `acceptance` is copied from the benchmark file
                (that file is the source of truth for the criteria, not this
                tool); `result` comes from the comparator JSON.
`outputs`       location, retention, and per-file md5 + byte counts of the
                candidate output. May be empty if the data was already purged —
                the verifier warns, it is not an error.
`security`      from the Cyber gate's summary.json, with its per-scan states
                mapped onto the schema's vocabulary. With no summary the block
                is `{"gate": ..., "status": "NOT_RUN"}` — absence is not an
                available answer, so the manifest says the gate did not run.
`result`        rolled up: ERROR if any case errored, else FAIL if any failed,
                else PASS.

Two invariants this tool is responsible for
-------------------------------------------
1. `result.checks[]` corresponds one-to-one and in order with the benchmark's
   `acceptance.rules[]` — same check name, same `gating` value. That
   correspondence is what lets a reader reconstruct why a PASS is a PASS. The
   comparator reports what it measured; this tool decides which of those
   measurements gated, by reading the benchmark.
2. `evidence_class` is `complete` only when every provenance field was actually
   captured. When backfilling a historical run whose compiler version or
   reference commit is no longer recoverable, it emits `reconstructed` and
   leaves those fields out. It never invents a plausible value to satisfy the
   schema — a reconstructed manifest is a format example, and the verifier says
   so. `--evidence-class complete` with provenance missing is an error, not a
   promotion.

A rule the comparator did not measure
-------------------------------------
A rule whose measurement is absent (a scope that matched no file, a gating timer
missing from `cesm_timing_stats`, a statistical rule the comparator was not
given) is *unevaluable*. It never becomes a pass:

  - gating and unevaluable  -> the case is ERROR, and the check is written
    `passed: false` with `detail` naming the reason. The schema forbids `null`
    on a gating check, and ERROR plus the message is what distinguishes this
    from a comparison that ran and failed.
  - not gating and unevaluable -> `passed: null` with the reason in `detail`,
    which is what null is for.

Exit codes match the comparators: 0 PASS, 1 FAIL, 2 ERROR — the manifest's own
rolled-up result. 2 is also returned when no manifest could be assembled at all
(missing benchmark, unreadable comparator JSON, provenance that would have to be
invented); in that case nothing is written.

Usage
-----
    make_manifest.py --case pi-6month-allcodon=pi.json \
                     --case mco-6month-allcodon=mco.json \
                     --benchmark-dir benchmarks/pycam5 \
                     --artifact-repo ~/PyCAM5 \
                     --outputs-location /glade/derecho/scratch/me/pi/run \
                     --outputs-retention "scratch, purged ~2026-12-01" \
                     --out evidence/pycam5/unreleased-e8d68996/manifest.json
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import dataio
from compare_stats import rule_key
from dataio import DataError

SCHEMA_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2

TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.]+)?$")

# tools/devsecops-local.sh scan states -> the manifest's vocabulary. The runner
# reports what happened; the schema names the states, and a state it does not
# name must not be squeezed into "scanned".
SCAN_STATE = {
    "passed": "scanned", "findings": "scanned",
    "unavailable": "not_installed", "not_installed": "not_installed",
    "error": "failed", "failed": "failed",
    "skipped": "skipped", "skipped_by_user": "skipped", "not_configured": "skipped",
}
AI_STATE = {
    "reviewed": "reviewed", "findings": "reviewed",
    "unavailable": "unreviewed", "not_configured": "unreviewed",
    "unreviewed": "unreviewed", "error": "error",
    "skipped": "skipped", "skipped_by_user": "skipped",
}
GATE_STATUS = {"PASS": "PASS", "FINDINGS": "FAIL", "INCOMPLETE": "INCOMPLETE",
               "NOT_RUN": "NOT_RUN"}


class BuildError(Exception):
    """The manifest could not be assembled. Nothing is written; exit 2."""


# --------------------------------------------------------------------------
# scope matching


def expand_braces(pattern: str) -> List[str]:
    """`a.{h0,r}.nc` -> ['a.h0.nc', 'a.r.nc']. Recursive, left to right."""
    start = pattern.find("{")
    if start < 0:
        return [pattern]
    end = pattern.find("}", start)
    if end < 0:
        return [pattern]
    head, body, tail = pattern[:start], pattern[start + 1:end], pattern[end + 1:]
    out: List[str] = []
    for option in body.split(","):
        out.extend(expand_braces(head + option + tail))
    return out


def in_scope(key: str, scope: Optional[str]) -> bool:
    """Does a comparator file key fall inside an acceptance rule's scope glob?

    The rule's scope is written against the run directory's file names
    (`*.cam.{h0,r,rh0,rs}.*.nc`) while a comparator key has the case name
    stripped (`h0.0001-01.nc`), so the key is matched both bare and with a
    representative case prefix put back.
    """
    if not scope:
        return True
    for pattern in expand_braces(scope):
        if fnmatch.fnmatch(key, pattern) or fnmatch.fnmatch("case.cam." + key, pattern):
            return True
    return False


# --------------------------------------------------------------------------
# rule evaluation


class Unevaluable(Exception):
    """The rule has no measurement behind it. Never a pass, never a plain fail."""


def _bitwise_check(rule: dict, comparison: dict) -> Tuple[Optional[bool], str]:
    check = rule.get("check")
    files = comparison.get("files") or []

    if check == "file_set_equal":
        file_set = comparison.get("file_set")
        if file_set is None:
            raise Unevaluable("the comparator reported no file_set result")
        extra = []
        if file_set.get("reference_only"):
            extra.append("missing from candidate: %s" % ", ".join(file_set["reference_only"]))
        if file_set.get("candidate_only"):
            extra.append("missing from reference: %s" % ", ".join(file_set["candidate_only"]))
        return bool(file_set["equal"]), "; ".join(extra) or "file sets match"

    if check == "numeric_md5_equal":
        scoped = [f for f in files if in_scope(f["key"], rule.get("scope"))]
        if not scoped:
            raise Unevaluable(
                "scope %r matched none of the %d compared files"
                % (rule.get("scope"), len(files)))
        differing = [f["key"] for f in scoped if not f["numeric_equal"]]
        return (not differing), (
            "overall_numeric_equal=%s (%d files%s)"
            % (not differing, len(scoped),
               "; differ: " + ", ".join(differing) if differing else ""))

    if check == "char_diff_count":
        scoped = [f for f in files if in_scope(f["key"], rule.get("scope"))]
        if not scoped:
            raise Unevaluable(
                "scope %r matched none of the %d compared files"
                % (rule.get("scope"), len(files)))
        total = sum(f["char_diff_count"] for f in scoped)
        expect = int(rule.get("expect", 0))
        return total == expect, "char_diff_count=%d, expected %d" % (total, expect)

    if check == "timing_delta_pct":
        timing = comparison.get("timing") or {}
        missing = [t for t in rule["timers"] if t not in timing]
        bound = rule.get("max_abs_pct")
        if bound is None:
            detail = "reported without a bound"
            if missing:
                detail += "; not measured: " + ", ".join(missing)
            return None, detail
        if missing:
            raise Unevaluable("timers not measured: %s" % ", ".join(missing))
        worst = max(abs(timing[t]["delta_pct"]) for t in rule["timers"])
        return worst <= float(bound), "worst |delta_pct| %.3f vs bound %.3f" % (worst, float(bound))

    raise Unevaluable("no evaluator for check %r" % check)


def _statistical_check(rule: dict, comparison: dict) -> Tuple[Optional[bool], str]:
    measured = {entry["key"]: entry for entry in comparison.get("rules") or []}
    entry = measured.get(rule_key(rule))
    if entry is None:
        raise Unevaluable(
            "the comparator measured no rule matching %r; the benchmark and the "
            "comparison do not describe the same criterion" % rule.get("check"))
    if entry.get("passed") is None:
        raise Unevaluable(entry.get("detail") or "the comparator reached no verdict")
    return bool(entry["passed"]), entry.get("detail", "")


def evaluate_case(acceptance: dict, comparison: dict) -> dict:
    """Build cases[].result from the benchmark's rules and the comparator's output."""
    kind = acceptance.get("kind")
    evaluator = _statistical_check if kind == "statistical" else _bitwise_check

    checks: List[dict] = []
    reasons: List[str] = []
    for rule in acceptance["rules"]:
        gating = bool(rule.get("gating"))
        try:
            passed, detail = evaluator(rule, comparison)
        except Unevaluable as exc:
            reasons.append("%s: %s" % (rule.get("check"), exc))
            # A gating check may not carry a null verdict, and it did not pass;
            # the case status carries the truth that it was never evaluated.
            passed = False if gating else None
            detail = "could not be evaluated: %s" % exc
        checks.append({
            "check": rule.get("check"),
            "gating": gating,
            "passed": passed,
            "detail": detail,
        })

    result: Dict[str, object] = {"status": "PASS", "checks": checks}
    if comparison.get("files"):
        result["files"] = comparison["files"]
    if comparison.get("timing"):
        result["timing"] = comparison["timing"]

    if comparison.get("status") == "ERROR" or reasons:
        result["status"] = "ERROR"
        parts = [comparison["error"]] if comparison.get("status") == "ERROR" and comparison.get("error") else []
        parts.extend(reasons)
        result["error"] = "; ".join(parts) or "the comparison could not be carried out"
    elif any(c["gating"] and c["passed"] is False for c in checks):
        result["status"] = "FAIL"
    return result


# --------------------------------------------------------------------------
# probes


def git_output(repo: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(repo)] + list(args), text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.strip() or None


def normalise_remote(url: str) -> str:
    """git@host:owner/repo.git -> https://host/owner/repo (the schema wants a URI)."""
    match = re.match(r"^[\w.+-]+@([^:]+):(.+?)(?:\.git)?$", url)
    if match:
        return "https://%s/%s" % (match.group(1), match.group(2))
    return re.sub(r"\.git$", "", url)


def version_for(repo: Path, commit: str) -> str:
    tag = git_output(repo, "describe", "--tags", "--exact-match")
    if tag and TAG_RE.match(tag):
        return tag
    return "unreleased-%s" % commit[:8]


def probe(command: List[str], line: int = 0) -> Optional[str]:
    try:
        out = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if not lines or line >= len(lines):
        return None
    return lines[line]


def probe_environment(args) -> Dict[str, object]:
    machine = args.machine or os.environ.get("NCAR_HOST") or platform.node()
    if not machine:
        raise BuildError("could not determine the machine; pass --machine")
    environment: Dict[str, object] = {"machine": machine}
    if not args.no_probe:
        found = {
            "compiler": probe(["ifx", "--version"]),
            "mpi": probe(["mpirun", "--version"]) or probe(["mpiexec", "--version"]),
            "codon": probe(["codon", "--version"]),
            "cuda": probe(["nvcc", "--version"], line=3),
        }
        found["python"] = "%s %s" % (platform.python_implementation(),
                                     platform.python_version())
        for key, value in found.items():
            if value:
                environment[key] = value
        modules = [m for m in os.environ.get("LOADEDMODULES", "").split(":") if m]
        if modules:
            environment["modules"] = modules
    for item in args.env or []:
        key, _, value = item.partition("=")
        if not key or not value:
            raise BuildError("--env expects KEY=VALUE, got %r" % item)
        environment[key] = value
    return environment


def security_block(args, artifact_commit: str, cc_test_commit: str,
                   artifact_repo: Optional[Path]) -> Tuple[dict, List[str]]:
    """Translate the Cyber gate's summary.json into the manifest's security block."""
    warnings: List[str] = []
    if not args.security_summary:
        return {"gate": args.security_gate, "status": "NOT_RUN"}, [
            "no --security-summary: the manifest records the Cyber gate as NOT_RUN"]
    try:
        summary = json.loads(Path(args.security_summary).read_text())
    except (OSError, ValueError) as exc:
        raise BuildError("cannot read %s: %s" % (args.security_summary, exc)) from exc
    scans = summary.get("scans", {})
    secrets = scans.get("secrets", {})
    cve = scans.get("cve", scans.get("vulnerabilities", {}))
    audit = scans.get("ai_audit", {})

    scanned_commit = summary.get("commit")
    if not scanned_commit or not re.match(r"^[0-9a-f]{7,40}$", scanned_commit):
        raise BuildError(
            "%s records no usable scanned commit (%r); the security block would "
            "have to name code nobody can identify"
            % (args.security_summary, scanned_commit))
    if scanned_commit != artifact_commit:
        warnings.append(
            "the Cyber gate scanned %s but the artifact is %s; recorded as measured, "
            "and verify_evidence.py will flag it" % (scanned_commit[:8], artifact_commit[:8]))

    def has_config(relative: str) -> bool:
        return bool(artifact_repo and (artifact_repo / relative).exists())

    block = {
        "gate": summary.get("tool") or args.security_gate,
        "cc_test_commit": cc_test_commit,
        "scanned_commit": scanned_commit,
        "timestamp": args.security_timestamp or iso_now(),
        "status": GATE_STATUS.get(summary.get("status"), "INCOMPLETE"),
        "scans": {
            "secrets": {
                "tool": "gitleaks",
                "state": SCAN_STATE.get(secrets.get("state"), "failed"),
                "findings": int(secrets.get("findings") or 0),
                "target_config": has_config(".gitleaks.toml"),
            },
            "vulnerabilities": {
                "tool": "syft -> grype",
                "state": SCAN_STATE.get(cve.get("state"), "failed"),
                "critical": int(cve.get("critical") or 0),
                "high": int(cve.get("high") or 0),
                "vex_applied": has_config(".vex/openvex.json"),
            },
            "ai_audit": {
                "tool": "ai_audit.py",
                "state": AI_STATE.get(audit.get("state"), "unreviewed"),
                "high_findings": int(audit.get("high") or audit.get("high_findings") or 0),
            },
        },
    }
    if artifact_repo is None:
        warnings.append(
            "no --artifact-repo: target_config and vex_applied recorded as false "
            "because the product checkout was not available to look at")
    return block, warnings


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# assembly


def find_benchmark(benchmark_dir: Path, case_id: str) -> Path:
    for suffix in (".yaml", ".yml", ".json"):
        candidate = benchmark_dir / (case_id + suffix)
        if candidate.is_file():
            return candidate
    raise BuildError(
        "no benchmark for case %r in %s (looked for %s.yaml/.yml/.json)"
        % (case_id, benchmark_dir, case_id))


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        raise BuildError(
            "%s is outside this repository; cases[].benchmark must be a path "
            "under benchmarks/ here" % path) from None


def build_case(case_id: str, comparator_json: Path, args) -> Tuple[dict, dict, List[str]]:
    """Returns (case, the benchmark document it came from, warnings)."""
    warnings: List[str] = []
    benchmark_path = find_benchmark(args.benchmark_dir, case_id)
    benchmark = dataio.load_document(benchmark_path)
    if benchmark.get("id") and benchmark["id"] != case_id:
        raise BuildError(
            "%s declares id %r but is named for case %r"
            % (benchmark_path, benchmark["id"], case_id))
    acceptance = benchmark.get("acceptance")
    if not isinstance(acceptance, dict) or not acceptance.get("rules"):
        raise BuildError("%s holds no acceptance rules" % benchmark_path)

    if not comparator_json.is_file():
        raise BuildError("no comparator result for case %r: %s" % (case_id, comparator_json))
    try:
        comparison = json.loads(comparator_json.read_text())
    except ValueError as exc:
        raise BuildError("%s is not valid JSON: %s" % (comparator_json, exc)) from exc

    case: Dict[str, object] = {
        "id": case_id,
        "benchmark": repo_relative(benchmark_path),
        "acceptance": acceptance,
        "result": evaluate_case(acceptance, comparison),
    }
    for key in ("compset", "resolution", "duration", "ranks"):
        value = (benchmark.get("case") or {}).get(key)
        if value is None:
            continue
        if key == "ranks":
            try:
                case[key] = int(value)
            except (TypeError, ValueError):
                raise BuildError(
                    "%s: case.ranks is %r, which is not an integer"
                    % (benchmark_path, value)) from None
        else:
            case[key] = str(value)

    outputs_dir = args.case_outputs.get(case_id)
    location = args.outputs_location or (str(outputs_dir.resolve()) if outputs_dir else None)
    if not location:
        raise BuildError(
            "case %r has no outputs location; pass --outputs-location or "
            "--case-outputs %s=DIR" % (case_id, case_id))
    files: List[dict] = []
    if outputs_dir is not None:
        if outputs_dir.is_dir():
            for key, path in sorted(dataio.collect_run_files(outputs_dir).items()):
                files.append({"name": key, "md5": md5_file(path),
                              "bytes": path.stat().st_size})
            if not files:
                warnings.append(
                    "case %s: %s holds no output files in scope; no fingerprint retained"
                    % (case_id, outputs_dir))
        else:
            warnings.append(
                "case %s: %s does not exist (purged?); no fingerprint retained"
                % (case_id, outputs_dir))
    case["outputs"] = {
        "location": location,
        "retention": args.outputs_retention,
        "files": files,
    }
    if args.assets_release:
        case["outputs"]["assets_release"] = args.assets_release
    return case, benchmark, warnings


def reference_block(args, benchmarks: List[dict]) -> dict:
    """Baseline identity: the flags win, the benchmark files fill the gaps."""
    reference: Dict[str, str] = {}
    for benchmark in benchmarks:
        for key, value in (benchmark.get("reference") or {}).items():
            if key in ("model", "commit_or_tag", "provenance") and value:
                reference.setdefault(key, str(value))
    for key, value in (("model", args.reference_model),
                       ("commit_or_tag", args.reference_commit),
                       ("provenance", args.reference_provenance)):
        if value:
            reference[key] = value
    for required in ("model", "provenance"):
        if not reference.get(required):
            raise BuildError(
                "reference.%s is unknown; set --reference-%s or record it in the "
                "benchmark file. It is not something to guess at." % (required, required))
    return reference


def build_manifest(args) -> Tuple[dict, List[str]]:
    warnings: List[str] = []

    artifact_repo = args.artifact_repo.resolve() if args.artifact_repo else None
    commit = args.artifact_commit or (git_output(artifact_repo, "rev-parse", "HEAD")
                                      if artifact_repo else None)
    if not commit:
        raise BuildError(
            "could not read the artifact commit; pass --artifact-repo pointing at "
            "the product checkout, or --artifact-commit")
    remote = args.artifact_repo_url or (
        git_output(artifact_repo, "config", "--get", "remote.origin.url")
        if artifact_repo else None)
    if not remote:
        raise BuildError(
            "could not read the artifact repository URL; pass --artifact-repo-url")
    name = args.artifact_name or (artifact_repo.name if artifact_repo else None)
    if not name:
        raise BuildError("could not determine the artifact name; pass --artifact-name")

    if args.artifact_version:
        version = args.artifact_version
    elif artifact_repo:
        version = version_for(artifact_repo, commit)
    else:
        version = "unreleased-%s" % commit[:8]
    artifact = {
        "name": name,
        "repo": normalise_remote(remote),
        "commit": commit,
        "version": version,
    }

    cc_commit = git_output(REPO_ROOT, "rev-parse", "HEAD")
    if not cc_commit:
        raise BuildError(
            "%s is not a git checkout, so cc_test.commit cannot be recorded" % REPO_ROOT)
    cc_test = {"version": version_for(REPO_ROOT, cc_commit), "commit": cc_commit}

    cases: List[dict] = []
    benchmarks: List[dict] = []
    for case_id, comparator_json in args.case:
        case, benchmark, case_warnings = build_case(case_id, comparator_json, args)
        cases.append(case)
        benchmarks.append(benchmark)
        warnings.extend(case_warnings)

    reference = reference_block(args, benchmarks)
    environment = probe_environment(args)
    security, security_warnings = security_block(args, commit, cc_commit, artifact_repo)
    warnings.extend(security_warnings)

    statuses = [case["result"]["status"] for case in cases]
    if "ERROR" in statuses:
        result = "ERROR"
    elif "FAIL" in statuses:
        result = "FAIL"
    else:
        result = "PASS"

    complete = bool(reference.get("commit_or_tag")) and bool(environment.get("compiler"))
    if args.evidence_class == "complete" and not complete:
        missing = [n for n, ok in (("reference.commit_or_tag", reference.get("commit_or_tag")),
                                   ("environment.compiler", environment.get("compiler"))) if not ok]
        raise BuildError(
            "--evidence-class complete was requested but %s could not be captured. "
            "A reconstructed manifest is the honest answer; inventing a value is not."
            % " and ".join(missing))
    evidence_class = args.evidence_class if args.evidence_class != "auto" else (
        "complete" if complete else "reconstructed")
    if evidence_class == "reconstructed":
        warnings.append(
            "evidence_class is reconstructed: a format example, not compliance evidence")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "evidence_class": evidence_class,
        "artifact": artifact,
        "reference": reference,
        "cc_test": cc_test,
        "environment": environment,
        "cases": cases,
        "security": security,
        "result": result,
        "timestamp": args.timestamp or iso_now(),
    }
    if args.operator:
        manifest["operator"] = args.operator
    if args.notes:
        manifest["notes"] = args.notes

    out_version = Path(args.out).resolve().parent.name
    if out_version != artifact["version"]:
        warnings.append(
            "--out is under %r but artifact.version is %r; verify_evidence.py "
            "requires them to match" % (out_version, artifact["version"]))
    return manifest, warnings


def validate(manifest: dict) -> List[str]:
    """Schema-check before writing. A skipped validation says so; it never passes silently."""
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return ["jsonschema is not installed, so the manifest was written "
                "unvalidated; run correctness/verify_evidence.py where it is"]
    schema = json.loads((SCHEMA_DIR / "evidence-manifest.v1.json").read_text())
    acceptance = json.loads((SCHEMA_DIR / "acceptance.v1.json").read_text())
    registry = Registry().with_resources([
        (schema["$id"], Resource.from_contents(schema)),
        (acceptance["$id"], Resource.from_contents(acceptance)),
    ])
    validator = Draft202012Validator(schema, registry=registry)
    return ["schema: %s: %s" % ("/".join(str(p) for p in error.path) or "<root>", error.message)
            for error in sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))]


def write_summary(manifest: dict, path: Path) -> None:
    lines = [
        "# Validation summary — %s %s" % (manifest["artifact"]["name"],
                                          manifest["artifact"]["version"]),
        "",
        "| | |",
        "|---|---|",
        "| Artifact | `%s` @ `%s` |" % (manifest["artifact"]["repo"],
                                        manifest["artifact"]["commit"][:8]),
        "| Reference | %s%s |" % (manifest["reference"]["model"],
                                  ", " + manifest["reference"]["commit_or_tag"]
                                  if manifest["reference"].get("commit_or_tag") else ""),
        "| CC-Test | %s (`%s`) |" % (manifest["cc_test"]["version"],
                                     manifest["cc_test"]["commit"][:8]),
        "| Machine | %s |" % manifest["environment"]["machine"],
        "| Compiler | %s |" % manifest["environment"].get("compiler", "_not captured_"),
        "| Cases | %d |" % len(manifest["cases"]),
        "| Result | **%s** |" % manifest["result"],
        "| Security gate | %s |" % manifest["security"]["status"],
        "| Evidence class | %s |" % manifest["evidence_class"],
        "| Validated | %s |" % manifest["timestamp"],
        "",
        "## Cases",
        "",
    ]
    for case in manifest["cases"]:
        lines.append("### %s — %s" % (case["id"], case["result"]["status"]))
        lines.append("")
        lines.append("Criteria: `%s` (%s)" % (case["benchmark"], case["acceptance"]["kind"]))
        lines.append("")
        lines.append("| Check | Gating | Passed | Detail |")
        lines.append("|---|---|---|---|")
        for check in case["result"]["checks"]:
            lines.append("| `%s` | %s | %s | %s |" % (
                check["check"], "yes" if check["gating"] else "no",
                {True: "yes", False: "no", None: "—"}[check["passed"]],
                check.get("detail", "")))
        if case["result"].get("error"):
            lines.append("")
            lines.append("> ERROR: %s" % case["result"]["error"])
        lines.append("")
    path.write_text("\n".join(lines))


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Assemble an evidence manifest from comparator output.")
    parser.add_argument("--case", action="append", metavar="ID=PATH",
                        help="comparator JSON for one case; repeatable")
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--artifact-repo", type=Path)
    parser.add_argument("--artifact-name")
    parser.add_argument("--artifact-repo-url")
    parser.add_argument("--artifact-commit")
    parser.add_argument("--artifact-version")
    parser.add_argument("--reference-model")
    parser.add_argument("--reference-commit", metavar="COMMIT_OR_TAG")
    parser.add_argument("--reference-provenance")
    parser.add_argument("--machine")
    parser.add_argument("--env", action="append", metavar="KEY=VALUE",
                        help="environment field to set explicitly; repeatable")
    parser.add_argument("--no-probe", action="store_true",
                        help="do not run environment probes (machine still required)")
    parser.add_argument("--outputs-location")
    parser.add_argument("--outputs-retention", default="unknown",
                        help="retention class and expected purge date (default: unknown)")
    parser.add_argument("--case-outputs", action="append", metavar="ID=DIR", default=None,
                        help="candidate output directory to fingerprint; repeatable")
    parser.add_argument("--assets-release")
    parser.add_argument("--security-summary", type=Path,
                        help="summary.json from tools/devsecops-local.sh")
    parser.add_argument("--security-gate", default="hpc-devsecops")
    parser.add_argument("--security-timestamp")
    parser.add_argument("--evidence-class", default="auto",
                        choices=("auto", "complete", "reconstructed"))
    parser.add_argument("--operator")
    parser.add_argument("--notes")
    parser.add_argument("--timestamp", help="when the validation ran (ISO 8601 UTC)")
    parser.add_argument("--summary", type=Path, help="also write a summary.md here")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.case:
        parser.error("at least one --case ID=PATH is required")
    cases = []
    for item in args.case:
        case_id, sep, path = item.partition("=")
        if not sep or not case_id or not path:
            parser.error("--case expects ID=PATH, got %r" % item)
        cases.append((case_id, Path(path)))
    args.case = cases

    outputs = {}
    for item in args.case_outputs or []:
        case_id, sep, path = item.partition("=")
        if not sep or not case_id or not path:
            parser.error("--case-outputs expects ID=DIR, got %r" % item)
        outputs[case_id] = Path(path)
    args.case_outputs = outputs
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        manifest, warnings = build_manifest(args)
    except (BuildError, DataError) as exc:
        print("make_manifest: %s" % exc, file=sys.stderr)
        return EXIT_ERROR

    errors = validate(manifest)
    schema_errors = [e for e in errors if e.startswith("schema:")]
    warnings.extend(e for e in errors if not e.startswith("schema:"))
    if schema_errors:
        for error in schema_errors:
            print("make_manifest: %s" % error, file=sys.stderr)
        print("make_manifest: the manifest does not validate; nothing was written",
              file=sys.stderr)
        return EXIT_ERROR

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        write_summary(manifest, args.summary)

    for warning in warnings:
        print("make_manifest: WARNING: %s" % warning, file=sys.stderr)
    print("make_manifest: wrote %s (%d cases, result %s, security %s)"
          % (args.out, len(manifest["cases"]), manifest["result"],
             manifest["security"]["status"]), file=sys.stderr)
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL, "ERROR": EXIT_ERROR}[manifest["result"]]


if __name__ == "__main__":
    sys.exit(main())
