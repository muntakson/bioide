#!/usr/bin/env python
"""
01_tme_integrate.py  —  Use 1 · integrate the non-malignant (TME) cells.

Concatenates every harmonized/<study>.tme.h5ad on the common-gene set, picks
batch-aware HVGs, and integrates across `sample` (+ platform covariate):
  - if every study has recovered raw counts -> scVI (GPU),
  - else -> Harmony on log-normalised PCA (graceful fallback so the scaffold
    runs today even before counts are recovered for the 10x studies).
Then neighbours -> Leiden -> UMAP. Writes the integrated atlas + UMAP figures.

Outputs ($GHBIO_RESULTS):
  tme_atlas.h5ad
  umap_tme_lineage.png  umap_tme_cancer.png  umap_tme_leiden.png
  tme_integration_summary.txt
"""
from __future__ import annotations
import argparse, os, glob
from pathlib import Path
import numpy as np, pandas as pd, scanpy as sc, anndata as ad
import anndata as _adcfg
try: _adcfg.settings.allow_write_nullable_strings=True
except Exception: pass
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_tme(results: Path) -> ad.AnnData:
    files = sorted(glob.glob(str(results / "harmonized" / "*.tme.h5ad")))
    if not files:
        raise SystemExit("No harmonized/*.tme.h5ad — run Stage 0 (run_harmonize.sh) first.")
    common = (results / "common_genes.txt").read_text().split()
    parts = []
    for f in files:
        a = sc.read_h5ad(f)
        keep = [g for g in common if g in a.var_names]
        parts.append(a[:, keep].copy())
    adata = ad.concat(parts, join="inner", index_unique="-")
    print(f"==> TME concat: {adata.n_obs:,} cells x {adata.n_vars:,} genes "
          f"from {len(files)} studies")
    return adata


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.environ.get("GHBIO_RESULTS",
                    os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--max-per-sample", type=int, default=0,
                    help="subsample cap per sample to balance big-4 studies (0=off)")
    args = ap.parse_args()
    R = Path(args.results)

    adata = load_tme(R)

    # optional balancing subsample (big-4 studies otherwise dominate)
    if args.max_per_sample > 0:
        idx = (adata.obs.groupby("sample", observed=True)
               .apply(lambda d: d.sample(min(len(d), args.max_per_sample), random_state=0))
               .index.get_level_values(-1))
        adata = adata[adata.obs_names.isin(idx)].copy()
        print(f"==> balanced to {adata.n_obs:,} cells (<= {args.max_per_sample}/sample)")

    counts_ok = all(f in adata.layers for f in ["counts"]) and \
        adata.layers["counts"] is not None
    # normalise for HVG / fallback
    if "counts" in adata.layers:
        adata.X = adata.layers["counts"].copy()
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    adata.raw = adata
    sc.pp.highly_variable_genes(adata, n_top_genes=2000, batch_key="study_id")
    adata = adata[:, adata.var.highly_variable].copy()

    method = "none"
    if counts_ok:
        try:
            import scvi
            scvi.settings.seed = 0
            lay = adata.copy(); lay.X = lay.layers["counts"]
            scvi.model.SCVI.setup_anndata(lay, batch_key="sample",
                                          categorical_covariate_keys=["platform"])
            m = scvi.model.SCVI(lay, n_latent=30)
            m.train(max_epochs=200, early_stopping=True)
            adata.obsm["X_emb"] = m.get_latent_representation()
            method = "scVI"
        except Exception as e:
            print(f"!! scVI failed ({e}); falling back to Harmony.")
    if "X_emb" not in adata.obsm:
        sc.pp.scale(adata, max_value=10)
        sc.tl.pca(adata, n_comps=30)
        try:
            # call harmonypy directly — the scanpy wrapper's obsm write-back is
            # brittle across versions (shape-mismatch on assignment)
            import harmonypy
            ho = harmonypy.run_harmony(adata.obsm["X_pca"], adata.obs, ["sample"])
            # harmonypy >=2.0 returns Z_corr already as (cells, PCs) — no transpose
            Z = np.asarray(ho.Z_corr)
            if Z.shape[0] != adata.n_obs:  # older harmonypy = (PCs, cells)
                Z = Z.T
            adata.obsm["X_emb"] = Z; method = "Harmony"
        except Exception as e:
            print(f"!! Harmony failed ({e}); using raw PCA.")
            adata.obsm["X_emb"] = adata.obsm["X_pca"]; method = "PCA(uncorrected)"

    sc.pp.neighbors(adata, use_rep="X_emb")
    # fast igraph backend — leidenalg is ~10-100x slower at this cell count
    sc.tl.leiden(adata, resolution=1.0, key_added="leiden",
                 flavor="igraph", n_iterations=2, directed=False)
    sc.tl.umap(adata)

    for color, fn in [("cell_lineage", "umap_tme_lineage.png"),
                      ("cancer", "umap_tme_cancer.png"),
                      ("leiden", "umap_tme_leiden.png")]:
        sc.pl.umap(adata, color=color, show=False, size=3, legend_fontsize=6)
        plt.savefig(R / fn, dpi=130, bbox_inches="tight"); plt.close()

    adata.write_h5ad(R / "tme_atlas.h5ad")
    (R / "tme_integration_summary.txt").write_text(
        f"integration_method={method}\ncells={adata.n_obs}\nhvg={adata.n_vars}\n"
        f"studies={adata.obs.study_id.nunique()}\nleiden_clusters={adata.obs.leiden.nunique()}\n")
    print(f"==> [01] Done ({method}). tme_atlas.h5ad written. Next: 2. annotate.")


if __name__ == "__main__":
    main()
