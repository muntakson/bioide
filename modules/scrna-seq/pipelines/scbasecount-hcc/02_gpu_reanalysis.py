#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (scBaseCount HCC — INDEPENDENT cross-study GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT use scBaseCount's per-cell
`cell_type` (SRAgent-inferred) as an analysis input. We start from the uniformly
STARsolo-quantified RAW UMI counts (adata.X, the `Gene` feature) of every selected
human HCC sample and RE-DERIVE the whole analysis with our own GPU code:

  1. load + concatenate the per-sample h5ads pulled by step 1 (each file = one SRX
     sample), recording sample (srx) + tissue + disease as covariates,
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p),
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony integration ACROSS SAMPLES/STUDIES (harmonypy, batch = srx) — the whole
     point of a uniformly-processed atlas: many independent HCC studies pooled into one,
  7. neighbours → Leiden → UMAP,
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical HCC-ecosystem signatures),
 10. an unsupervised malignant-vs-normal HEPATOCYTE split (GMM on an HCC-malignancy −
     mature-hepatocyte-differentiation signature),
 11. a TLS (tertiary lymphoid structure) module: per-cell B/plasma, CXCL13⁺ Tfh,
     TLS-chemokine and central-memory-T scores, aggregated by tissue and by sample.

scBaseCount's `cell_type` is stripped from the working object and saved verbatim to
`author_labels.csv` for the SEPARATE validation step (03) only (헌장 제2조).

