#!/usr/bin/env python3
"""Validate evidence manifests — schema plus the invariants JSON Schema can't express.

This is the CI entry point. It runs on committed manifests in seconds and needs
no HPC access, no model output, and no network beyond the repository itself.
It is the whole of what GitHub Actions can honestly check about a validation
run (see docs/VALIDATION-ARCHITECTURE.md §4, adjustment A).

Usage
-----
    verify_evidence.py [PATH ...]      # defaults to every manifest under evidence/
    verify_evidence.py --strict        # treat warnings and skipped checks as errors
    verify_evidence.py --base-ref REF  # enables the append-only check (invariant 8)
    verify_evidence.py --artifact-checkout NAME=DIR   # enables invariant 4

Exit 0 when every manifest passes, 1 when any error is reported, and 2 when the
verification could not be carried out at all — no jsonschema, no readable
manifest, no manifest matching the paths given. That third code is the point:
reporting "0 errors" for a run that checked nothing would be exactly the false
assurance this repository's schema exists to prevent.

Step 1 — schema
---------------
Loads ../schemas/evidence-manifest.v1.json and ../schemas/acceptance.v1.json into
one registry (the manifest $refs the acceptance schema by $id, so a validator
given only one of them will try to resolve the other over the network and fail).
../schemas/test_schemas.py shows the same two-line setup.

Step 2 — cross-field invariants
-------------------------------
The authoritative list is in ../schemas/README.md; the two are kept in step.
As of schema v1:

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
   10. security.scanned_commit equals artifact.commit.
   11. security.status is PASS only when all three scans ran and every count
       is zero.

  Warnings
   12. evidence_class: reconstructed — a format example, not compliance evidence.
   13. outputs.files is empty — no fingerprint retained.
   14. outputs.retention is unknown — no purge date recorded.
   15. security.status is NOT_RUN or INCOMPLETE.
   16. security.scans.secrets.target_config is false.
   17. security.scans.vulnerabilities.vex_applied is false.

Invariants 4, 5 and 8 need something this tool is not always given — the product
checkout, a manifest that actually lives under evidence/, the base branch. Each
is then reported as SKIP with the reason, never quietly counted as passing.
In CI, pass --base-ref so invariant 8 runs; locally it is expected to skip.

Output
------
One line per finding as `path: LEVEL: message`, then a summary count. A manifest
that fails schema validation is reported and skipped for the invariant pass —
invariants must not be attempted against a document whose shape is unknown.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"
REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_PASS, EXIT_FINDINGS, EXIT_INCOMPLETE = 0, 1, 2

ERROR, WARNING, SKIP = "ERROR", "WARNING", "SKIP"


class Findings:
    """Collected findings for one run, in the order they were made."""

    def __init__(self) -> None:
        self.items: List[Tuple[str, str, str]] = []

    def add(self, path: str, level: str, message: str) -> None:
        self.items.append((path, level, message))

    def count(self, level: str) -> int:
        return sum(1 for _, item_level, _ in self.items if item_level == level)


def load_validator():
    """The two schemas in one registry, or None when jsonschema is absent."""
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
    except ImportError:
        return None
    manifest_schema = json.loads((SCHEMA_DIR / "evidence-manifest.v1.json").read_text())
    acceptance_schema = json.loads((SCHEMA_DIR / "acceptance.v1.json").read_text())
    registry = Registry().with_resources([
        (manifest_schema["$id"], Resource.from_contents(manifest_schema)),
        (acceptance_schema["$id"], Resource.from_contents(acceptance_schema)),
    ])
    return Draft202012Validator(manifest_schema, registry=registry)


def git_has_commit(repo: Path, commit: str) -> Optional[bool]:
    """True/False, or None when the question could not be asked."""
    if not (repo / ".git").exists():
        return None
    try:
        subprocess.check_call(
            ["git", "-C", str(repo), "cat-file", "-e", "%s^{commit}" % commit],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False
    except OSError:
        return None


# --------------------------------------------------------------------------
# invariants


def check_checks_match_rules(manifest: dict, report) -> None:
    """Invariant 1."""
    for index, case in enumerate(manifest.get("cases", [])):
        rules = (case.get("acceptance") or {}).get("rules") or []
        checks = (case.get("result") or {}).get("checks") or []
        where = "cases[%d] (%s)" % (index, case.get("id"))
        if len(rules) != len(checks):
            report(ERROR, "%s: %d acceptance rules but %d recorded checks"
                          % (where, len(rules), len(checks)))
            continue
        for position, (rule, check) in enumerate(zip(rules, checks)):
            if rule.get("check") != check.get("check"):
                report(ERROR, "%s: check %d is %r but rule %d is %r"
                              % (where, position, check.get("check"),
                                 position, rule.get("check")))
            if bool(rule.get("gating")) != bool(check.get("gating")):
                report(ERROR, "%s: check %d (%s) records gating=%s, the rule says %s"
                              % (where, position, check.get("check"),
                                 check.get("gating"), rule.get("gating")))


def check_case_status(manifest: dict, report) -> None:
    """Invariant 2."""
    for index, case in enumerate(manifest.get("cases", [])):
        result = case.get("result") or {}
        status = result.get("status")
        where = "cases[%d] (%s)" % (index, case.get("id"))
        gating = [c for c in result.get("checks") or [] if c.get("gating")]
        any_failed = any(c.get("passed") is False for c in gating)
        if status == "PASS" and any_failed:
            report(ERROR, "%s: status PASS with a failing gating check" % where)
        if status == "FAIL" and not any_failed:
            report(ERROR, "%s: status FAIL but every gating check passed" % where)
        if status == "ERROR" and not result.get("error"):
            report(ERROR, "%s: status ERROR without an error message" % where)


def check_rollup(manifest: dict, report) -> None:
    """Invariant 3."""
    statuses = [(c.get("result") or {}).get("status") for c in manifest.get("cases", [])]
    expected = "ERROR" if "ERROR" in statuses else ("FAIL" if "FAIL" in statuses else "PASS")
    if manifest.get("result") != expected:
        report(ERROR, "result is %r but the case statuses %s roll up to %r"
                      % (manifest.get("result"), statuses, expected))


def check_artifact_commit(manifest: dict, report, checkouts: Dict[str, Path]) -> None:
    """Invariant 4."""
    artifact = manifest.get("artifact") or {}
    name = artifact.get("name")
    checkout = checkouts.get(name)
    if checkout is None:
        report(SKIP, "artifact.commit not resolved: no --artifact-checkout %s=DIR" % name)
        return
    resolved = git_has_commit(checkout, artifact.get("commit", ""))
    if resolved is None:
        report(SKIP, "artifact.commit not resolved: %s is not a git checkout" % checkout)
    elif not resolved:
        report(ERROR, "artifact.commit %s does not resolve in %s"
                      % (artifact.get("commit"), checkout))


def check_version_directory(manifest: dict, path: Path, report) -> None:
    """Invariant 5."""
    try:
        relative = path.resolve().relative_to(EVIDENCE_DIR)
    except ValueError:
        report(SKIP, "version directory not checked: %s is not under evidence/" % path)
        return
    if len(relative.parts) < 3:
        report(ERROR, "%s is not at evidence/<product>/<version>/manifest.json" % path)
        return
    directory = relative.parts[1]
    version = (manifest.get("artifact") or {}).get("version")
    if directory != version:
        report(ERROR, "artifact.version %r but the directory is evidence/%s/%s/"
                      % (version, relative.parts[0], directory))


def check_benchmarks(manifest: dict, report) -> None:
    """Invariant 6."""
    for index, case in enumerate(manifest.get("cases", [])):
        benchmark = case.get("benchmark") or ""
        where = "cases[%d] (%s)" % (index, case.get("id"))
        path = REPO_ROOT / benchmark
        if not path.is_file():
            report(ERROR, "%s: benchmark %s does not exist in this repository"
                          % (where, benchmark))
            continue
        if path.stem != case.get("id"):
            report(ERROR, "%s: benchmark file stem is %r, case id is %r"
                          % (where, path.stem, case.get("id")))


def check_cc_test_commit(manifest: dict, report) -> None:
    """Invariant 7."""
    commit = (manifest.get("cc_test") or {}).get("commit", "")
    resolved = git_has_commit(REPO_ROOT, commit)
    if resolved is None:
        report(SKIP, "cc_test.commit not resolved: %s is not a git checkout" % REPO_ROOT)
    elif not resolved:
        report(ERROR, "cc_test.commit %s does not resolve in this repository" % commit)


def check_append_only(paths: List[Path], base_ref: Optional[str], findings: Findings) -> None:
    """Invariant 8, asked once for the whole evidence tree rather than per manifest."""
    if not base_ref:
        for path in paths:
            findings.add(str(path), SKIP, "append-only not checked: no --base-ref given")
        return
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-status", base_ref, "--",
             str(EVIDENCE_DIR.relative_to(REPO_ROOT))],
            text=True, stderr=subprocess.STDOUT)
    except (OSError, subprocess.CalledProcessError) as exc:
        for path in paths:
            findings.add(str(path), SKIP, "append-only not checked: %s" % exc)
        return
    changed = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changed[parts[-1]] = parts[0][0]
    verbs = {"M": "modified", "D": "deleted", "R": "renamed"}
    for name, status in sorted(changed.items()):
        if status in verbs:
            findings.add(str(REPO_ROOT / name), ERROR,
                         "evidence/ is append-only: %s was %s relative to %s"
                         % (name, verbs[status], base_ref))


def check_provisional_statistical(manifest: dict, report) -> None:
    """Invariant 9."""
    for index, case in enumerate(manifest.get("cases", [])):
        acceptance = case.get("acceptance") or {}
        if acceptance.get("kind") != "statistical":
            continue
        if acceptance.get("status") == "provisional":
            report(ERROR,
                   "cases[%d] (%s): statistical acceptance is still provisional "
                   "(decision D4); evidence may not be filed against it"
                   % (index, case.get("id")))


def check_security(manifest: dict, report) -> None:
    """Invariants 10, 11, 15, 16, 17."""
    security = manifest.get("security") or {}
    status = security.get("status")
    if status == "NOT_RUN":
        report(WARNING, "security.status is NOT_RUN: the validated code was not scanned")
        return
    artifact_commit = (manifest.get("artifact") or {}).get("commit")
    scanned = security.get("scanned_commit")
    if scanned != artifact_commit:
        report(ERROR, "security.scanned_commit %s is not artifact.commit %s: the Cyber "
                      "verdict describes different code than the correctness verdict"
                      % (scanned, artifact_commit))
    scans = security.get("scans") or {}
    secrets = scans.get("secrets") or {}
    vulnerabilities = scans.get("vulnerabilities") or {}
    audit = scans.get("ai_audit") or {}
    all_ran = (secrets.get("state") == "scanned"
               and vulnerabilities.get("state") == "scanned"
               and audit.get("state") == "reviewed")
    all_zero = (not secrets.get("findings")
                and not vulnerabilities.get("critical")
                and not vulnerabilities.get("high")
                and not audit.get("high_findings"))
    if status == "PASS" and not (all_ran and all_zero):
        report(ERROR, "security.status is PASS but the scans do not support it "
                      "(states %s/%s/%s, counts %s/%s/%s/%s)"
                      % (secrets.get("state"), vulnerabilities.get("state"),
                         audit.get("state"), secrets.get("findings"),
                         vulnerabilities.get("critical"), vulnerabilities.get("high"),
                         audit.get("high_findings")))
    if status == "INCOMPLETE":
        report(WARNING, "security.status is INCOMPLETE: the validated code was not "
                        "fully scanned")
    if secrets.get("target_config") is False:
        report(WARNING, "the secret scan used default rules with no project allowlist")
    if vulnerabilities.get("vex_applied") is False:
        report(WARNING, "the CVE counts include findings nobody has assessed as "
                        "not-affected")


def check_soft(manifest: dict, report) -> None:
    """Warnings 12, 13, 14."""
    if manifest.get("evidence_class") == "reconstructed":
        report(WARNING, "evidence_class is reconstructed: a format example, not "
                        "compliance evidence")
    for index, case in enumerate(manifest.get("cases", [])):
        outputs = case.get("outputs") or {}
        where = "cases[%d] (%s)" % (index, case.get("id"))
        if not outputs.get("files"):
            report(WARNING, "%s: outputs.files is empty, so no fingerprint was retained"
                            % where)
        if (outputs.get("retention") or "").strip().lower() == "unknown":
            report(WARNING, "%s: outputs.retention is unknown, so no purge date was "
                            "recorded" % where)


# --------------------------------------------------------------------------
# driver


def discover(paths: List[str]) -> List[Path]:
    if not paths:
        return sorted(EVIDENCE_DIR.glob("*/*/manifest.json"))
    found: List[Path] = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            found.extend(sorted(path.glob("**/manifest.json")))
        else:
            found.append(path)
    return found


def verify(path: Path, validator, findings: Findings, checkouts: Dict[str, Path]) -> None:
    label = str(path)

    def report(level: str, message: str) -> None:
        findings.add(label, level, message)

    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        report(ERROR, "cannot read manifest: %s" % exc)
        return

    schema_errors = sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))
    if schema_errors:
        for error in schema_errors:
            report(ERROR, "schema: %s: %s"
                          % ("/".join(str(p) for p in error.path) or "<root>", error.message))
        report(SKIP, "invariants not checked: the document does not match the schema")
        return

    check_checks_match_rules(manifest, report)
    check_case_status(manifest, report)
    check_rollup(manifest, report)
    check_artifact_commit(manifest, report, checkouts)
    check_version_directory(manifest, path, report)
    check_benchmarks(manifest, report)
    check_cc_test_commit(manifest, report)
    check_provisional_statistical(manifest, report)
    check_security(manifest, report)
    check_soft(manifest, report)


def parse_args(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Validate evidence manifests against the schema and the "
                    "invariants JSON Schema cannot express.")
    parser.add_argument("paths", nargs="*",
                        help="manifest files or directories (default: evidence/*/*/manifest.json)")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings and skipped checks as errors")
    parser.add_argument("--base-ref",
                        help="base branch/ref, which enables the append-only check")
    parser.add_argument("--artifact-checkout", action="append", metavar="NAME=DIR",
                        help="product checkout for resolving artifact.commit; repeatable")
    args = parser.parse_args(argv)
    checkouts: Dict[str, Path] = {}
    for item in args.artifact_checkout or []:
        name, sep, directory = item.partition("=")
        if not sep or not name or not directory:
            parser.error("--artifact-checkout expects NAME=DIR, got %r" % item)
        checkouts[name] = Path(directory)
    args.artifact_checkout = checkouts
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    validator = load_validator()
    if validator is None:
        print("verify_evidence: jsonschema is not installed, so nothing was verified.",
              file=sys.stderr)
        print("verify_evidence:   python3 -m venv .venv && .venv/bin/pip install jsonschema",
              file=sys.stderr)
        return EXIT_INCOMPLETE

    paths = discover(args.paths)
    missing = [p for p in paths if not p.is_file()]
    for path in missing:
        print("%s: ERROR: no such manifest" % path)
    paths = [p for p in paths if p.is_file()]
    if not paths:
        print("verify_evidence: no manifest to verify%s. Nothing was checked, which is "
              "not the same as a clean run." % (" under %s" % EVIDENCE_DIR
                                                if not args.paths else ""),
              file=sys.stderr)
        return EXIT_INCOMPLETE

    findings = Findings()
    for path in paths:
        verify(path, validator, findings, args.artifact_checkout)
    check_append_only(paths, args.base_ref, findings)

    for label, level, message in findings.items:
        print("%s: %s: %s" % (label, level, message))

    errors = findings.count(ERROR) + len(missing)
    warnings = findings.count(WARNING)
    skipped = findings.count(SKIP)
    print("verify_evidence: %d manifest(s), %d error(s), %d warning(s), %d skipped check(s)%s"
          % (len(paths), errors, warnings, skipped, " [strict]" if args.strict else ""))
    if errors or (args.strict and (warnings or skipped)):
        return EXIT_FINDINGS
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
