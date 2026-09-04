#!/usr/bin/env python3
"""Check a product's VALIDATION.md against the evidence it points at.

This is the product side of layer 2 (docs/VALIDATION-ARCHITECTURE.md §4
adjustment A, §7). `verify_evidence.py` asks whether an evidence package is
internally sound; this asks the different question of whether the product
repository's own claim still matches it.

The failure mode it exists to catch is the one named in §4: VALIDATION.md says
PASS, and points at a commit that stopped being the current code months ago.
Nothing about the evidence package is wrong in that case — the package is a
true record of a commit nobody runs any more. Only a check that reads both
sides can see it.

What it checks
--------------
  1. VALIDATION.md parses: the validated commit, the result, and the evidence
     link are all present. A file this tool cannot read is exit 2, never a pass.
  2. The validated commit resolves in the product repository. A commit that does
     not exist there is an ERROR — the claim names nothing.
  3. Drift: the validated commit is HEAD, or the file declares the drift and the
     count it declares is the real one. Undeclared drift is a WARNING with the
     true count; a declared count that is wrong is an ERROR, because a stale
     number reads as reassurance.
  4. The evidence package named by --product exists under the evidence root and
     its manifest's artifact.commit is the commit VALIDATION.md claims.
  5. The result in VALIDATION.md is the manifest's result. The manifest wins;
     this file is a copy, and a copy that disagrees is the whole problem.

Exit codes match the rest of the Correctness half: 0 clean, 1 findings, 2 the
check could not be carried out. Exit 2 covers an unreadable VALIDATION.md, an
absent product checkout, and an evidence root with no package for this product
— each of which would otherwise be reported as a clean run of nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ERROR = "ERROR"
WARNING = "WARNING"
SKIP = "SKIP"

ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$")
DRIFT = re.compile(
    r"Current HEAD is\s+(\d+)\s+commits?\s+ahead of the validated commit", re.I)
CODE = re.compile(r"`([^`]+)`")


class CheckError(Exception):
    """The check cannot be carried out — exit 2, never a silent pass."""


def parse_validation_md(text: str) -> Tuple[Dict[str, str], Optional[int]]:
    """The two-column table as a dict, plus the declared drift count if present."""
    fields: Dict[str, str] = {}
    for line in text.splitlines():
        match = ROW.match(line)
        if not match:
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        # The header separator row (|---|---|) and the empty header carry no field.
        if not key or set(key) <= set("-: "):
            continue
        fields[key.lower()] = value
    declared = DRIFT.search(text)
    return fields, (int(declared.group(1)) if declared else None)


def bare(value: str) -> str:
    """A table cell's value without the markdown backticks around it."""
    match = CODE.search(value)
    return (match.group(1) if match else value).strip()


def git(repo: Path, *args: str) -> Optional[str]:
    """A git command in `repo`, or None when git says no."""
    try:
        out = subprocess.run(("git", "-C", str(repo)) + args,
                             capture_output=True, text=True, check=False)
    except OSError as exc:                                  # git absent entirely
        raise CheckError("cannot run git: %s" % exc) from exc
    return out.stdout.strip() if out.returncode == 0 else None


def find_manifest(evidence_root: Path, product: str) -> Path:
    """The one manifest for `product`, or an explanation of why there is not one."""
    product_dir = evidence_root / product
    if not product_dir.is_dir():
        raise CheckError(
            "no evidence directory %s: VALIDATION.md claims a result for a product "
            "that has filed no evidence" % product_dir)
    manifests = sorted(product_dir.glob("*/manifest.json"))
    if not manifests:
        raise CheckError("no manifest under %s" % product_dir)
    if len(manifests) > 1:
        # Several versions is the normal end state; the claim must say which one.
        return manifests[-1]
    return manifests[0]


