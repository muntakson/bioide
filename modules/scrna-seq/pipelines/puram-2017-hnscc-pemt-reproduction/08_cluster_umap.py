#!/usr/bin/env python
"""08_cluster_umap.py — Clustering (GPU Leiden) and UMAP embedding.

Reads adata_latent.h5ad from the scVI latent step, runs neighbors + Leiden
clustering (GPU-accelerated via rapids-singlecell when available, CPU fallback
otherwise) and computes a UMAP embedding. Writes adata_clustered.h5ad and
umap.png into $GHBIO_RESULTS. Idempotent: skips work if outputs already exist.
"""
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import scanpy as sc
import anndata as ad

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
RESULTS = Path(os.environ.get("GHBIO_RESULTS",
                              str(Path.home() / "ghbio-tutorial" / "results")))
RESULTS.mkdir(parents=True, exist_ok=True)

IN_H5AD = RESULTS / "adata_latent.h5ad"
OUT_H5AD = RESULTS / "adata_clustered.h5ad"
OUT_UMAP = RESULTS / "umap.png"

# Latent representation key produced by the scVI step
LATENT_KEY = "X_scVI"  # TODO: 확인 필요
LEIDEN_RESOLUTION = 1.0  # TODO: 확인 필요
N_NEIGHBORS = 15  # TODO: 확인 필요
RANDOM_STATE = 0

sc.settings.verbosity = 1


def _outputs_exist() -> bool:
    return OUT_H5AD.exists() and OUT_UMAP.exists()


def main() -> int:
    if _outputs_exist():
        print(f"[08_cluster_umap] outputs already present, skipping:\n"
              f"  {OUT_H5AD}\n  {OUT_UMAP}")
        return 0

    if not IN_H5AD.exists():
        print(f"[08_cluster_umap] ERROR: input not found: {IN_H5AD}",
              file=sys.stderr)
        return 1

    print(f"[08_cluster_umap] reading {IN_H5AD}")
    adata = ad.read_h5ad(IN_H5AD)

    # Determine representation to use for neighbors.
    if LATENT_KEY in adata.obsm:
        use_rep = LATENT_KEY
    elif "X_pca" in adata.obsm:
        use_rep = "X_pca"
        print(f"[08_cluster_umap] WARNING: {LATENT_KEY} not found, "
              f"falling back to X_pca")
    else:
        print("[08_cluster_umap] no latent/PCA rep found; computing PCA")
        sc.pp.pca(adata, n_comps=50, random_state=RANDOM_STATE)
        use_rep = "X_pca"

    # -------------------------------------------------------------------
    # Try GPU path via rapids-singlecell; fall back to CPU scanpy.
    # -------------------------------------------------------------------
    gpu_ok = False
    try:
        import rapids_singlecell as rsc  # noqa: F401
        import cupy as cp  # noqa: F401
        gpu_ok = True
        print("[08_cluster_umap] rapids-singlecell available, using GPU path")
    except Exception as exc:  # pragma: no cover
        print(f"[08_cluster_umap] rapids-singlecell unavailable "
              f"({exc}); using CPU scanpy path")

    if gpu_ok:
        try:
            import rapids_singlecell as rsc
            rsc.get.anndata_to_GPU(adata)
            rsc.pp.neighbors(adata, n_neighbors=N_NEIGHBORS, use_rep=use_rep,
                             random_state=RANDOM_STATE)
            rsc.tl.leiden(adata, resolution=LEIDEN_RESOLUTION,
                          random_state=RANDOM_STATE, key_added="leiden")
            rsc.tl.umap(adata, random_state=RANDOM_STATE)
            rsc.get.anndata_to_CPU(adata)
        except Exception as exc:
            print(f"[08_cluster_umap] GPU path failed ({exc}); "
                  f"retrying on CPU")
            gpu_ok = False

    if not gpu_ok:
        sc.pp.neighbors(adata, n_neighbors=N_NEIGHBORS, use_rep=use_rep,
                        random_state=RANDOM_STATE)
        try:
            sc.tl.leiden(adata, resolution=LEIDEN_RESOLUTION,
                         random_state=RANDOM_STATE, key_added="leiden",
                         flavor="igraph", n_iterations=2, directed=False)
        except TypeError:
            sc.tl.leiden(adata, resolution=LEIDEN_RESOLUTION,
                         random_state=RANDOM_STATE, key_added="leiden")
        sc.tl.umap(adata, random_state=RANDOM_STATE)

    n_clusters = adata.obs["leiden"].nunique()
    print(f"[08_cluster_umap] Leiden clusters: {n_clusters}")

    # -------------------------------------------------------------------
    # Plot UMAP colored by cluster (and patient batch if present).
    # -------------------------------------------------------------------
    color_keys = ["leiden"]
    for cand in ("patient", "batch", "sample"):
        if cand in adata.obs.columns:
            color_keys.append(cand)
            break

    fig, axes = plt.subplots(1, len(color_keys),
                             figsize=(6 * len(color_keys), 5))
    if len(color_keys) == 1:
        axes = [axes]
    for axi, key in zip(axes, color_keys):
        sc.pl.umap(adata, color=key, ax=axi, show=False,
                   frameon=False, legend_loc="on data" if key == "leiden"
                   else "right margin")
    fig.tight_layout()

    tmp_png = OUT_UMAP.with_suffix(".png.tmp")
    # The temp name ends in ".tmp", so matplotlib cannot infer the format — set it.
    fig.savefig(tmp_png, dpi=150, bbox_inches="tight", format="png")
    plt.close(fig)
    os.replace(tmp_png, OUT_UMAP)
    print(f"[08_cluster_umap] wrote {OUT_UMAP}")

    # -------------------------------------------------------------------
    # Write clustered AnnData atomically.
    # -------------------------------------------------------------------
    tmp_h5ad = OUT_H5AD.with_suffix(".h5ad.tmp")
    adata.write_h5ad(tmp_h5ad)
    os.replace(tmp_h5ad, OUT_H5AD)
    print(f"[08_cluster_umap] wrote {OUT_H5AD}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
