#!/usr/bin/env python3
"""
Convert a REAL public NSCLC scRNA-seq dataset (.h5ad / AnnData) into the exact
files the NSCLC Atlas app consumes (public/data/meta.json + expr.bin).

Where to get real data
----------------------
  * CELLxGENE Discover  https://cellxgene.cziscience.com   (download .h5ad, NSCLC / lung)
  * Kim et al. 2020     GEO GSE131907  (NSCLC, ~200k cells)
  * Lambrechts 2018     ArrayExpress E-MTAB-6149 / 6653
  * Human Lung Cell Atlas (HLCA)  https://cellxgene.cziscience.com

Requirements
------------
  pip install scanpy anndata numpy  --break-system-packages

Usage
-----
  python scripts/convert_h5ad.py INPUT.h5ad \
      --celltype   cell_type \
      --condition  tissue \
      --sample     sample \
      --patient    patient \
      [--umap X_umap] [--max-cells 40000] [--panel EPCAM,CD8A,...]

The app expects a normalized+log1p expression matrix. If your .h5ad still holds
raw counts this script will normalize_total + log1p for you (pass --raw).
"""
import argparse
import json
import os

import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "data")

# Default NSCLC marker panel (used if --panel not given); only genes present in
# the dataset are kept.
DEFAULT_PANEL = [
    "EPCAM", "KRT19", "KRT8", "NAPSA", "SFTPC", "SFTPB", "SCGB1A1", "MKI67", "TOP2A",
    "PTPRC", "CD3D", "CD3E", "CD8A", "CD8B", "GZMK", "CD4", "IL7R", "FOXP3", "CTLA4",
    "IL2RA", "GZMB", "NKG7", "GNLY", "KLRD1", "NCAM1", "CD79A", "MS4A1", "CD19",
    "MZB1", "IGHG1", "JCHAIN", "CD68", "CD14", "LYZ", "MARCO", "FCGR3A", "CLEC9A",
    "LILRA4", "FCER1A", "TPSAB1", "CPA3", "KIT", "COL1A1", "DCN", "PDGFRB", "ACTA2",
    "PECAM1", "VWF", "CLDN5", "CDH5",
]

# A small palette to auto-assign cell-type colors.
PALETTE = [
    "#e6194B", "#f58231", "#4363d8", "#42d4f4", "#911eb4", "#000075", "#3cb44b",
    "#469990", "#9A6324", "#808000", "#fabed4", "#a9a9a9", "#ffe119", "#f032e6",
    "#bfef45", "#dcbeff", "#800000", "#aaffc3", "#ffd8b1", "#000000",
]


