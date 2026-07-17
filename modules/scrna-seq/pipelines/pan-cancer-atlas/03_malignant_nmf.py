#!/usr/bin/env python
"""
03_malignant_nmf.py  —  Use 2 · per-sample NMF programs on malignant cells.

The malignant compartment is NOT integrated (malignant cells cluster by patient,
driven by private CNV). Instead we factor EACH sample independently (NMF) and
collect the per-sample gene programs; 04_meta_programs.py then clusters those
programs across samples into recurrent meta-programs (Gavish/Tirosh 2023).

For each qualifying sample (>= --min-cells malignant cells) we run scikit-learn
NMF (k programs) on log-normalised HVGs and store, per program, the top gene
loadings. Light, CPU-friendly, embarrassingly parallel across samples.

Outputs ($GHBIO_RESULTS):
  malignant_programs.csv     rows = (study, sample, program, rank, gene, weight)
  malignant_programs.json    same, nested; + per-sample metadata
  malignant_nmf_summary.txt
"""
from __future__ import annotations
import argparse, os, glob, json
from pathlib import Path
import numpy as np, pandas as pd, scanpy as sc, anndata as ad
from sklearn.decomposition import NMF


def program_top_genes(model, var_names, topn=50):
    progs = []
    for k in range(model.components_.shape[0]):
        w = model.components_[k]
        order = np.argsort(w)[::-1][:topn]
        progs.append([(var_names[i], float(w[i])) for i in order])
    return progs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--k", type=int, default=8, help="programs per sample")
    ap.add_argument("--min-cells", type=int, default=50)
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--topn", type=int, default=50)
    args = ap.parse_args()
    R = Path(args.results)

    files = sorted(glob.glob(str(R / "harmonized" / "*.malignant.h5ad")))
    if not files:
        raise SystemExit("No harmonized/*.malignant.h5ad — run Stage 0 first.")

    rows, nested, n_samples = [], [], 0
    for f in files:
        a = sc.read_h5ad(f)
        study = a.obs["study_id"].iloc[0] if a.n_obs else Path(f).name.split(".")[0]
        if a.n_obs < args.min_cells:
            print(f"  [{study}] {a.n_obs} malignant cells (< {args.min_cells}) — skipped")
            continue
        if "counts" in a.layers:
            a.X = a.layers["counts"].copy()
        sc.pp.normalize_total(a, target_sum=1e4); sc.pp.log1p(a)
        for sample, d in a.obs.groupby("sample", observed=True):
            sub = a[d.index]
            if sub.n_obs < args.min_cells:
                continue
            s = sub.copy()
            sc.pp.highly_variable_genes(s, n_top_genes=min(args.n_hvg, s.n_vars - 1))
            s = s[:, s.var.highly_variable].copy()
            X = s.X.toarray() if hasattr(s.X, "toarray") else np.asarray(s.X)
            X = np.clip(X, 0, None)
            try:
                model = NMF(n_components=args.k, init="nndsvda", max_iter=400, random_state=0)
                model.fit(X)
            except Exception as e:
                print(f"  !! NMF failed {study}/{sample}: {e}"); continue
            progs = program_top_genes(model, list(s.var_names), args.topn)
            n_samples += 1
            for pk, genes in enumerate(progs):
                nested.append({"study": study, "sample": sample, "program": pk,
                               "n_cells": int(sub.n_obs),
                               "genes": [g for g, _ in genes]})
                for rank, (g, w) in enumerate(genes):
                    rows.append({"study": study, "sample": sample, "program": pk,
                                 "rank": rank, "gene": g, "weight": w})
            print(f"  [{study}/{sample}] {sub.n_obs} cells -> {args.k} programs")

    pd.DataFrame(rows).to_csv(R / "malignant_programs.csv", index=False)
    (R / "malignant_programs.json").write_text(json.dumps(nested, indent=1))
    (R / "malignant_nmf_summary.txt").write_text(
        f"samples_factored={n_samples}\nprograms_per_sample={args.k}\n"
        f"total_programs={len(nested)}\n")
    print(f"==> [03] Done. {n_samples} samples -> {len(nested)} programs. Next: 4. meta-programs.")


if __name__ == "__main__":
    main()
