#!/usr/bin/env bash
"""placeholder"""
#!/usr/bin/env python
# 07_scvi_latent.py
# Stage [latent]: GPU latent representation (scVI) with patient=batch,
# accelerated PCA/neighbors via rapids-singlecell (with CPU fallback).

import os
import sys
import warnings

warnings.filterwarnings("ignore")


def get_results_dir():
    base = os.environ.get("GHBIO_RESULTS")
    if not base:
        base = os.path.join(os.path.expanduser("~"), "ghbio-tutorial", "results")
    os.makedirs(base, exist_ok=True)
    return base


def main():
    import numpy as np
    import scanpy as sc
    import anndata as ad

    results = get_results_dir()
    in_path = os.path.join(results, "adata_norm.h5ad")
    model_dir = os.path.join(results, "model_scvi")
    model_pt = os.path.join(model_dir, "model.pt")
    out_path = os.path.join(results, "adata_latent.h5ad")

    # Idempotency: skip if both outputs already exist.
    if os.path.exists(model_pt) and os.path.exists(out_path):
        print(f"[latent] Outputs already present, skipping:\n  {model_pt}\n  {out_path}")
        return

    if not os.path.exists(in_path):
        sys.exit(f"[latent] ERROR: required input not found: {in_path}")

    print(f"[latent] Loading {in_path}")
    adata = sc.read_h5ad(in_path)
    print(f"[latent] adata: {adata.n_obs} cells x {adata.n_vars} genes")

    # ---- Determine batch key (patient). ---------------------------------
    batch_key = None
    for cand in ("patient", "Patient", "sample", "Sample", "donor"):  # TODO: 확인 필요
        if cand in adata.obs.columns:
            batch_key = cand
            break
    if batch_key is None:
        print("[latent] WARNING: no patient/batch column found; using single batch.")
        adata.obs["_batch"] = "all"
        batch_key = "_batch"
    else:
        print(f"[latent] Using batch key: {batch_key}")
    adata.obs[batch_key] = adata.obs[batch_key].astype("category")

    # ---- Subset to HVGs for scVI if available. --------------------------
    if "highly_variable" in adata.var.columns:
        adata_hvg = adata[:, adata.var["highly_variable"].values].copy()
        print(f"[latent] Using {adata_hvg.n_vars} HVGs for scVI training.")
    else:
        adata_hvg = adata.copy()
        print("[latent] No HVG flag found; using all genes for scVI.")

    # ---- Prepare counts layer for scVI. ---------------------------------
    # scVI expects count-like data. Prefer a stored 'counts' layer (built in
    # 04_build_adata via TPM->pseudo-count inverse). Otherwise fall back to X.
    if "counts" in adata_hvg.layers:
        counts_layer = "counts"
        print("[latent] Using 'counts' layer for scVI likelihood.")
        gene_likelihood = "nb"  # TODO: 확인 필요 (Smart-seq2 pseudo-counts)
    elif "counts" in adata.layers:
        adata_hvg.layers["counts"] = adata[:, adata_hvg.var_names].layers["counts"].copy()
        counts_layer = "counts"
        print("[latent] Copied 'counts' layer from parent for scVI.")
        gene_likelihood = "nb"  # TODO: 확인 필요
    else:
        # No integer counts available (only log-normalized TPM). Round X as an
        # approximate count-like input; NB likelihood tolerates this roughly.
        print("[latent] No counts layer; approximating counts from X.")
        X = adata_hvg.X
        try:
            X = X.toarray()
        except AttributeError:
            X = np.asarray(X)
        adata_hvg.layers["counts"] = np.rint(np.clip(np.expm1(X), 0, None)).astype("float32")
        counts_layer = "counts"
        gene_likelihood = "nb"  # TODO: 확인 필요

    # ---- Train scVI. ----------------------------------------------------
    import scvi

    scvi.settings.seed = 0

    use_gpu = False
    try:
        import torch
        use_gpu = torch.cuda.is_available()
    except Exception:
        use_gpu = False
    accelerator = "gpu" if use_gpu else "cpu"
    print(f"[latent] scVI accelerator: {accelerator}")

    scvi.model.SCVI.setup_anndata(
        adata_hvg,
        layer=counts_layer,
        batch_key=batch_key,
    )

    model = scvi.model.SCVI(
        adata_hvg,
        n_latent=30,          # TODO: 확인 필요
        n_layers=2,
        gene_likelihood=gene_likelihood,
    )

    max_epochs = 400  # TODO: 확인 필요 (small dataset ~5,902 cells)
    print(f"[latent] Training scVI for up to {max_epochs} epochs...")
    model.train(
        max_epochs=max_epochs,
        accelerator=accelerator,
        early_stopping=True,
    )

    # ---- Save model. ----------------------------------------------------
    os.makedirs(model_dir, exist_ok=True)
    model.save(model_dir, overwrite=True, save_anndata=False)
    # scvi writes model.pt inside model_dir; verify it exists.
    if not os.path.exists(model_pt):
        # Some scvi versions name it differently; find the .pt file.
        pts = [f for f in os.listdir(model_dir) if f.endswith(".pt")]
        if pts:
            src = os.path.join(model_dir, pts[0])
            if src != model_pt:
                import shutil
                shutil.copyfile(src, model_pt)
    print(f"[latent] Saved scVI model to {model_dir}")

    # ---- Extract latent representation. ---------------------------------
    latent = model.get_latent_representation()
    adata.obsm["X_scVI"] = latent
    print(f"[latent] Latent representation shape: {latent.shape}")

    # ---- Accelerated PCA/neighbors via rapids-singlecell. ---------------
    used_rsc = False
    try:
        import rapids_singlecell as rsc
        print("[latent] Using rapids-singlecell for neighbors (GPU).")
        rsc.get.anndata_to_GPU(adata)
        rsc.pp.neighbors(adata, use_rep="X_scVI", n_neighbors=15)
        rsc.get.anndata_to_CPU(adata)
        used_rsc = True
    except Exception as e:
        print(f"[latent] rapids-singlecell unavailable ({e}); using scanpy CPU.")

    if not used_rsc:
        sc.pp.neighbors(adata, use_rep="X_scVI", n_neighbors=15)

    # Also compute PCA on scVI latent for downstream convenience.
    try:
        sc.tl.pca(adata, n_comps=min(30, adata.obsm["X_scVI"].shape[1] - 1))
    except Exception as e:
        print(f"[latent] PCA on latent skipped: {e}")

    # ---- Write output. --------------------------------------------------
    tmp_out = out_path + ".tmp.h5ad"
    adata.write_h5ad(tmp_out)
    os.replace(tmp_out, out_path)
    print(f"[latent] Wrote {out_path}")


if __name__ == "__main__":
    main()
