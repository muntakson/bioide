#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
03_validate.py  (Tahoe-100M drug response — independent validation, 헌장 제2조)

Judges whether our independently re-derived drug signature is (a) REPRODUCIBLE across
cancer cell lines and (b) ON-MECHANISM (recovers the drug's known targets). Reads only
step-2 outputs in $GHBIO_RESULTS. No bucket access needed.

Metrics:
  - mean_cross_line_logfc_corr : mean pairwise correlation of per-gene log2FC between
    cell lines (a real drug effect agrees across independent lines),
  - n_consensus_de             : consensus DE genes (min padj < 0.05 & |consensus logFC| > 1),
  - target_recovery_frac       : fraction of known target genes that move (|logFC| > 0.25).
Verdict: AGREE / PARTIAL / DISAGREE.
"""
from __future__ import annotations

import argparse
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def savefig(path):
    plt.tight_layout(); plt.savefig(path, dpi=130, bbox_inches="tight"); plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    args = ap.parse_args()
    R = args.results
    m = {}

    de = pd.read_csv(os.path.join(R, "de_by_cellline.csv"))
    rep = pd.read_csv(os.path.join(R, "reproducibility.csv")) if os.path.exists(os.path.join(R, "reproducibility.csv")) else pd.DataFrame()
    m["n_cell_lines"] = int(de["cell_line"].nunique())
    m["mean_cross_line_logfc_corr"] = float(rep["logfc_corr"].mean()) if not rep.empty else float("nan")

    # consensus DE
    wide = de.pivot_table(index="gene", columns="cell_line", values="logfc")
    consensus = wide.mean(axis=1)
    minpadj = de.groupby("gene")["padj"].min()
    sig = (minpadj < 0.05) & (consensus.abs() > 1.0)
    m["n_consensus_de"] = int(sig.sum())

    # target recovery
    tr_path = os.path.join(R, "target_recovery.csv")
    if os.path.exists(tr_path) and os.path.getsize(tr_path) > 0:
        tr = pd.read_csv(tr_path)
        if len(tr):
            m["n_targets"] = int(len(tr))
            m["target_recovery_frac"] = float((tr["consensus_logfc"].abs() > 0.25).mean())
        else:
            m["n_targets"] = 0
            m["target_recovery_frac"] = float("nan")

    # verdict
    corr = m["mean_cross_line_logfc_corr"]
    if not np.isnan(corr):
        if corr >= 0.5 and m["n_consensus_de"] >= 20:
            verdict = "AGREE"
        elif corr >= 0.3 and m["n_consensus_de"] >= 5:
            verdict = "PARTIAL"
        else:
            verdict = "DISAGREE"
    else:
        verdict = "INCONCLUSIVE"
    m["verdict"] = verdict

    pd.DataFrame([m]).T.rename(columns={0: "value"}).to_csv(os.path.join(R, "validation_summary.csv"))
    with open(os.path.join(R, "validation_verdict.txt"), "w") as fh:
        fh.write(f"VERDICT: {verdict}\n")
        fh.write(f"cross-cell-line logFC corr = {corr:.3f} over {m['n_cell_lines']} lines\n")
        fh.write(f"consensus DE genes (padj<0.05,|logFC|>1) = {m['n_consensus_de']}\n")
        if "target_recovery_frac" in m:
            fh.write(f"target recovery frac = {m['target_recovery_frac']}\n")

    # bars
    keys = [k for k in ("mean_cross_line_logfc_corr", "target_recovery_frac") if k in m and not (isinstance(m[k], float) and np.isnan(m[k]))]
    if keys:
        plt.figure(figsize=(5, 4))
        plt.bar(keys, [m[k] for k in keys]); plt.ylim(0, 1)
        plt.title(f"Validation — {verdict}"); plt.xticks(rotation=15, ha="right")
        savefig(os.path.join(R, "validation_bars.png"))

    print(f"==> [03] validation verdict: {verdict}")
    print(pd.DataFrame([m]).T.rename(columns={0: "value"}).to_string())


if __name__ == "__main__":
    main()
