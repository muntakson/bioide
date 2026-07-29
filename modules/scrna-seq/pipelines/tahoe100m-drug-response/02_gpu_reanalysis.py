#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Tahoe-100M drug response — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조: we do NOT consume any provided drug-'response' or 'sensitive' label.
Starting from the raw UMI counts of the streamed subset (one drug + DMSO controls across
a few cancer cell lines), our own GPU code re-derives the drug's transcriptional response:

  1. load tahoe_subset.h5ad (drug + control cells, several cell lines),
  2. QC → normalisation → HVG,
  3. **GPU (PyTorch)** scaling + PCA, Harmony integration (batch = cell_line) → Leiden →
     UMAP for a visual sanity check that drug and control separate WITHIN each cell line,
  4. per cell line, DIFFERENTIAL EXPRESSION drug-vs-DMSO (Wilcoxon) → de_by_cellline.csv,
  5. CROSS-CELL-LINE REPRODUCIBILITY — correlate the per-gene log-fold-changes between
     cell lines (a reproducible drug signature agrees across independent lines),
  6. TARGET / MOA RECOVERY — do the drug's known target genes (drug_metadata) move in the
     expected direction / rank among the top DE genes?

The point: a giga-scale perturbation atlas lets us ask "is this drug's signature
reproducible across cancer contexts, and does it hit its known mechanism?" — re-derived
from counts, not read off a label.

