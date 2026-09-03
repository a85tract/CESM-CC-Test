# Evidence — the index

One directory per validated version: `evidence/<product>/<version>/`.

```
manifest.json    the record — validates against ../schemas/evidence-manifest.v1.json
summary.md       human-readable, one page
report.txt       the comparator's raw text output
```

`INDEX.md` is a generated cross-product table. Nothing here yet: the first package is
migration step 4, a backfill of the 2026-06-16 PyCAM5 PI and MCO runs.

## Rules

**Append-only.** Once a version's manifest lands it is immutable. A re-run produces a new
version directory; it never edits an old one. `verify_evidence.py --base-ref REF` enforces
this against the base branch — a pull request that modifies an existing manifest fails.
Without `--base-ref` there is no base branch to diff against, so the check is reported as
skipped rather than silently passed.

**`<version>` is a release tag**, e.g. `v0.2.0`. No product repository has cut one yet, so
until then use the bridge form `unreleased-<commit[:8]>`; `artifact.commit` is
authoritative either way (decision D2).

**Manifests only — never model output.** A 30-year history set is orders of magnitude past
what belongs in Git, and it lives on scratch that will be purged. What the manifest keeps
is the fingerprint: per-file md5 and byte counts, plus the location and the expected purge
date. That is what makes the record still useful after the data is gone — a later re-run
can be compared against it. Derived artefacts too large for Git but worth keeping (plots,
diff tables, run logs) go to a release asset, referenced by `outputs.assets_release`.

**A reconstructed package is not compliance evidence.** When backfilling a run whose
compiler version or reference commit can no longer be established, set
`evidence_class: reconstructed` and omit those fields rather than inventing values. The
verifier reports such a package as a format example.
