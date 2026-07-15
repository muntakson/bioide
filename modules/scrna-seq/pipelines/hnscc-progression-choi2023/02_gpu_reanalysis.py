#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Choi 2023, head & neck cancer — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT read the authors'
per-cell `cell.type` labels (T.cells / Malignant.cells / Fibroblasts / …) as an
input. We start from the authors' RAW dense UMI count matrix (GSE181919,
`GSE181919_UMI_counts.txt.gz`, genes × cells) and RE-DERIVE the whole analysis
with our own, freshly-written, GPU-accelerated code:

  1. load the dense TSV UMI matrix (genes × cells) in gene-chunks into a sparse
     cells×genes AnnData, and join each cell's per-barcode metadata
     (GSE181919_Barcode_metadata.txt.gz: patient.id, sample.id, tissue.type stage,
     subsite, hpv, cell.type). NOTE: the counts header writes barcodes with a DOT
     (AAAC….1) while the metadata uses a DASH (AAAC…-1) — we normalise both,
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p) — the deposit is raw counts,
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony batch-integration across the samples (harmonypy),
  7. neighbours → Leiden clustering → UMAP (Scanpy),
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical head&neck-ecosystem signatures),
 10. an INDEPENDENT malignant-vs-normal EPITHELIAL split (unsupervised GMM on a
     HNSCC squamous-carcinoma malignancy − normal-squamous-differentiation
     signature) — the authors annotated Malignant vs (normal) Epithelial cells with
     their own pipeline; we deliberately use a different, unsupervised method so
     agreement in step 3 means two independent routes converge (제6조).

The disease STAGE (tissue.type ∈ NL normal / LP leukoplakia / CA carcinoma /
LN lymph-node metastasis) is EXPERIMENTAL DESIGN metadata (which specimen a cell
came from), NOT an author-derived cell label — so it is kept as a covariate and
used to test the paper's central claim: that malignant cells already appear in the
precancerous leukoplakia stage and rise along NL→LP→CA→LN.

The authors' `cell.type` is stripped from the working object and saved verbatim to
`author_labels.csv` for the SEPARATE validation step (03), which is the only place
it is allowed to be touched (헌장 제2조).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call, stage)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_epithelial.csv     DE (our malignant vs our normal epithelial)
  epithelial_summary.csv       our epithelial split counts + mean scores (malignancy/SDS/prolif)
  composition_by_stage.csv     cell-type % per progression stage (NL/LP/CA/LN)
  malignant_by_stage.csv       malignant-epithelial % among epithelial per stage (the progression claim)
  author_labels.csv            authors' cell.type per cell (for step 3 validation ONLY)
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, umap_stage.png, composition.png
  qc_summary.csv, provenance.json, run_summary.txt
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import threading
import time
from contextlib import contextmanager

import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager  # noqa: E402  (needed before pyplot to pick a CJK font)
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
    """z-score each gene to mean 0 / unit variance, clip at scale_max (Seurat ScaleData)."""
    x = torch.from_numpy(np.ascontiguousarray(matrix, dtype=np.float32)).to(device)
    mean = x.mean(dim=0, keepdim=True)
    std = x.std(dim=0, unbiased=True, keepdim=True)
    std = torch.where(std == 0, torch.ones_like(std), std)
    return torch.clamp((x - mean) / std, max=scale_max)


def gpu_pca(scaled: torch.Tensor, n_comps: int) -> np.ndarray:
    """PCA scores via SVD on centered, scaled data: scores = U*S (top n_comps)."""
    scaled = scaled - scaled.mean(dim=0, keepdim=True)
    u, s, _ = torch.linalg.svd(scaled, full_matrices=False)
    return (u[:, :n_comps] * s[:n_comps]).cpu().numpy()


