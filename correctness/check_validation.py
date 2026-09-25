#!/usr/bin/env python3
"""VALIDATION.md for a product repository: render it from an acceptance record, check it against one.

Each product repository carries one short file, VALIDATION.md, that says which of its
commits was validated and links the acceptance record here. The record is the only
authority; the file is a pointer with a summary. Two things can rot: the pointer (the
record it names is gone, or says something else) and the commit (HEAD moved on and the
file still reads as current). This tool does both halves.

    check_validation.py render --manifest evidence/<product>/<version>/manifest.json
        Print VALIDATION.md for that record. Run it in this repository after filing a
        record and commit the output in the product repository.

    check_validation.py check --validation VALIDATION.md --product-repo . \
                              --evidence-dir <cc-test checkout>/evidence [--strict] [--refresh]
        Run in the product repository (CI does, through
        .github/workflows/validation-callable.yml). Exit 0 when the file agrees with the
        record and the drift line is current, 1 on a finding, 2 when nothing could be
        checked. Drift -- HEAD ahead of the validated commit -- is reported as a warning
        and stated in the file's last line; --strict makes a stale or missing drift line a
        finding, and --refresh rewrites that line in place.

The rows the check reads are `Validated commit`, `Record` and `Result`; everything else in
the table is for a reader and is not verified beyond the manifest it came from.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

EXIT_PASS, EXIT_FINDINGS, EXIT_INCOMPLETE = 0, 1, 2
CC_TEST_URL = "https://github.com/a85tract/CESM-CC-Test"

ROW = re.compile(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>.*?)\s*\|\s*$")
DRIFT = re.compile(r"^> Current HEAD is (?:the validated commit|(?P<n>\d+) commits? ahead of the validated commit)\.?\s*$")
RECORD = re.compile(r"evidence/(?P<product>[a-z0-9][a-z0-9-]*)/(?P<version>[^/\s`)]+)/?")


# --- render ---------------------------------------------------------------------


def render(manifest: dict, record_path: str) -> str:
    artifact, reference, env = manifest["artifact"], manifest["reference"], manifest["environment"]
    cases = manifest["cases"]
    statuses = [c["result"]["status"] for c in cases]
    kinds = sorted({c["acceptance"]["kind"] for c in cases})
    platform = " · ".join(
        (str(env[k]) if k in ("machine", "compiler") else "%s %s" % (k, env[k]))
        for k in ("machine", "compiler", "python", "jax", "codon", "cuda", "engine")
        if env.get(k))
    reference_text = reference["model"] + (
        ", %s" % reference["commit_or_tag"] if reference.get("commit_or_tag") else "")
    rows = [
        ("Validated commit", "`%s`" % artifact["commit"]),
        ("Reference", reference_text),
        ("Validation date", manifest["timestamp"][:10]),
        ("Platform", platform or "_not captured_"),
        ("Tests", "%d case%s — %d passed, %d failed, %d error" % (
            len(cases), "" if len(cases) == 1 else "s",
            statuses.count("PASS"), statuses.count("FAIL"), statuses.count("ERROR"))),
        ("Criteria", "%s — %d benchmark%s under %s" % (
            ", ".join(kinds), len(cases), "" if len(cases) == 1 else "s",
            ", ".join("`%s/`" % d for d in sorted({c["benchmark"].rsplit("/", 1)[0] for c in cases})))),
        ("Result", manifest["result"]),
        ("Security gate", manifest["security"]["status"]),
        ("Evidence class", manifest["evidence_class"]),
        ("Record", "`%s`" % record_path),
        ("Evidence", "%s/tree/main/%s" % (CC_TEST_URL, record_path)),
    ]
    width = max(len(k) for k, _ in rows)
    lines = ["# Validation Status", "",
             "Validated against the acceptance record named below; that record is the",
             "authority, this file is the pointer. `correctness/check_validation.py` in CC-Test",
             "checks the two agree and refreshes the last line.", "",
             "| | |", "|---|---|"]
    lines += ["| %-*s | %s |" % (width, k, v) for k, v in rows]
    lines += ["", "> Current HEAD is the validated commit.", ""]
    return "\n".join(lines)


# --- check ----------------------------------------------------------------------


def parse(text: str) -> Tuple[Dict[str, str], Optional[int], bool]:
    """(rows, commits ahead the drift line claims or None, whether a drift line exists)."""
    rows: Dict[str, str] = {}
    drift: Optional[int] = None
    has_drift = False
    for line in text.splitlines():
        row = ROW.match(line)
        if row and row.group("key") not in ("", "---"):
            rows[row.group("key")] = row.group("value")
        match = DRIFT.match(line)
        if match:
            has_drift = True
            drift = int(match.group("n")) if match.group("n") else 0
    return rows, drift, has_drift


def git(repo: Path, *args: str) -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo)] + list(args), text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def check(args) -> int:
    findings: List[str] = []
    warnings: List[str] = []
    path = Path(args.validation)
    try:
        text = path.read_text()
    except OSError as exc:
        print("check_validation: cannot read %s: %s" % (path, exc), file=sys.stderr)
        return EXIT_INCOMPLETE
    rows, drift, has_drift = parse(text)

    commit = rows.get("Validated commit", "").strip("` ")
    record = rows.get("Record", "")
    stated = rows.get("Result", "").strip()
    match = RECORD.search(record) or RECORD.search(rows.get("Evidence", ""))
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        findings.append("no usable `Validated commit` row (got %r)" % commit)
    if not match:
        findings.append("no `Record` row naming evidence/<product>/<version>/")
    if not stated:
        findings.append("no `Result` row")
    if findings:
        for f in findings:
            print("%s: ERROR: %s" % (path, f))
        return EXIT_FINDINGS

    assert match is not None
    product, version = match.group("product"), match.group("version")
    manifest_path = Path(args.evidence_dir) / product / version / "manifest.json"
    if not manifest_path.is_file():
        print("%s: ERROR: the record it names, evidence/%s/%s/, is not in %s"
              % (path, product, version, args.evidence_dir))
        return EXIT_FINDINGS
    manifest = json.loads(manifest_path.read_text())

    recorded = manifest["artifact"]["commit"]
    if not (recorded.startswith(commit) or commit.startswith(recorded)):
        findings.append("validated commit %s is not the record's artifact.commit %s"
                        % (commit, recorded))
    if manifest["result"] != stated:
        findings.append("Result says %s but the record says %s" % (stated, manifest["result"]))
    if manifest["artifact"]["version"] != version:
        findings.append("record path names version %s but the manifest says %s"
                        % (version, manifest["artifact"]["version"]))

    repo = Path(args.product_repo)
    resolved = git(repo, "cat-file", "-e", commit + "^{commit}")
    if resolved is None:
        findings.append("validated commit %s does not resolve in %s" % (commit, repo))
    else:
        head = git(repo, "rev-parse", "HEAD") or ""
        ahead = git(repo, "rev-list", "--count", "%s..HEAD" % commit)
        ahead_n = int(ahead) if ahead and ahead.isdigit() else None
        if ahead_n is None:
            warnings.append("could not count commits between %s and HEAD" % commit)
        else:
            if ahead_n:
                warnings.append("HEAD %s is %d commit(s) ahead of the validated commit %s"
                                % (head[:8], ahead_n, commit[:8]))
            stale = (not has_drift) or drift != ahead_n
            if stale:
                message = ("drift line is %s: HEAD is %d commit(s) ahead"
                           % ("missing" if not has_drift else "stale", ahead_n))
                if args.refresh:
                    new_line = ("> Current HEAD is the validated commit." if ahead_n == 0
                                else "> Current HEAD is %d commit%s ahead of the validated commit."
                                % (ahead_n, "" if ahead_n == 1 else "s"))
                    lines = [l for l in text.splitlines() if not DRIFT.match(l)]
                    while lines and not lines[-1].strip():
                        lines.pop()
                    path.write_text("\n".join(lines + ["", new_line]) + "\n")
                    warnings.append(message + "; refreshed")
                elif args.strict:
                    findings.append(message)
                else:
                    warnings.append(message)

    for f in findings:
        print("%s: ERROR: %s" % (path, f))
    for w in warnings:
        print("%s: WARNING: %s" % (path, w))
    print("check_validation: %s -> evidence/%s/%s/ (%s): %d error(s), %d warning(s)"
          % (path, product, version, manifest["result"], len(findings), len(warnings)))
    return EXIT_FINDINGS if findings else EXIT_PASS


# --- driver ---------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render", help="print VALIDATION.md for an acceptance record")
    r.add_argument("--manifest", type=Path, required=True,
                   help="evidence/<product>/<version>/manifest.json in this repository")
    c = sub.add_parser("check", help="check a product's VALIDATION.md against the records")
    c.add_argument("--validation", type=Path, default=Path("VALIDATION.md"))
    c.add_argument("--product-repo", type=Path, default=Path("."))
    c.add_argument("--evidence-dir", type=Path, required=True,
                   help="the evidence/ directory of a CC-Test checkout")
    c.add_argument("--strict", action="store_true",
                   help="a missing or stale drift line is a finding, not a warning")
    c.add_argument("--refresh", action="store_true",
                   help="rewrite the drift line in place")
    args = parser.parse_args(argv)

    if args.command == "render":
        manifest_path = args.manifest.resolve()
        parts = manifest_path.parts
        try:
            at = len(parts) - 1 - parts[::-1].index("evidence")
        except ValueError:
            print("check_validation: %s is not under an evidence/ directory" % manifest_path,
                  file=sys.stderr)
            return EXIT_INCOMPLETE
        record_path = "/".join(parts[at:-1]) + "/"
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            print("check_validation: cannot read %s: %s" % (manifest_path, exc), file=sys.stderr)
            return EXIT_INCOMPLETE
        sys.stdout.write(render(manifest, record_path))
        return EXIT_PASS
    return check(args)


if __name__ == "__main__":
    sys.exit(main())
