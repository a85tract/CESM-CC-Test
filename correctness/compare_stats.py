#!/usr/bin/env python3
"""Compare a reference/candidate run pair — statistical acceptance (Pipeline 2).

STATUS: stub, and BLOCKED. See ../docs/VALIDATION-ARCHITECTURE.md, migration
step 8 and decision D4.

Pipeline 2 (jax-kernels, numba-kernels, pyphys-bridge) does not reproduce the
Fortran bit for bit, so `compare_runpair.py` does not apply. Its criteria are
statistical — the dashboard records figures like "1.24e-6 relative difference"
for Held-Suarez and "within ensemble spread" for TJ2016.

Why this is blocked rather than merely unwritten
------------------------------------------------
Those figures are results, not criteria. To become executable each needs:

  - the tolerance value AND the norm it applies to (L2? L-infinity? RMSE?);
  - the set of variables compared, and whether every one must pass or an
    aggregate is enough;
  - for the ensemble tests, the required member count and what "within spread"
    means — standard deviation, min/max envelope, interquartile range — and
    with what multiplier;
  - whether the comparison is over the whole field, a region, or a time mean.

Writing this module before those are settled would bake one arbitrary reading of
each into the tool and into every evidence package produced with it.

`../schemas/acceptance.v1.json` therefore defines `relative_diff_max` and
`within_ensemble_spread` as PLACEHOLDERS. They must carry `"status":
"provisional"`, and `verify_evidence.py` rejects any manifest that uses them.
The placeholders exist so the shape of the pending decision is visible — not so
evidence can be filed against them. When D4 is settled, remove the `status`
field from the schema and implement against the agreed definitions.

The JSON contract, exit codes, and reference/candidate naming follow
`compare_runpair.py`; only the acceptance vocabulary differs.
"""

from __future__ import annotations

import sys


def main() -> int:
    raise NotImplementedError(
        "compare_stats.py is blocked on decision D4: the statistical acceptance "
        "vocabulary (tolerance, norm, variable set, ensemble spread test) is not "
        "yet defined. See this module's docstring."
    )


if __name__ == "__main__":
    sys.exit(main())