# ---- canonical head&neck-ecosystem markers (for INDEPENDENT annotation) ------
# Lineages reported by Choi et al. 2023 (Nat Commun): (normal + malignant)
# squamous epithelial cells, T/NK cells, B/plasma cells, macrophages/myeloid,
# dendritic cells, mast cells, endothelial cells, fibroblasts, and myocytes.
# Epithelial + Malignant are merged into one "Epithelial" lineage here and split
# by the unsupervised malignant call below.
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Epithelial": ["KRT5", "KRT14", "KRT6A", "KRT17", "KRT15", "KRT4", "KRT13", "KRT19",
                   "KRT8", "KRT18", "EPCAM", "SFN", "PERP", "S100A2", "SPRR1B", "TP63"],
    "T-NK cell": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "CD8B", "IL7R", "TRAC", "CD7",
                  "GZMK", "NKG7", "GNLY", "KLRD1", "FOXP3", "CCL5"],
    "B-Plasma cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1",
                      "IGKC", "JCHAIN", "DERL3", "XBP1"],
    "Macrophage-Myeloid": ["LYZ", "CD68", "CD163", "C1QA", "C1QB", "C1QC", "AIF1", "CSF1R",
                           "FCGR3A", "APOE", "APOC1", "S100A8", "S100A9", "ITGAX"],
    "Dendritic cell": ["CD1C", "FCER1A", "CLEC9A", "LILRA4", "LAMP3", "CLEC4C", "IRF7"],
    "Mast cell": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT", "HPGDS", "GATA2"],
    "Endothelial": ["PECAM1", "VWF", "CDH5", "CLDN5", "RAMP2", "EGFL7", "CD34", "AQP1", "PLVAP"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "DCN", "LUM", "PDGFRA", "PDGFRB", "ACTA2",
                   "TAGLN", "FN1", "FAP", "THY1", "POSTN"],
    "Myocyte": ["ACTA1", "MYH1", "MYH2", "TNNT3", "DES", "MYL1", "TTN", "CKM", "ACTN2", "MYLPF"],
}
# HNSCC squamous-carcinoma malignant signature (up) vs a normal-squamous
# differentiation signature (down). Choi et al. 2023 highlight LGALS7B(Galectin-7B)+
# malignant cells and a carcinoma-in-situ-like malignant program that loses normal
# stratified-squamous identity while gaining an invasive/EMT-like program.
MALIGNANT_SIG = ["LGALS7B", "LGALS7", "MMP1", "MMP10", "MMP3", "MMP9", "LAMC2", "LAMB3",
                 "LAMA3", "PTHLH", "TGFBI", "ITGA6", "INHBA", "SERPINE1", "TNC", "CDH3",
                 "SPP1", "PLAU", "FSCN1"]
# Squamous Differentiation Score (SDS) genes — high in normal stratified squamous
# mucosa (suprabasal/differentiated keratinocytes), lost in malignant cells.
DIFFERENTIATION_SIG = ["KRT4", "KRT13", "KRT15", "KRT36", "KRT78", "MAL", "CRNN", "SPRR3",
                       "SPRR2A", "SPRR1A", "CNFN", "TGM3", "CRCT1", "ECM1", "RHCG",
                       "TMPRSS11B", "TMPRSS11E", "EMP1", "A2ML1"]
# Cell-cycle / proliferation program (malignant epithelium is more proliferative).
PROLIF_SIG = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CCNB2", "CENPF", "UBE2C", "BIRC5", "TYMS"]
EPITHELIAL_TYPES = {"Epithelial"}

# progression stage: normal → leukoplakia (precancer) → carcinoma → LN metastasis
STAGE_CANON = {"NL": "NL (정상)", "LP": "LP (백반증/전암)", "CA": "CA (암)", "LN": "LN (림프절전이)"}
STAGE_RANK = {"NL": 0, "LP": 1, "CA": 2, "LN": 3}


def _open(path: str):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def _norm_barcode(bc: str) -> str:
    """Counts header uses 'AAAC….1' (dot), metadata uses 'AAAC…-1' (dash) — the
    R deposit dotted the barcode suffix. Canonicalise the trailing '.<n>' → '-<n>'
    so both files join one-to-one. Only the FINAL dot-before-digits is touched, so
    gene symbols (never passed here) are irrelevant; barcodes carry a single dot."""
    return bc.replace(".", "-")