def check(validation_file: Path, repo: Path, evidence_root: Path,
          product: str, findings: List[Tuple[str, str]]) -> None:
    try:
        text = validation_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckError("cannot read %s: %s" % (validation_file, exc)) from exc

    fields, declared_drift = parse_validation_md(text)
    claimed_commit = bare(fields.get("validated commit", ""))
    claimed_result = bare(fields.get("result", "")).upper()
    if not claimed_commit:
        raise CheckError("%s has no 'Validated commit' row" % validation_file)
    if not claimed_result:
        raise CheckError("%s has no 'Result' row" % validation_file)

    if not (repo / ".git").exists():
        raise CheckError("%s is not a git checkout, so the claim cannot be "
                         "compared with the code" % repo)

    resolved = git(repo, "rev-parse", "--verify", "%s^{commit}" % claimed_commit)
    if resolved is None:
        findings.append((ERROR, "validated commit %s does not resolve in %s: the "
                                "claim names no code" % (claimed_commit, repo)))
        resolved = ""

    head = git(repo, "rev-parse", "HEAD") or ""
    if resolved and head:
        if resolved == head:
            if declared_drift:
                findings.append((ERROR, "VALIDATION.md declares %d commits of drift, "
                                        "but the validated commit is HEAD"
                                 % declared_drift))
        else:
            count = git(repo, "rev-list", "--count", "%s..HEAD" % resolved)
            actual = int(count) if count and count.isdigit() else None
            if actual is None:
                findings.append((WARNING, "HEAD is not the validated commit and the "
                                          "distance could not be measured"))
            elif declared_drift is None:
                findings.append((WARNING, "HEAD is %d commit(s) ahead of the validated "
                                          "commit %s and VALIDATION.md does not say so"
                                 % (actual, claimed_commit[:12])))
            elif declared_drift != actual:
                findings.append((ERROR, "VALIDATION.md declares %d commit(s) of drift; "
                                        "the real distance is %d"
                                 % (declared_drift, actual)))

    manifest_path = find_manifest(evidence_root, product)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckError("cannot read %s: %s" % (manifest_path, exc)) from exc

    artifact = (manifest.get("artifact") or {}).get("commit", "")
    if resolved and artifact:
        # The manifest carries the full sha; VALIDATION.md is allowed the short one.
        if not (artifact.startswith(claimed_commit) or resolved.startswith(artifact)):
            findings.append((ERROR, "VALIDATION.md claims commit %s but %s records %s"
                             % (claimed_commit, manifest_path, artifact[:12])))

    manifest_result = str(manifest.get("result", "")).upper()
    if manifest_result and claimed_result != manifest_result:
        findings.append((ERROR, "VALIDATION.md says %s; %s records %s. The manifest "
                                "is the authority" % (claimed_result, manifest_path,
                                                      manifest_result)))

    evidence_link = fields.get("evidence", "")
    if not evidence_link or evidence_link in {"-", "—", "TBD"}:
        findings.append((WARNING, "VALIDATION.md has no evidence link, so a reader "
                                  "cannot reach the manifest it summarises"))

    print("check_validation_md: %s vs %s" % (validation_file, manifest_path),
          file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a product's VALIDATION.md against its evidence package.")
    parser.add_argument("--validation-file", type=Path, default=Path("VALIDATION.md"))
    parser.add_argument("--repo", type=Path, default=Path("."),
                        help="the product checkout the claim is about")
    parser.add_argument("--evidence-root", type=Path, required=True,
                        help="CC-Test's evidence/ directory")
    parser.add_argument("--product", required=True,
                        help="directory name under the evidence root, e.g. pycam5")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors")
    args = parser.parse_args(argv)

    findings: List[Tuple[str, str]] = []
    try:
        check(args.validation_file, args.repo, args.evidence_root,
              args.product, findings)
    except CheckError as exc:
        print("check_validation_md: %s" % exc, file=sys.stderr)
        print("check_validation_md: nothing was checked, which is not the same as a "
              "clean run.", file=sys.stderr)
        return 2

    for level, message in findings:
        print("%s: %s: %s" % (args.validation_file, level, message))
    errors = sum(1 for level, _ in findings if level == ERROR)
    warnings = sum(1 for level, _ in findings if level == WARNING)
    print("check_validation_md: %d error(s), %d warning(s)" % (errors, warnings))
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
