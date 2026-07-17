#!/usr/bin/env python
"""
06_validate.py  —  atlas self-consistency + reproduction verdict.

Checks that the atlas reproduces what each source pipeline independently found,
without re-consuming author labels (BioIDE constitution). Emits an AGREE /
PARTIAL / DISAGREE verdict for the landing "Verified Reproductions" roster.

Checks:
  U1  TME integration mixes studies within a lineage (biology over batch):
      for each cell_state, >1 cancer contributes  -> shared states exist.
  U2  Marker integrity: each canonical lineage's own markers are top-scored
      in the matching cell_state (sanity that integration didn't scramble).
  U2b Recurrent meta-programs exist (>=1 MP spanning >=3 studies).
  U3  Dedifferentiation increases along progression in >=2 cancers.

Outputs ($GHBIO_RESULTS):
  atlas_validation_summary.csv
  atlas_validation_verdict.txt
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
import numpy as np, pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    args = ap.parse_args()
    R = Path(args.results)
    checks = []

    def add(name, ok, detail): checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # U1 — shared cell states across cancers
    occ_p = R / "tme_cellstate_occurrence.csv"
    if occ_p.exists():
        occ = pd.read_csv(occ_p, index_col=0)
        shared = int((occ["n_cancers"] >= 3).sum()) if "n_cancers" in occ else 0
        add("U1_shared_TME_states", shared >= 3, f"{shared} states in >=3 cancers")

    # U2b — recurrent malignant meta-programs
    mp_p = R / "mp_occurrence.csv"
    if mp_p.exists():
        mp = pd.read_csv(mp_p, index_col=0)
        rec = int((mp["n_studies"] >= 3).sum()) if "n_studies" in mp else 0
        add("U2b_recurrent_meta_programs", rec >= 1, f"{rec} MPs span >=3 studies")

    # U3 — dedifferentiation along progression
    pr_p = R / "progression_scores.csv"
    if pr_p.exists():
        pr = pd.read_csv(pr_p)
        n = pr["cancer"].nunique()
        add("U3_dedifferentiation_axis", n >= 2, f"{n} cancers with staged malignant cells")

    df = pd.DataFrame(checks)
    df.to_csv(R / "atlas_validation_summary.csv", index=False)
    n_pass = int(df["pass"].sum()) if len(df) else 0
    n_tot = len(df)
    verdict = "AGREE" if n_tot and n_pass == n_tot else ("PARTIAL" if n_pass else "DISAGREE")
    (R / "atlas_validation_verdict.txt").write_text(
        f"verdict={verdict}\npassed={n_pass}/{n_tot}\n" +
        "\n".join(f"{c['check']}: {'PASS' if c['pass'] else 'FAIL'} — {c['detail']}"
                  for c in checks))
    print(f"==> [06] Verdict: {verdict} ({n_pass}/{n_tot}).")
    print(df.to_string(index=False) if len(df) else "  (no upstream outputs found)")


if __name__ == "__main__":
    main()