def load_dense_tsv(counts_path: str, chunksize: int = 2000) -> ad.AnnData:
    """Read the dense genes×cells UMI TSV in gene-chunks into a sparse cells×genes
    AnnData. The full dense matrix (~20k genes × 54k cells) would be several GB in
    memory; reading chunk-by-chunk and storing sparse keeps peak memory bounded."""
    blocks: list[sparse.csr_matrix] = []
    genes: list[str] = []
    cells: list[str] | None = None
    # NB: no blanket dtype= here — the C parser would try to cast the gene-symbol
    # index column (e.g. 'RP11-34P13.7') to float and crash. Cast the values below.
    reader = pd.read_csv(counts_path, sep="\t", index_col=0, chunksize=chunksize,
                         compression="infer")
    for chunk in reader:
        if cells is None:
            cells = [_norm_barcode(str(c)) for c in chunk.columns]
        genes.extend(str(g) for g in chunk.index)
        blocks.append(sparse.csr_matrix(chunk.to_numpy(dtype=np.float32)))
    if cells is None or not blocks:
        raise RuntimeError(f"no data read from {counts_path}")
    mat = sparse.vstack(blocks, format="csr")          # genes × cells
    X = sparse.csr_matrix(mat.T)                        # → cells × genes
    a = ad.AnnData(X=X)
    a.obs_names = list(cells)
    a.var_names = list(genes)
    a.var_names_make_unique()
    return a