Outputs (into $GHBIO_RESULTS): see the pipeline.json `produces` list.
"""
from __future__ import annotations

import argparse
import glob
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


# ---- GPU (PyTorch) dense linear algebra --------------------------------------
def gpu_scale(matrix: np.ndarray, device: torch.device, scale_max: float) -> torch.Tensor:
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    return torch.clamp((x - mean) / std, max=scale_max)


def gpu_pca(scaled: torch.Tensor, n_comps: int) -> np.ndarray:
    scaled = scaled - scaled.mean(dim=0, keepdim=True)
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    return (u[:, :n_comps] * s[:n_comps]).cpu().numpy()


# ---- canonical HCC-ecosystem markers (identical to hcc-tls-lu2022 for consistency) --
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Hepatocyte": ["ALB", "APOA1", "APOA2", "APOC3", "APOB", "TTR", "TF", "SERPINA1",
                   "FGB", "FGA", "FGG", "ORM1", "HP", "CYP2E1", "CYP3A4", "ASGR1",
                   "GPC3", "AFP", "SPINK1", "AKR1B10"],
    "T/NK": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "CD8B", "IL7R", "TRAC", "CD7",
             "CCL5", "GZMK", "GZMB", "NKG7", "GNLY", "KLRD1", "KLRF1", "NCAM1", "FOXP3"],
    "B": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1",
          "IGKC", "JCHAIN", "DERL3", "BANK1", "CR2"],
    "Myeloid": ["LYZ", "CD68", "CD163", "C1QA", "C1QB", "C1QC", "AIF1", "CSF1R",
                "FCGR3A", "APOE", "MARCO", "VCAN", "S100A8", "S100A9", "FCN1", "CD14",
                "ITGAX", "LAMP3", "CLEC9A"],
    "Endothelial": ["PECAM1", "VWF", "CDH5", "CLDN5", "RAMP2", "EGFL7", "CLEC14A",
                    "AQP1", "FLT1", "ENG", "CLEC4G", "STAB2", "OIT3", "CCL21"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "DCN", "LUM", "PDGFRA", "PDGFRB",
                   "ACTA2", "TAGLN", "RGS5", "MYH11", "MYL9", "BGN"],
}
MALIGNANT_SIG = ["AFP", "GPC3", "SPINK1", "AKR1B10", "CAP2", "MDK", "S100A6", "REG3A",
                 "GDF15", "MID1IP1", "PEG10", "LCN2", "SPP1", "CD24", "TOP2A"]
DIFFERENTIATION_SIG = ["CYP2E1", "CYP3A4", "CYP2A6", "ADH1B", "ADH4", "ALB", "APOA1",
                       "APOC3", "ASGR1", "ASGR2", "HP", "TF", "TTR", "SERPINA1", "ARG1",
                       "PCK1", "CPS1", "GLUL", "APOB"]
PROLIF_SIG = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CCNB2", "CENPF", "UBE2C", "BIRC5", "TYMS"]
HEPATOCYTE_TYPES = {"Hepatocyte"}

TLS_CHEMOKINE_SIG = ["CXCL13", "CCL19", "CCL21", "CXCL9", "CXCL10", "CXCL11", "CCL5", "CCL2"]
B_TLS_SIG = ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1",
             "IGKC", "JCHAIN", "BANK1", "CR2", "FCER2", "LTB"]
TFH_SIG = ["CXCL13", "CXCR5", "PDCD1", "ICOS", "BCL6", "IL21", "TOX", "CD4", "MAF", "CD200"]
TCM_SIG = ["CCR7", "SELL", "TCF7", "IL7R", "LEF1", "CD28", "CD27"]


def present(adata, genes):
    return [g for g in genes if g in adata.var_names]


def score(adata, genes, name):
    g = present(adata, genes)
    if len(g) < 3:
        adata.obs[name] = 0.0
        return
    sc.tl.score_genes(adata, g, score_name=name, use_raw=False)


# ---- load + concatenate the per-sample scBaseCount h5ads ---------------------
CELLTYPE_KEYS = ["cell_type", "cell_type_ontology_term_id", "celltype"]
TISSUE_KEYS = ["tissue", "tissue_ontology_term_id"]
DISEASE_KEYS = ["disease", "disease_ontology_term_id"]


def _first_obs(obs, keys, default=""):
    for k in keys:
        if k in obs.columns:
            return k
    return None


def load_atlas(h5ad_dir: str, max_cells: int) -> tuple[ad.AnnData, pd.DataFrame]:
    files = sorted(glob.glob(os.path.join(h5ad_dir, "*.h5ad")))
    if not files:
        raise SystemExit(f"ERROR: no h5ad files in {h5ad_dir} (run step 1 first).")
    print(f"==> concatenating {len(files)} scBaseCount sample h5ads")
    parts, manifest = [], []
    for f in files:
        srx = os.path.splitext(os.path.basename(f))[0]
        a = sc.read_h5ad(f)
        a.var_names_make_unique()
        # normalise obs covariate names
        ck = _first_obs(a.obs, CELLTYPE_KEYS)
        tk = _first_obs(a.obs, TISSUE_KEYS)
        dk = _first_obs(a.obs, DISEASE_KEYS)
        a.obs["srx"] = srx
        a.obs["author_cell_type"] = a.obs[ck].astype(str).values if ck else "unknown"
        a.obs["tissue"] = a.obs[tk].astype(str).values if tk else "unknown"
        a.obs["disease"] = a.obs[dk].astype(str).values if dk else "unknown"
        a.obs_names = [f"{srx}_{bc}" for bc in a.obs_names]
        keep_cols = ["srx", "author_cell_type", "tissue", "disease"]
        a.obs = a.obs[keep_cols]
        manifest.append({"srx": srx, "n_cells": a.n_obs,
                         "tissue": a.obs["tissue"].iloc[0] if a.n_obs else "",
                         "disease": a.obs["disease"].iloc[0] if a.n_obs else ""})
        parts.append(a)
    adata = ad.concat(parts, join="outer", index_unique=None, fill_value=0)
    adata.obs_names_make_unique()
    print(f"==> concatenated: {adata.n_obs:,} cells × {adata.n_vars:,} genes across {len(files)} samples")
    if max_cells and adata.n_obs > max_cells:
        rng = np.random.default_rng(0)
        idx = rng.choice(adata.n_obs, size=max_cells, replace=False)
        idx.sort()
        adata = adata[idx].copy()
        print(f"==> subsampled to {adata.n_obs:,} cells (--max-cells {max_cells})")
    return adata, pd.DataFrame(manifest)


def annotate_celltypes(adata) -> pd.DataFrame:
    for ct, genes in CELL_TYPE_MARKERS.items():
        score(adata, genes, f"score_{ct}")
    score_cols = [f"score_{ct}" for ct in CELL_TYPE_MARKERS]
    # per-cluster mean lineage score → argmax
    df = adata.obs.groupby("leiden")[score_cols].mean()
    assign = df.idxmax(axis=1).str.replace("score_", "", regex=False)
    adata.obs["cell_type"] = adata.obs["leiden"].map(assign).astype("category")
    rows = []
    for cl in df.index:
        rows.append({"leiden": cl, "cell_type": assign[cl],
                     "n_cells": int((adata.obs["leiden"] == cl).sum()),
                     **{c: float(df.loc[cl, c]) for c in score_cols}})
    return pd.DataFrame(rows)


def split_malignant(adata) -> pd.DataFrame:
    from sklearn.mixture import GaussianMixture
    score(adata, MALIGNANT_SIG, "score_malignant")
    score(adata, DIFFERENTIATION_SIG, "score_hds")
    score(adata, PROLIF_SIG, "score_prolif")
    hep = adata.obs["cell_type"].isin(HEPATOCYTE_TYPES).values
    adata.obs["malignant_call"] = "n/a"
    summ = {"n_hepatocyte": int(hep.sum())}
    if hep.sum() >= 20:
        x = (adata.obs["score_malignant"] - adata.obs["score_hds"]).values[hep].reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=0).fit(x)
        mal_comp = int(np.argmax(gm.means_.ravel()))
        lab = gm.predict(x)
        calls = np.where(lab == mal_comp, "malignant", "normal")
        adata.obs.loc[hep, "malignant_call"] = calls
        summ.update({"n_malignant": int((calls == "malignant").sum()),
                     "n_normal": int((calls == "normal").sum()),
                     "mean_malignancy_score": float(x.mean())})
    return pd.DataFrame([summ])


def tls_module(adata):
    score(adata, TLS_CHEMOKINE_SIG, "score_tls_chemokine")
    score(adata, B_TLS_SIG, "score_B_tls")
    score(adata, TFH_SIG, "score_tfh")
    score(adata, TCM_SIG, "score_tcm")
    adata.obs["is_B"] = (adata.obs["cell_type"] == "B")
    # CXCL13+ Tfh: T/NK cells high on the Tfh program
    tcell = adata.obs["cell_type"] == "T/NK"
    thr = adata.obs.loc[tcell, "score_tfh"].quantile(0.9) if tcell.any() else np.inf
    adata.obs["is_cxcl13_tfh"] = tcell & (adata.obs["score_tfh"] >= thr)


def by_group(adata, group):
    g = adata.obs.groupby(group)
    out = pd.DataFrame({
        "n_cells": g.size(),
        "pct_B": g["is_B"].mean() * 100,
        "pct_cxcl13_tfh": g["is_cxcl13_tfh"].mean() * 100,
        "mean_tls_chemokine": g["score_tls_chemokine"].mean(),
        "mean_tcm": g["score_tcm"].mean(),
    })
    hep = adata.obs["cell_type"].isin(HEPATOCYTE_TYPES)
    mal = adata.obs["malignant_call"] == "malignant"
    denom = adata.obs[hep].groupby(group).size()
    num = adata.obs[hep & mal].groupby(group).size()
    out["pct_malignant_of_hep"] = (num / denom * 100).reindex(out.index)
    return out.reset_index()


def savefig(path):
    plt.tight_layout()
    plt.savefig(path + ".tmp", dpi=130, bbox_inches="tight")
    os.replace(path + ".tmp", path)
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--h5ad-dir", default=os.path.expanduser("~/ghbio-tutorial/data/scbasecount-hcc/h5ad"))
    ap.add_argument("--max-cells", type=int, default=0, help="subsample cap (0 = all)")
    ap.add_argument("--n-pcs", type=int, default=50)
    ap.add_argument("--n-hvg", type=int, default=2000)
    args = ap.parse_args()
    R = args.results
    os.makedirs(R, exist_ok=True)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"==> [02] scBaseCount HCC reanalysis → {R}  (device: {dev})")

    with progress("load + concat sample h5ads"):
        adata, manifest = load_atlas(args.h5ad_dir, args.max_cells)
    manifest.to_csv(os.path.join(R, "sample_manifest.csv"), index=False)
    # save scBaseCount's labels for validation ONLY, then keep as covariate column
    adata.obs[["srx", "author_cell_type", "tissue", "disease"]].to_csv(
        os.path.join(R, "author_labels.csv"))

    with progress("QC filter"):
        adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
        sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], inplace=True, percent_top=None)
        sc.pp.filter_cells(adata, min_genes=200)
        sc.pp.filter_genes(adata, min_cells=3)
        adata = adata[adata.obs["pct_counts_mt"] < 20].copy()
    pd.DataFrame({"n_cells": [adata.n_obs], "n_genes": [adata.n_vars],
                 "median_genes": [float(np.median(adata.obs["n_genes_by_counts"]))]
                 }).to_csv(os.path.join(R, "qc_summary.csv"), index=False)

    with progress("normalise + HVG"):
        adata.layers["counts"] = adata.X.copy()
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        adata.raw = adata
        sc.pp.highly_variable_genes(adata, n_top_genes=args.n_hvg, flavor="seurat")

    with progress(f"GPU scale + PCA ({dev})"):
        hvg = adata[:, adata.var["highly_variable"]].X
        dense = hvg.toarray() if sparse.issparse(hvg) else np.asarray(hvg)
        scaled = gpu_scale(dense, dev, scale_max=10.0)
        adata.obsm["X_pca"] = gpu_pca(scaled, args.n_pcs)

    with progress("Harmony integration across samples (batch=srx)"):
        try:
            import harmonypy
            ho = harmonypy.run_harmony(adata.obsm["X_pca"], adata.obs, ["srx"])
            adata.obsm["X_pca_harmony"] = ho.Z_corr.T
            rep = "X_pca_harmony"
        except Exception as e:
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.")
            rep = "X_pca"

    with progress("neighbours → Leiden → UMAP"):
        sc.pp.neighbors(adata, use_rep=rep, n_neighbors=15)
        sc.tl.leiden(adata, resolution=1.0)
        sc.tl.umap(adata)

    with progress("markers per cluster"):
        sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon", n_genes=25)
        rows = []
        for cl in adata.obs["leiden"].cat.categories:
            names = adata.uns["rank_genes_groups"]["names"][cl]
            for r, g in enumerate(names):
                rows.append({"leiden": cl, "rank": r + 1, "gene": g})
        pd.DataFrame(rows).to_csv(os.path.join(R, "markers_by_cluster.csv"), index=False)

    with progress("cell-type annotation (marker-based, no author labels)"):
        ann = annotate_celltypes(adata)
        ann.to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)

    with progress("unsupervised malignant hepatocyte split (GMM)"):
        split_malignant(adata).to_csv(os.path.join(R, "hepatocyte_summary.csv"), index=False)
        # DE malignant vs normal hepatocyte
        hep = adata[adata.obs["cell_type"].isin(HEPATOCYTE_TYPES)].copy()
        if hep.obs["malignant_call"].nunique() > 1:
            sc.tl.rank_genes_groups(hep, "malignant_call", groups=["malignant"],
                                    reference="normal", method="wilcoxon", n_genes=40)
            de = sc.get.rank_genes_groups_df(hep, group="malignant")
            de.to_csv(os.path.join(R, "malignant_hepatocyte.csv"), index=False)

    with progress("TLS module scoring"):
        tls_module(adata)

    # ---- compositions ---------------------------------------------------------
    comp = (adata.obs.groupby(["cell_type"]).size().rename("n_cells").reset_index())
    comp["pct"] = comp["n_cells"] / comp["n_cells"].sum() * 100
    comp.to_csv(os.path.join(R, "celltype_composition.csv"), index=False)
    by_group(adata, "srx").to_csv(os.path.join(R, "composition_by_sample.csv"), index=False)
    tls_tissue = by_group(adata, "tissue")
    tls_tissue.to_csv(os.path.join(R, "tls_module_by_tissue.csv"), index=False)
    mal_cols = [c for c in ("tissue", "n_cells", "pct_malignant_of_hep") if c in tls_tissue.columns]
    tls_tissue[mal_cols].to_csv(os.path.join(R, "malignant_by_tissue.csv"), index=False)
    by_group(adata, "srx").to_csv(os.path.join(R, "tls_by_sample.csv"), index=False)

    # ---- figures --------------------------------------------------------------
    with progress("figures"):
        sc.pl.umap(adata, color="leiden", show=False, legend_loc="on data", title="Leiden clusters")
        savefig(os.path.join(R, "umap_clusters.png"))
        sc.pl.umap(adata, color="cell_type", show=False, title="Cell types (marker-based)")
        savefig(os.path.join(R, "umap_celltypes.png"))
        sc.pl.umap(adata, color="malignant_call", show=False, title="Malignant hepatocyte call")
        savefig(os.path.join(R, "umap_malignant.png"))
        sc.pl.umap(adata, color="srx", show=False, title="Sample (SRX) — integration check")
        savefig(os.path.join(R, "umap_sample.png"))
        adata.obs["score_tls_niche"] = adata.obs[["score_B_tls", "score_tfh", "score_tls_chemokine"]].mean(axis=1)
        sc.pl.umap(adata, color="score_tls_niche", show=False, title="TLS niche score", color_map="magma")
        savefig(os.path.join(R, "umap_tls.png"))
        # composition bar
        ct = comp.sort_values("n_cells", ascending=False)
        plt.figure(figsize=(6, 4)); plt.bar(ct["cell_type"], ct["pct"])
        plt.ylabel("% of cells"); plt.title("Cell-type composition (pooled HCC atlas)")
        plt.xticks(rotation=30, ha="right"); savefig(os.path.join(R, "composition.png"))
        # TLS by tissue
        tt = tls_tissue.copy()
        gcol = "tissue" if "tissue" in tt else tt.columns[0]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(tt[gcol].astype(str), tt["pct_B"], label="% B", alpha=0.8)
        ax.bar(tt[gcol].astype(str), tt["pct_cxcl13_tfh"], bottom=tt["pct_B"], label="% CXCL13⁺ Tfh", alpha=0.8)
        ax.set_ylabel("% of cells"); ax.set_title("TLS components by tissue"); ax.legend()
        plt.xticks(rotation=30, ha="right"); savefig(os.path.join(R, "tls_by_tissue.png"))

    adata.write(os.path.join(R, "gpu_reanalysis.h5ad"))
    prov = {"pipeline": "scbasecount-hcc", "n_cells": int(adata.n_obs), "n_genes": int(adata.n_vars),
            "n_samples": int(adata.obs["srx"].nunique()), "device": str(dev),
            "integration": rep, "n_pcs": args.n_pcs, "n_hvg": args.n_hvg,
            "source": "Arc Virtual Cell Atlas / scBaseCount (STARsolo, SRAgent-curated)"}
    json.dump(prov, open(os.path.join(R, "provenance.json"), "w"), indent=2)
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"scBaseCount HCC independent GPU reanalysis\n"
                 f"cells={adata.n_obs} genes={adata.n_vars} samples={adata.obs['srx'].nunique()}\n"
                 f"cell types: {dict(adata.obs['cell_type'].value_counts())}\n"
                 f"integration: {rep}\n")
    print("==> [02] Done. Next: 3. 독립 검증 (03_validate.py).")


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        main()