def main():
    import scanpy as sc  # imported lazily so --help works without scanpy

    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--celltype", required=True, help="obs column with cell-type labels")
    ap.add_argument("--condition", required=True, help="obs column for tumor/normal tissue")
    ap.add_argument("--sample", required=True, help="obs column for sample id")
    ap.add_argument("--patient", default=None, help="obs column for patient id (defaults to sample)")
    ap.add_argument("--umap", default="X_umap", help="obsm key holding 2D UMAP coords")
    ap.add_argument("--panel", default=None, help="comma-separated gene panel override")
    ap.add_argument("--max-cells", type=int, default=40000, help="downsample to at most N cells")
    ap.add_argument("--raw", action="store_true", help="normalize_total + log1p the matrix first")
    ap.add_argument("--out-dir", default=OUT_DIR, help="where to write meta.json + expr.bin")
    ap.add_argument("--name", default=None, help="dataset display name")
    ap.add_argument("--description", default=None, help="dataset description")
    ap.add_argument("--name-by-marker", action="store_true",
                    help="rename each cell-type / cluster group by its top-expressing panel gene "
                         "(useful when --celltype points at unnamed Leiden clusters)")
    args = ap.parse_args()

    print(f"Reading {args.input} …")
    adata = sc.read_h5ad(args.input)

    if args.patient is None:
        args.patient = args.sample

    # UMAP
    if args.umap not in adata.obsm:
        print(f"'{args.umap}' not in .obsm — computing PCA+neighbors+UMAP (slow)…")
        sc.pp.pca(adata, n_comps=30)
        sc.pp.neighbors(adata)
        sc.tl.umap(adata)
        args.umap = "X_umap"

    # downsample for a responsive web app
    if adata.n_obs > args.max_cells:
        idx = np.random.default_rng(0).choice(adata.n_obs, args.max_cells, replace=False)
        idx.sort()
        adata = adata[idx].copy()
        print(f"Downsampled to {adata.n_obs} cells")

    if args.raw:
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)

    # gene panel present in this dataset
    panel = [g.strip() for g in args.panel.split(",")] if args.panel else DEFAULT_PANEL
    var_names = set(map(str, adata.var_names))
    genes = [g for g in panel if g in var_names]
    if not genes:
        raise SystemExit("None of the panel genes were found in the dataset var_names.")
    print(f"Using {len(genes)} genes: {', '.join(genes)}")

    # categorical encodings
    def encode(col):
        vals = adata.obs[col].astype(str).values
        cats = sorted(set(vals))
        idx = {c: i for i, c in enumerate(cats)}
        return np.array([idx[v] for v in vals], dtype=np.int32), cats

    ct, ct_names = encode(args.celltype)
    cond, cond_names = encode(args.condition)
    samp, samp_names = encode(args.sample)
    pat, pat_names = encode(args.patient)
    N, N_CT = adata.n_obs, len(ct_names)

    # expression matrix for the panel (dense, cells x genes)
    sub = adata[:, genes]
    X = sub.X
    X = np.asarray(X.todense()) if hasattr(X, "todense") else np.asarray(X)
    X = X.astype(np.float32)

    # dotplot + per-gene normalized uint8
    dot_mean = np.zeros((N_CT, len(genes)))
    dot_pct = np.zeros((N_CT, len(genes)))
    for c in range(N_CT):
        mask = ct == c
        if mask.sum():
            dot_mean[c] = X[mask].mean(axis=0)
            dot_pct[c] = (X[mask] > 0).mean(axis=0) * 100.0

    # optionally name each group (e.g. unnamed Leiden clusters) by its top panel marker
    if args.name_by_marker:
        ct_names = [f"{ct_names[c]} · {genes[int(np.argmax(dot_mean[c]))]}" for c in range(N_CT)]

    gmax = X.max(axis=0)
    gmax[gmax == 0] = 1.0
    expr_u8 = np.clip(np.round((X / gmax) * 255), 0, 255).astype(np.uint8)

    coords = np.asarray(adata.obsm[args.umap])[:, :2]

    def comp(vals, k):
        out = np.zeros((k, N_CT), dtype=int)
        for i in range(N):
            out[vals[i], ct[i]] += 1
        return out.tolist()

    meta = {
        "dataset": {
            "name": args.name or os.path.basename(args.input),
            "description": args.description or (
                f"Real scRNA-seq data from {os.path.basename(args.input)} "
                f"({N} cells, {len(genes)} panel genes)."),
            "nCells": int(N),
            "nGenes": len(genes),
        },
        "cellTypes": [
            {"id": i, "name": ct_names[i], "color": PALETTE[i % len(PALETTE)]}
            for i in range(N_CT)
        ],
        "conditions": cond_names,
        "patients": pat_names,
        "samples": samp_names,
        "genes": genes,
        "markerGenes": {},
        "x": [round(float(v), 3) for v in coords[:, 0]],
        "y": [round(float(v), 3) for v in coords[:, 1]],
        "cellType": ct.tolist(),
        "condition": cond.tolist(),
        "sample": samp.tolist(),
        "patient": pat.tolist(),
        "dotPlot": {
            "mean": [[round(float(v), 3) for v in row] for row in dot_mean],
            "pct": [[round(float(v), 1) for v in row] for row in dot_pct],
        },
        "composition": {
            "byCondition": comp(cond, len(cond_names)),
            "byPatient": comp(pat, len(pat_names)),
        },
    }

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, separators=(",", ":"))
    with open(os.path.join(args.out_dir, "expr.bin"), "wb") as f:
        f.write(expr_u8.tobytes(order="C"))

    print(f"Wrote {N} cells x {len(genes)} genes to {args.out_dir}")


if __name__ == "__main__":
    main()