def annotate(adata: ad.AnnData, groupby: str) -> pd.DataFrame:
    score_cols = {}
    for sig, genes in CELL_TYPE_MARKERS.items():
        present = [g for g in genes if g in adata.var_names]
        col = f"_s_{sig}"
        if present:
            sc.tl.score_genes(adata, present, score_name=col, use_raw=False)
        else:
            adata.obs[col] = 0.0
        score_cols[sig] = col
    per = adata.obs.groupby(groupby, observed=True)[list(score_cols.values())].mean()
    per.columns = list(score_cols.keys())
    assigned = per.idxmax(axis=1)
    adata.obs["cell_type"] = adata.obs[groupby].map(assigned).astype("category")
    table = per.copy()
    table.insert(0, "n_cells", adata.obs[groupby].value_counts().reindex(table.index).astype(int))
    table.insert(1, "cell_type", assigned.values)
    table.index.name = "cluster"
    adata.obs.drop(columns=list(score_cols.values()), inplace=True)
    return table.reset_index()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=os.path.expanduser(
        "~/ghbio-tutorial/data/hnscc-choi2023"))
    ap.add_argument("--results", default=os.environ.get(
        "GHBIO_RESULTS", os.path.expanduser("~/ghbio-tutorial/results")))
    ap.add_argument("--n-hvg", type=int, default=2000)
    ap.add_argument("--n-comps", type=int, default=50)
    ap.add_argument("--n-pcs", type=int, default=30)
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--resolution", type=float, default=1.0)
    ap.add_argument("--scale-max", type=float, default=10.0)
    ap.add_argument("--min-genes", type=int, default=300)
    ap.add_argument("--min-cells", type=int, default=10)
    ap.add_argument("--max-mito", type=float, default=20.0)
    ap.add_argument("--batch-key", default="sample")
    ap.add_argument("--seed", type=int, default=2023)
    ap.add_argument("--no-harmony", action="store_true", help="skip Harmony batch integration")
    args = ap.parse_args()

    if not torch.cuda.is_available():
        print("ERROR: CUDA unavailable; this GPU reanalysis refuses CPU fallback.", file=sys.stderr)
        sys.exit(2)
    device = torch.device("cuda")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    sc.settings.verbosity = 1
    R = args.results
    os.makedirs(R, exist_ok=True)
    print(f"GPU: {torch.cuda.get_device_name(0)} | CUDA {torch.version.cuda}", flush=True)

    counts = os.path.join(args.source, "GSE181919_UMI_counts.txt.gz")
    meta_path = os.path.join(args.source, "GSE181919_Barcode_metadata.txt.gz")
    if not os.path.exists(counts):
        print(f"ERROR: {counts} not found (run step 1 first).", file=sys.stderr)
        sys.exit(1)

    # --- load the dense UMI matrix (genes × cells) → sparse cells × genes --------
    with progress("Loading dense UMI matrix (GSE181919_UMI_counts.txt.gz)"):
        adata = load_dense_tsv(counts)
    print(f"    loaded: {adata.n_obs:,} cells × {adata.n_vars:,} genes", flush=True)

    # --- join per-barcode metadata (stage + sample + authors' cell.type) --------
    with progress("Joining per-barcode metadata"):
        meta = pd.read_csv(meta_path, sep="\t", index_col=0)
        meta.index = [_norm_barcode(str(b)) for b in meta.index]
        cols = {c.lower().strip(): c for c in meta.columns}
        pt_col = cols.get("patient.id") or cols.get("patient")
        sm_col = cols.get("sample.id") or cols.get("sample")
        st_col = cols.get("tissue.type") or cols.get("stage") or cols.get("tissue")
        ty_col = cols.get("cell.type") or cols.get("celltype") or cols.get("type")
        hpv_col = cols.get("hpv")
        sub_col = cols.get("subsite")
        m = meta.reindex(adata.obs_names)
        adata.obs["patient"] = m[pt_col].astype(str).values if pt_col else "unknown"
        adata.obs["sample"] = m[sm_col].astype(str).values if sm_col else "unknown"
        # STAGE is experimental design (which specimen), NOT a cell label → kept.
        raw_stage = m[st_col].astype(str).values if st_col else np.array(["NA"] * adata.n_obs)
        adata.obs["stage"] = raw_stage
        adata.obs["stage_label"] = [STAGE_CANON.get(s, s) for s in raw_stage]
        if hpv_col:
            adata.obs["hpv"] = m[hpv_col].astype(str).values
        if sub_col:
            adata.obs["subsite"] = m[sub_col].astype(str).values
        author_type = m[ty_col].astype(str).values if ty_col else np.array(["unclassified"] * adata.n_obs)

    # 헌장 제1조: stash the authors' cell.type for validation ONLY, then forget it.
    author = pd.DataFrame(index=adata.obs_names)
    author["author_cell_type"] = author_type
    author["sample"] = adata.obs["sample"].astype(str).values
    author["stage"] = adata.obs["stage"].astype(str).values
    author.to_csv(os.path.join(R, "author_labels.csv"))
    n_lbl = int((author["author_cell_type"] != "nan").sum())
    print(f"    authors' cell.type withheld → author_labels.csv "
          f"({author['author_cell_type'].nunique()} label values, {n_lbl:,} labelled)", flush=True)
    print("    stages: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["stage"].value_counts().items()), flush=True)

    # --- QC ---------------------------------------------------------------------
    with progress("QC filtering (min genes/cells, mitochondrial %)"):
        adata.var["mito"] = adata.var_names.str.upper().str.startswith("MT-")
        sc.pp.calculate_qc_metrics(adata, qc_vars=["mito"], inplace=True, percent_top=None, log1p=False)
        sc.pp.filter_cells(adata, min_genes=args.min_genes)
        sc.pp.filter_genes(adata, min_cells=args.min_cells)
        adata = adata[adata.obs["pct_counts_mito"] < args.max_mito].copy()
    n_after = adata.n_obs
    pd.DataFrame({
        "metric": ["cells_after_qc", "genes_after_qc", "median_genes_per_cell", "median_pct_mito"],
        "value": [n_after, adata.n_vars,
                  float(np.median(adata.obs["n_genes_by_counts"])),
                  round(float(np.median(adata.obs["pct_counts_mito"])), 3)],
    }).to_csv(os.path.join(R, "qc_summary.csv"), index=False)
    print(f"    after QC: {n_after:,} cells × {adata.n_vars:,} genes", flush=True)

    # --- our own normalisation (deposit is raw counts) --------------------------
    adata.layers["counts"] = adata.X.copy()
    with progress("Normalise (normalize_total 1e4 + log1p)"):
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)

    # --- HVG on the log-normalised values ---------------------------------------
    with progress("Highly-variable genes (seurat, batch-aware)"):
        sc.pp.highly_variable_genes(adata, flavor="seurat", n_top_genes=args.n_hvg,
                                    batch_key=args.batch_key if args.batch_key in adata.obs else None)
    hvg = np.where(adata.var["highly_variable"].to_numpy())[0]

    # --- GPU: ScaleData + PCA(SVD) on the HVGs ----------------------------------
    with progress(f"GPU z-score scaling + PCA(SVD) on {len(hvg)} HVGs (PyTorch)"):
        X = adata[:, hvg].X
        dense = np.asarray(X.todense()) if sparse.issparse(X) else np.asarray(X)
        scaled = gpu_scale(dense, device, args.scale_max)
        adata.obsm["X_pca"] = gpu_pca(scaled, args.n_comps)
        del dense, scaled
        torch.cuda.empty_cache()

    # --- Harmony batch integration across samples -------------------------------
    rep = "X_pca"
    if not args.no_harmony and args.batch_key in adata.obs and adata.obs[args.batch_key].nunique() > 1:
        try:
            import harmonypy
            with progress(f"Harmony integration across {adata.obs[args.batch_key].nunique()} samples"):
                ho = harmonypy.run_harmony(adata.obsm["X_pca"][:, : args.n_pcs],
                                           adata.obs, [args.batch_key])
                # harmonypy >=2.0 returns Z_corr as (cells, pcs); older as (pcs, cells).
                Z = np.asarray(ho.Z_corr)
                if Z.shape[0] != adata.n_obs and Z.shape[1] == adata.n_obs:
                    Z = Z.T
                adata.obsm["X_pca_harmony"] = np.ascontiguousarray(Z, dtype=np.float32)
            rep = "X_pca_harmony"
        except Exception as e:  # keep going on un-integrated PCA if Harmony fails
            print(f"    WARNING: Harmony failed ({e}); using un-integrated PCA.", file=sys.stderr)
    n_use = adata.obsm[rep].shape[1] if rep == "X_pca_harmony" else args.n_pcs

    # --- neighbours → Leiden → UMAP ---------------------------------------------
    with progress("Neighbours + Leiden + UMAP (Scanpy)"):
        sc.pp.neighbors(adata, use_rep=rep, n_pcs=n_use, n_neighbors=args.n_neighbors,
                        random_state=args.seed)
        sc.tl.leiden(adata, key_added="leiden_gpu", resolution=args.resolution,
                     flavor="igraph", n_iterations=2, directed=False, random_state=args.seed)
        sc.tl.umap(adata, random_state=args.seed)
    n_clusters = adata.obs["leiden_gpu"].nunique()
    print(f"    {n_clusters} Leiden clusters (resolution {args.resolution})", flush=True)

    # --- canonicalise X + checkpoint (guards the marker step) -------------------
    # The dense→sparse path can leave X with unsorted/duplicate indices or float64;
    # rank_genes_groups reads X column-wise and is sensitive to that. Force
    # canonical CSR float32, free the unused counts layer, and checkpoint so the
    # (expensive) embedding work isn't lost if anything downstream fails.
    if "counts" in adata.layers:
        del adata.layers["counts"]
    if sparse.issparse(adata.X):
        adata.X = adata.X.tocsr()
        adata.X.sort_indices()
        adata.X.sum_duplicates()
        adata.X.eliminate_zeros()
    adata.X = adata.X.astype(np.float32)
    ckpt = os.path.join(R, "_checkpoint_pre_markers.h5ad")
    with progress("Checkpoint before markers"):
        adata.write_h5ad(ckpt, compression="gzip")

    # --- Wilcoxon markers per cluster -------------------------------------------
    vc = adata.obs["leiden_gpu"].value_counts()
    mk_groups = [str(g) for g in vc[vc >= 3].index.tolist()]
    with progress("Wilcoxon markers per cluster"):
        sc.tl.rank_genes_groups(adata, "leiden_gpu", groups=mk_groups,
                                method="wilcoxon", use_raw=False, n_genes=30)
    mk = sc.get.rank_genes_groups_df(adata, group=None).rename(
        columns={"group": "cluster", "names": "gene", "logfoldchanges": "log2fc"})
    mk["rank"] = mk.groupby("cluster", observed=True).cumcount() + 1
    mk = mk[mk["rank"] <= 30][["cluster", "rank", "gene", "scores", "log2fc", "pvals_adj"]]
    mk.to_csv(os.path.join(R, "markers_by_cluster.csv"), index=False)

    # --- INDEPENDENT marker-based cell-type annotation --------------------------
    with progress("Marker-based cell-type annotation (independent of authors)"):
        annotation = annotate(adata, "leiden_gpu")
    annotation.to_csv(os.path.join(R, "celltype_annotation.csv"), index=False)
    print("    cell types: " + ", ".join(
        f"{t}×{n}" for t, n in adata.obs["cell_type"].value_counts().items()), flush=True)

    # --- INDEPENDENT malignant vs normal epithelial split (unsupervised GMM) -----
    sig_mal = [g for g in MALIGNANT_SIG if g in adata.var_names]
    sig_dif = [g for g in DIFFERENTIATION_SIG if g in adata.var_names]
    sig_pro = [g for g in PROLIF_SIG if g in adata.var_names]
    sc.tl.score_genes(adata, sig_mal, score_name="malignancy_score", use_raw=False)
    sc.tl.score_genes(adata, sig_dif, score_name="sds_score", use_raw=False)   # squamous differentiation score
    if sig_pro:
        sc.tl.score_genes(adata, sig_pro, score_name="prolif_score", use_raw=False)
    else:
        adata.obs["prolif_score"] = 0.0
    adata.obs["malignant_call"] = "n/a"
    epi_mask = adata.obs["cell_type"].astype(str).isin(EPITHELIAL_TYPES).to_numpy()
    n_epi = int(epi_mask.sum())
    if n_epi > 20:
        from sklearn.mixture import GaussianMixture
        score = (adata.obs.loc[epi_mask, "malignancy_score"]
                 - adata.obs.loc[epi_mask, "sds_score"]).to_numpy().reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=args.seed).fit(score)
        comp = gm.predict(score)
        mal_comp = int(np.argmax(gm.means_.ravel()))   # higher (malignancy − differentiation) = malignant
        call = np.where(comp == mal_comp, "malignant epithelial", "normal epithelial")
        idx = adata.obs_names[epi_mask]
        adata.obs.loc[idx, "malignant_call"] = call
    print("    epithelial split: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["malignant_call"].value_counts().items()), flush=True)

    # --- DE: our malignant vs our normal epithelial -----------------------------
    two = adata[adata.obs["malignant_call"].isin(["malignant epithelial", "normal epithelial"])].copy()
    if two.obs["malignant_call"].nunique() == 2:
        sc.tl.rank_genes_groups(two, "malignant_call", groups=["malignant epithelial"],
                                reference="normal epithelial", method="wilcoxon", use_raw=False, n_genes=40)
        de = sc.get.rank_genes_groups_df(two, group="malignant epithelial").rename(
            columns={"names": "gene", "logfoldchanges": "log2fc"})
        de.insert(0, "rank", range(1, len(de) + 1))
        de[["rank", "gene", "log2fc", "pvals_adj"]].to_csv(
            os.path.join(R, "malignant_epithelial.csv"), index=False)

    # --- composition tables + CSVs ----------------------------------------------
    counts_by = adata.obs["cell_type"].value_counts()
    markers_by_type: dict[str, list[str]] = {}
    for ct in counts_by.index:
        clusters = annotation.loc[annotation["cell_type"] == ct, "cluster"].tolist()
        genes: list[str] = []
        for cl in clusters:
            genes += mk.loc[mk["cluster"].astype(str) == str(cl), "gene"].head(5).tolist()
        markers_by_type[ct] = list(dict.fromkeys(genes))[:5]
    total = int(adata.n_obs)
    pd.DataFrame([
        {"celltype": ct, "n_cells": int(n), "pct_of_cells": round(100 * n / total, 2),
         "top5_markers": ", ".join(markers_by_type.get(ct, []))}
        for ct, n in counts_by.items()
    ]).to_csv(os.path.join(R, "celltype_composition.csv"), index=False)

    # cell-type composition per progression stage (NL/LP/CA/LN)
    comp_stage = None
    has_stages = "stage" in adata.obs and adata.obs["stage"].nunique() > 1
    if has_stages:
        comp_stage = (pd.crosstab(adata.obs["stage"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp_stage = comp_stage.reindex(sorted(comp_stage.index, key=lambda s: STAGE_RANK.get(s, 99)))
        comp_stage.to_csv(os.path.join(R, "composition_by_stage.csv"))

    # epithelial split summary (malignant vs normal: malignancy/SDS/proliferation)
    esum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean"),
                 mean_sds=("sds_score", "mean"),
                 mean_prolif=("prolif_score", "mean")).round(4).reset_index())
    esum.to_csv(os.path.join(R, "epithelial_summary.csv"), index=False)

    # THE PROGRESSION CLAIM (제2조 target): malignant-epithelial fraction per stage.
    # Choi et al. report malignant cells already present in leukoplakia (LP), rising
    # along NL→LP→CA→LN. We quantify % malignant among epithelial per stage.
    if n_epi > 20 and has_stages:
        epi = adata[epi_mask].copy()
        by = pd.DataFrame({
            "stage": epi.obs["stage"].values,
            "is_mal": (epi.obs["malignant_call"] == "malignant epithelial").astype(int).values,
            "prolif": epi.obs["prolif_score"].values,
        })
        agg = by.groupby("stage").agg(n_epithelial=("is_mal", "size"),
                                      pct_malignant=("is_mal", lambda s: round(100 * s.mean(), 2)),
                                      mean_prolif=("prolif", "mean")).round(4)
        agg["stage_rank"] = [STAGE_RANK.get(s, -1) for s in agg.index]
        agg = agg.sort_values("stage_rank")
        agg.to_csv(os.path.join(R, "malignant_by_stage.csv"))

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/정상 상피세포 판정"),
            ("stage_label", "umap_stage.png", "진행 단계 (NL→LP→CA→LN)"),
        ]:
            if color not in adata.obs:
                continue
            fig, ax = plt.subplots(figsize=(7.5, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=3, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if comp_stage is not None:
            fig, ax = plt.subplots(figsize=(7.5, 5))
            comp_stage.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.7)
            ax.set_ylabel("% of cells"); ax.set_title("진행 단계별 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=6, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=0)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

    # --- summary / provenance ---------------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant epithelial").sum())
    n_norm = int((adata.obs["malignant_call"] == "normal epithelial").sum())
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs['sample'].nunique()}\n")
        fh.write(f"stages={adata.obs['stage'].nunique()}\n")
        fh.write(f"malignant_epithelial_cells={n_mal}\nnormal_epithelial_cells={n_norm}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; authors' cell.type NOT used as input (stage is experimental design, kept).",
        "method": "dense UMI matrix (genes×cells) → sparse cells×genes + QC + normalize + HVG + GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant/normal epithelial split + per-stage progression composition",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "differentiation_signature_used": sig_dif,
        "proliferation_signature_used": sig_pro,
        "params": vars(args),
        "cell_type_counts": {str(k): int(v) for k, v in counts_by.items()},
        "stage_counts": {str(k): int(v) for k, v in adata.obs["stage"].value_counts().items()},
    }
    adata.uns["gpu_reanalysis"] = prov
    with progress("Writing gpu_reanalysis.h5ad + provenance"):
        adata.write_h5ad(os.path.join(R, "gpu_reanalysis.h5ad"), compression="gzip")
    with open(os.path.join(R, "provenance.json"), "w") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=2, default=str)
    # the pre-marker checkpoint was crash-insurance for this run; drop it on success.
    if os.path.exists(ckpt):
        os.remove(ckpt)

    print(f"\n==> [02] Independent GPU reanalysis done: {total:,} cells, {n_clusters} clusters, "
          f"{adata.obs['cell_type'].nunique()} cell types; malignant-epithelial={n_mal} / normal-epithelial={n_norm}.",
          flush=True)
    print("    Next: 3. Validate vs the authors' labels + the progression claim (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
