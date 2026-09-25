# Acceptance records

An **acceptance record** (验收记录) is one directory, `evidence/<product>/<version>/`: the
statement that one version of a product was checked against its benchmarks, and what came
of it. It holds the verdict and where it came from — commit, reference, environment, the
criteria copied from `benchmarks/`, each rule's outcome, the Cyber gate's state — and it
fingerprints the results it was judged from rather than containing them; those stay in the
product's repository. It is the counterpart of the acceptance criteria in `benchmarks/`.

The names on disk predate the term and are kept: the directory is `evidence/`, the
machine-readable part of each record is `manifest.json`, and its schema is
`evidence-manifest.v1.json`. "Manifest" in these docs always means that file.
RecastEngine's one-file-per-verdict output (`recast.evidence.v1`, which the engine's own
docs call evidence manifests) is a different document and is not an acceptance record;
CC-Test never files or reads it.

```
manifest.json    the machine-readable record — validates against ../schemas/evidence-manifest.v1.json
summary.md       human-readable, one page
report.txt       the comparator's raw text output
```

`INDEX.md` is a cross-product table generated from the manifests by
`correctness/index_evidence.py`, which writes `index.json` beside it from the same manifests.
`index.json` (`{"schema": 1, "source": ..., "records": [...]}`, newest validation first) holds one
record per acceptance record: `product`, `version`, `path`, `artifact` (name, repo, commit),
`reference` (model, commit_or_tag), `cases` (total, passed, ids), `result`, `security` (the gate
status), `evidence_class`, `validated` (the manifest timestamp) and `cc_test_commit`. Nothing in it
is generated at write time, so two runs over the same records give the same bytes. The SciRecast
website (`a85tract/SciRecast`) fetches it to list what has been validated (decision D9 in
`docs/CORRECTNESS-ORGANIZATION.md`). A pull request that files an acceptance record must run
`index_evidence.py` and commit both files; `index_evidence.py --check` exits 1 when either is stale
or missing, and `tests/test_correctness.py` runs that check, as does CI
(`.github/workflows/verify-evidence.yml`).
The same workflow runs `correctness/verify_evidence.py --base-ref origin/<base>` on every pull
request, so the append-only check (invariant 8) runs in CI against the base branch.

The one acceptance record so far is `clubb-jax/unreleased-99c8b22f/`: clubb-jax `99c8b22f` against
CLUBB_core `8ab3902`, 15 cases judged by RecastEngine `e3c6717` from the summaries the case
commits, all PASS, `evidence_class: complete`, `security.status: NOT_RUN`. Its
`cc_test.commit` (`86a46e8c`) is the CC-Test commit that holds the benchmarks and the
tooling that produced it; the record was assembled at that commit and committed after it.
File every record the same way: commit criteria and tooling first, assemble, then commit
the record, so that `cc_test.commit` names the code that made it.

## Rules

**Append-only.** Once an acceptance record lands it is immutable. A re-run produces a new
version directory; it never edits an old one. `verify_evidence.py --base-ref REF` enforces
this against the base branch: a pull request that modifies, deletes or renames any file of
an existing record fails. `INDEX.md`, `index.json` and this README are not records and are exempt.
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

**A reconstructed record is not compliance evidence.** When backfilling a run whose
compiler version or reference commit can no longer be established, set
`evidence_class: reconstructed` and omit those fields rather than inventing values. The
verifier reports such a record as a format example.
