# CC-Test schemas

Machine-readable definition of what an evidence package is. See
`../docs/VALIDATION-ARCHITECTURE.md` for the architecture these schemas serve.

| File | Purpose |
|---|---|
| `evidence-manifest.v1.json` | The evidence package itself: artifact, reference, environment, cases, result |
| `acceptance.v1.json` | The acceptance criteria vocabulary, referenced from each case |
| `examples/example-bitwise.manifest.json` | Format example. Not evidence — see the `notes` field |
| `test_schemas.py` | Self-test: the example must validate, and twelve deliberate mutations must be rejected |

Both are JSON Schema draft 2020-12. The manifest `$ref`s `acceptance.v1.json` by `$id`, so
a validator must be given both documents in one registry rather than resolving over the
network; `test_schemas.py` shows the two-line setup.

```
python3 -m venv .venv && .venv/bin/pip install jsonschema
.venv/bin/python schemas/test_schemas.py
```

## Design decisions worth knowing

**Every rule states whether it gates.** `gating` is required on every acceptance rule, and
a bitwise acceptance block must contain at least one gating rule. This exists because the
current comparator computes character-variable differences and GPTL timing but neither
affects its exit code — the de facto criterion is numeric bit-for-bit only. That was true
but unwritten; the schema makes it impossible to leave unwritten, so the meaning of a PASS
is always recoverable from the manifest.

**The numeric digest is per file, not per variable.** `numeric_md5_equal` covers one md5
per output file, taken over a single fixed-format text dump of all numeric variables in
that file. Only character variables are digested individually. The rule therefore records
`dump_format` (default `%+.17g`) and `dump_tool` (default `ncks`): a digest produced with a
different format string is not comparable, so the format is recorded rather than assumed.

**ERROR is distinct from FAIL.** When the reference and candidate run directories hold
different file sets, nothing was compared — that is not a failed comparison, it is an
absent one. The comparator already exits 2 for this case. `file_set_equal` is therefore
always gating, and a case whose status is `ERROR` must carry an `error` message.

**`evidence_class: reconstructed` is a first-class state.** Historical results assembled
after the fact cannot always name the compiler build or the reference revision. Rather than
forcing a plausible-looking value into those fields, a reconstructed manifest is allowed to
omit them and is reported as a format example, never counted as compliance evidence.

**Versions may precede tags.** No product repository has cut a tag yet. `version` accepts
either a release tag (`v0.2.0`) or the bridge form `unreleased-<commit[:8]>`; `commit` is
authoritative in both cases. See decision D2.

**Statistical acceptance is provisional and blocked.** `acceptance.v1.json` defines
placeholder rules for Pipeline 2 derived from the dashboard figures, but the tolerance
semantics, norm, compared variable set and spread test are not agreed (decision D4). The
block must carry `"status": "provisional"`, and `verify_evidence.py` rejects any manifest
using it until that marker is removed. The placeholders exist so the shape of the eventual
decision is visible, not so evidence can be filed against them.

## Invariants JSON Schema cannot express

`correctness/verify_evidence.py` (migration step 3) enforces these; they are listed here so
the schema and the verifier stay in agreement.

**Errors**

1. `cases[].result.checks` corresponds one-to-one and in order with
   `cases[].acceptance.rules` — same `check` name, same `gating` value.
2. A case is `PASS` only if every gating check has `passed: true`; `FAIL` if any gating
   check has `passed: false`; `ERROR` only with an `error` message.
3. Top-level `result` is `ERROR` if any case errored, otherwise `FAIL` if any case failed,
   otherwise `PASS`.
4. `artifact.commit` resolves in `artifact.repo`.
5. `artifact.version` equals the directory name under `evidence/<product>/`.
6. `cases[].benchmark` names a file that exists in this repository, and `cases[].id`
   equals that file's stem.
7. `cc_test.commit` resolves in this repository.
8. `evidence/` is append-only: a manifest already present on the base branch must not be
   modified by a pull request.
9. `acceptance.kind: statistical` is rejected while its `status` is `provisional`.
10. `security.scanned_commit` equals `artifact.commit` — otherwise the Cyber verdict
    describes different code than the correctness verdict.
11. `security.status` is `PASS` only when all three scans ran (`scanned` / `scanned` /
    `reviewed`) and every count is zero.

**Warnings**

12. `evidence_class: reconstructed` — usable as a format example only.
13. `outputs.files` is empty — no fingerprint was retained, so the run cannot be checked
    against a future re-run.
14. `outputs.retention` is `unknown` — the purge date was never recorded.
15. `security.status` is `NOT_RUN` or `INCOMPLETE` — the validated code was not fully
    scanned.
16. `security.scans.secrets.target_config` is false — the secret scan used default rules
    with no project allowlist.
17. `security.scans.vulnerabilities.vex_applied` is false — the CVE counts include
    findings nobody has assessed as not-affected.