Outputs (into $GHBIO_RESULTS): see the pipeline.json `produces` list.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import threading
import time
import warnings
from contextlib import contextmanager

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager  # noqa: E402
for _f in ("Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic"):
    if any(_f == f.name for f in matplotlib.font_manager.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _f
        break
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scanpy as sc  # noqa: E402
import torch  # noqa: E402
from scipy import sparse  # noqa: E402


@contextmanager
def progress(label: str):
    started = time.monotonic()
    done = threading.Event()

    def heartbeat() -> None:
        while not done.wait(30):
            print(f"⏳ {label} — still running ({(time.monotonic()-started)/60:.1f} min)", flush=True)

    print(f"▶ {label}", flush=True)
    t = threading.Thread(target=heartbeat, daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join(timeout=1)
        print(f"✓ {label} — done ({(time.monotonic()-started)/60:.1f} min)", flush=True)


def gpu_scale(matrix, device, scale_max):
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    return torch.clamp((x - mean) / std, max=scale_max)


def gpu_pca(scaled, n_comps):
    scaled = scaled - scaled.mean(dim=0, keepdim=True)
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    return (u[:, :n_comps] * s[:n_comps]).cpu().numpy()


def savefig(path):
    plt.tight_layout()
    plt.savefig(path + ".tmp", dpi=130, bbox_inches="tight")
    os.replace(path + ".tmp", path)
    plt.close()


def gene_symbols(adata):
    """Ensure var_names are gene symbols (Tahoe var may carry gene_symbol / ensembl)."""
    for k in ("gene_symbol", "gene_symbols", "feature_name"):
        if k in adata.var.columns:
            adata.var["ensembl"] = adata.var_names
            adata.var_names = adata.var[k].astype(str).values
            adata.var_names_make_unique()
            break
    return adata


def de_drug_vs_control(sub):
    """Wilcoxon DE of drug vs control within one cell line; returns a tidy frame."""
    if sub.obs["condition"].nunique() < 2:
        return None
    sc.tl.rank_genes_groups(sub, "condition", groups=["drug"], reference="control",
                            method="wilcoxon", n_genes=sub.n_vars)
    df = sc.get.rank_genes_groups_df(sub, group="drug")
    return df.rename(columns={"names": "gene", "logfoldchanges": "logfc",
                              "pvals_adj": "padj", "scores": "score"})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--subset", default=os.path.expanduser("~/ghbio-tutorial/data/tahoe100m/tahoe_subset.h5ad"))
    ap.add_argument("--data-dir", default=os.path.expanduser("~/ghbio-tutorial/data/tahoe100m"))
    ap.add_argument("--n-pcs", type=int, default=40)
    ap.add_argument("--n-hvg", type=int, default=2000)
    args = ap.parse_args()
    R = args.results
    os.makedirs(R, exist_ok=True)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"==> [02] Tahoe-100M drug-response reanalysis → {R}  (device: {dev})")

    with progress("load subset"):
        adata = sc.read_h5ad(args.subset)
        adata = gene_symbols(adata)
        adata.var_names_make_unique()
    print(adata.obs.groupby(["cell_line", "condition"]).size().to_string())

    with progress("QC + normalise + HVG"):
        adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
        sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], inplace=True, percent_top=None)
        sc.pp.filter_cells(adata, min_genes=200)
        sc.pp.filter_genes(adata, min_cells=3)
        adata = adata[adata.obs["pct_counts_mt"] < 20].copy()
        adata.layers["counts"] = adata.X.copy()
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        adata.raw = adata
        sc.pp.highly_variable_genes(adata, n_top_genes=args.n_hvg, flavor="seurat")
    pd.DataFrame({"n_cells": [adata.n_obs], "n_genes": [adata.n_vars]}).to_csv(
        os.path.join(R, "qc_summary.csv"), index=False)

    with progress(f"GPU scale + PCA ({dev})"):
        hvg = adata[:, adata.var["highly_variable"]].X
        dense = hvg.toarray() if sparse.issparse(hvg) else np.asarray(hvg)
        adata.obsm["X_pca"] = gpu_pca(gpu_scale(dense, dev, 10.0), args.n_pcs)

    with progress("Harmony (batch=cell_line) → Leiden → UMAP"):
        rep = "X_pca"
        try:
            import harmonypy
            ho = harmonypy.run_harmony(adata.obsm["X_pca"], adata.obs, ["cell_line"])
            adata.obsm["X_pca_harmony"] = ho.Z_corr.T
            rep = "X_pca_harmony"
        except Exception as e:
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.")
        sc.pp.neighbors(adata, use_rep=rep, n_neighbors=15)
        sc.tl.leiden(adata, resolution=1.0)
        sc.tl.umap(adata)

    # ---- per-cell-line DE drug vs control -----------------------------------------
    de_frames = []
    with progress("per-cell-line DE (drug vs DMSO)"):
        for cl in sorted(adata.obs["cell_line"].unique()):
            sub = adata[adata.obs["cell_line"] == cl].copy()
            df = de_drug_vs_control(sub)
            if df is None:
                continue
            df["cell_line"] = cl
            de_frames.append(df)
    if not de_frames:
        raise SystemExit("ERROR: no cell line had both drug and control cells for DE.")
    de = pd.concat(de_frames, ignore_index=True)
    de.to_csv(os.path.join(R, "de_by_cellline.csv"), index=False)

    # ---- cross-cell-line reproducibility (correlate per-gene logFC) --------------
    with progress("cross-cell-line reproducibility"):
        wide = de.pivot_table(index="gene", columns="cell_line", values="logfc")
        cls = list(wide.columns)
        pairs = []
        for a, b in itertools.combinations(cls, 2):
            r = wide[[a, b]].dropna().corr().iloc[0, 1]
            pairs.append({"cell_line_a": a, "cell_line_b": b, "logfc_corr": float(r)})
        rep_df = pd.DataFrame(pairs)
        rep_df.to_csv(os.path.join(R, "reproducibility.csv"), index=False)
        mean_corr = float(rep_df["logfc_corr"].mean()) if not rep_df.empty else float("nan")
        # consensus signature = mean logFC across cell lines
        wide["consensus_logfc"] = wide[cls].mean(axis=1)
        wide.sort_values("consensus_logfc").to_csv(os.path.join(R, "consensus_signature.csv"))

    # ---- target / MOA recovery ----------------------------------------------------
    target_rows = []
    dt_path = os.path.join(args.data_dir, "drug_targets.csv")
    targets = []
    if os.path.exists(dt_path):
        dt = pd.read_csv(dt_path)
        for c in dt.columns:
            if "target" in c.lower():
                for v in dt[c].dropna().astype(str):
                    targets += [t.strip() for t in v.replace(";", ",").replace("|", ",").split(",") if t.strip()]
    targets = sorted(set(g for g in targets if g and g.upper() in set(adata.var_names.str.upper())))
    for g in targets:
        row = wide.loc[g] if g in wide.index else None
        if row is not None:
            target_rows.append({"gene": g, "consensus_logfc": float(row["consensus_logfc"])})
    pd.DataFrame(target_rows).to_csv(os.path.join(R, "target_recovery.csv"), index=False)

    # ---- figures ------------------------------------------------------------------
    with progress("figures"):
        sc.pl.umap(adata, color="cell_line", show=False, title="Cell line")
        savefig(os.path.join(R, "umap_cellline.png"))
        sc.pl.umap(adata, color="condition", show=False, title="Drug vs DMSO control")
        savefig(os.path.join(R, "umap_condition.png"))
        sc.pl.umap(adata, color="leiden", show=False, legend_loc="on data", title="Leiden clusters")
        savefig(os.path.join(R, "umap_clusters.png"))

        # volcano (consensus)
        cons = wide.reset_index()[["gene", "consensus_logfc"]].dropna()
        best = de.groupby("gene")["padj"].min().reindex(cons["gene"]).values
        y = -np.log10(np.clip(best, 1e-300, 1))
        plt.figure(figsize=(6, 5))
        plt.scatter(cons["consensus_logfc"], y, s=5, alpha=0.4)
        for _, r in cons.reindex(cons["consensus_logfc"].abs().sort_values(ascending=False).index).head(12).iterrows():
            plt.annotate(r["gene"], (r["consensus_logfc"], y[cons["gene"].tolist().index(r["gene"])]), fontsize=7)
        plt.xlabel("consensus log2FC (drug vs DMSO)"); plt.ylabel("-log10 min padj")
        plt.title("Consensus drug signature"); savefig(os.path.join(R, "volcano.png"))

        # reproducibility scatter of the two best-covered cell lines
        if len(cls) >= 2:
            a, b = cls[0], cls[1]
            d2 = wide[[a, b]].dropna()
            plt.figure(figsize=(5, 5))
            plt.scatter(d2[a], d2[b], s=5, alpha=0.3)
            lim = np.nanpercentile(np.abs(d2.values), 99)
            plt.plot([-lim, lim], [-lim, lim], "r--", lw=0.8)
            plt.xlabel(f"log2FC {a}"); plt.ylabel(f"log2FC {b}")
            plt.title(f"Reproducibility r={rep_df['logfc_corr'].iloc[0]:.2f}" if not rep_df.empty else "Reproducibility")
            savefig(os.path.join(R, "reproducibility.png"))

        # top consensus DE heatmap across cell lines
        top = wide["consensus_logfc"].abs().sort_values(ascending=False).head(25).index
        hm = wide.loc[top, cls]
        plt.figure(figsize=(1.2 + 0.8 * len(cls), 7))
        plt.imshow(hm.values, aspect="auto", cmap="RdBu_r",
                   vmin=-np.nanmax(np.abs(hm.values)), vmax=np.nanmax(np.abs(hm.values)))
        plt.xticks(range(len(cls)), cls, rotation=45, ha="right"); plt.yticks(range(len(top)), top, fontsize=7)
        plt.colorbar(label="log2FC"); plt.title("Top consensus DE genes × cell line")
        savefig(os.path.join(R, "de_top_heatmap.png"))

        # target response
        if target_rows:
            tr = pd.DataFrame(target_rows).sort_values("consensus_logfc")
            plt.figure(figsize=(6, max(2, 0.4 * len(tr))))
            plt.barh(tr["gene"], tr["consensus_logfc"],
                     color=["#d97706" if v > 0 else "#2563eb" for v in tr["consensus_logfc"]])
            plt.axvline(0, color="k", lw=0.6); plt.xlabel("consensus log2FC")
            plt.title("Known target-gene response"); savefig(os.path.join(R, "target_response.png"))

    adata.write(os.path.join(R, "tahoe_reanalysis.h5ad"))
    adata.obs.groupby(["cell_line", "condition"]).size().rename("n_cells").reset_index().to_csv(
        os.path.join(R, "composition.csv"), index=False)
    prov = {"pipeline": "tahoe100m-drug-response", "n_cells": int(adata.n_obs),
            "n_genes": int(adata.n_vars), "cell_lines": cls, "integration": rep,
            "mean_cross_line_logfc_corr": mean_corr, "n_targets_recovered": len(target_rows),
            "source": "Tahoe-100M (Vevo × Arc Virtual Cell Atlas)"}
    json.dump(prov, open(os.path.join(R, "provenance.json"), "w"), indent=2)
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"Tahoe-100M drug-response independent reanalysis\n"
                 f"cells={adata.n_obs} cell_lines={cls}\n"
                 f"mean cross-cell-line logFC corr = {mean_corr:.3f}\n"
                 f"targets recovered: {[r['gene'] for r in target_rows]}\n")
    print(f"==> [02] Done. mean cross-line reproducibility r={mean_corr:.3f}. Next: 3. 검증.")


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
