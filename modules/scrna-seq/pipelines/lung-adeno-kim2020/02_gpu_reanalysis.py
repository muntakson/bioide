#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Kim 2020, lung adenocarcinoma — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT read the authors'
per-cell `Cell_type` / `Cell_subtype` labels (T lymphocytes / Malignant cells /
Myeloid cells / …) as an input. We start from the authors' RAW dense UMI count
matrix (GSE131907_Lung_Cancer_raw_UMI_matrix.txt.gz, genes × cells) and RE-DERIVE
the whole analysis with our own, freshly-written, GPU-accelerated code:

  1. load the dense TSV UMI matrix (genes × cells) in gene-chunks into a sparse
     cells×genes AnnData (208k cells — the full dense read would be >10 GB, so we
     stream it chunk-by-chunk and keep it sparse), and join each cell's per-barcode
     metadata (GSE131907_Lung_Cancer_cell_annotation.txt.gz: Sample, Sample_Origin,
     Cell_type, Cell_subtype). The matrix column headers and the annotation `Index`
     use the SAME `<barcode>_<Sample>` id, so they join one-to-one,
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p) — the deposit is raw counts,
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony batch-integration across the samples (harmonypy),
  7. neighbours → Leiden clustering → UMAP (Scanpy),
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical lung-ecosystem signatures),
 10. an INDEPENDENT malignant-vs-normal EPITHELIAL split (unsupervised GMM on a
     lung-adenocarcinoma malignancy − normal-alveolar/airway-differentiation
     signature) — the authors annotated "Malignant cells" with their own pipeline;
     we deliberately use a different, unsupervised method so agreement in step 3
     means two independent routes converge (제6조).

The tissue ORIGIN (Sample_Origin ∈ nLung normal lung / tLung primary tumour /
tL/B advanced primary / nLN normal LN / mLN metastatic LN / mBrain brain metastasis
/ PE pleural effusion) is EXPERIMENTAL DESIGN metadata (which specimen a cell came
from), NOT an author-derived cell label — so it is kept as a covariate and used to
test the paper's claims about the normal→tumour→metastasis axis (malignant epithelial
enriched in tumour/metastatic origins; myeloid infiltration of metastatic LN).

The authors' `Cell_type`/`Cell_subtype` are stripped from the working object and
saved verbatim to `author_labels.csv` for the SEPARATE validation step (03), which
is the only place they are allowed to be touched (헌장 제2조).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call, origin)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_epithelial.csv     DE (our malignant vs our normal epithelial)
  epithelial_summary.csv       our epithelial split counts + mean scores (malignancy/ADS/prolif)
  composition_by_origin.csv    cell-type % per tissue origin (nLung/tLung/…/mBrain)
  malignant_by_origin.csv      malignant-epithelial % among epithelial per origin (the progression claim)
  author_labels.csv            authors' Cell_type + Cell_subtype per cell (for step 3 validation ONLY)
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, umap_origin.png, composition.png
  qc_summary.csv, provenance.json, run_summary.txt
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
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


# ---- canonical lung-ecosystem markers (for INDEPENDENT annotation) -----------
# Lineages reported by Kim et al. 2020: epithelial (normal alveolar/airway +
# malignant), T lymphocytes, NK cells, B/plasma, myeloid (macrophage/monocyte/DC),
# mast, endothelial, fibroblast, and oligodendrocytes (from the brain-metastasis
# samples). Epithelial + malignant are merged into one "Epithelial" lineage here
# and split by the unsupervised malignant call below.
CELL_TYPE_MARKERS: dict[str, list[str]] = {
    "Epithelial": ["EPCAM", "KRT8", "KRT18", "KRT19", "KRT7", "SFTPC", "SFTPB", "SFTPA1",
                   "SFTPA2", "NAPSA", "SCGB1A1", "SCGB3A1", "AGER", "CLDN18", "MUC1"],
    "T cell": ["CD3D", "CD3E", "CD3G", "CD2", "CD8A", "CD8B", "IL7R", "TRAC", "CD7",
               "CCL5", "GZMK", "FOXP3"],
    "NK cell": ["NKG7", "GNLY", "KLRD1", "KLRF1", "NCR1", "NCAM1", "PRF1", "KLRC1", "TYROBP"],
    "B-Plasma cell": ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1",
                      "IGKC", "JCHAIN", "DERL3"],
    "Myeloid": ["LYZ", "CD68", "CD163", "C1QA", "C1QB", "C1QC", "AIF1", "CSF1R", "FCGR3A",
                "APOE", "MARCO", "FABP4", "S100A8", "S100A9", "FCN1", "CD14", "ITGAX", "LAMP3"],
    "Mast cell": ["TPSAB1", "TPSB2", "CPA3", "MS4A2", "KIT", "HPGDS", "GATA2"],
    "Endothelial": ["PECAM1", "VWF", "CDH5", "CLDN5", "RAMP2", "EGFL7", "CLEC14A", "AQP1", "CCL21"],
    "Fibroblast": ["COL1A1", "COL1A2", "COL3A1", "DCN", "LUM", "PDGFRA", "PDGFRB", "ACTA2",
                   "TAGLN", "FN1", "ELN", "MYH11"],
    "Oligodendrocyte": ["PLP1", "MBP", "MOG", "MAG", "MOBP", "CLDN11", "SOX10", "CNP"],
}
# Lung-adenocarcinoma malignant epithelial signature (up) vs a normal
# alveolar/airway differentiation signature (down). Kim et al. 2020 report tumour
# epithelial states (tS1/tS2/tS3) that diverge from the normal AT2 differentiation
# trajectory; malignant cells lose normal lung-epithelial identity while gaining a
# carcinoma program.
MALIGNANT_SIG = ["CEACAM5", "CEACAM6", "KRT19", "KRT17", "KRT8", "MUC1", "S100P", "LCN2",
                 "SLPI", "MDK", "SPINK1", "TFF3", "CLDN4", "MMP7", "LAMC2", "GPRC5A", "CD24"]
# Alveolar/airway Differentiation Score (ADS) genes — high in normal lung epithelium
# (AT1/AT2/club/ciliated), lost in malignant cells.
DIFFERENTIATION_SIG = ["SFTPC", "SFTPB", "SFTPA1", "SFTPA2", "SFTPD", "NAPSA", "PGC", "ABCA3",
                       "LAMP3", "AGER", "PDPN", "CLDN18", "SCGB1A1", "SCGB3A1", "MUC5B", "SCGB3A2"]
# Cell-cycle / proliferation program (malignant epithelium is more proliferative).
PROLIF_SIG = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CCNB2", "CENPF", "UBE2C", "BIRC5", "TYMS"]
EPITHELIAL_TYPES = {"Epithelial"}

# tissue origin: normal → primary tumour → LN metastasis → distant metastasis.
ORIGIN_CANON = {
    "nLung": "nLung (정상 폐)", "tLung": "tLung (원발 종양)", "tL/B": "tL/B (진행 원발종양)",
    "nLN": "nLN (정상 림프절)", "mLN": "mLN (전이 림프절)", "mBrain": "mBrain (뇌 전이)",
    "PE": "PE (흉수)",
}
# rank for ordering figures/tables along the metastasis axis (normal → distant met)
ORIGIN_RANK = {"nLung": 0, "nLN": 0, "tLung": 1, "tL/B": 2, "mLN": 3, "PE": 3, "mBrain": 4}
# origins that are tumour-bearing / metastatic (malignant expected) vs normal
TUMOR_ORIGINS = {"tLung", "tL/B", "mLN", "mBrain", "PE"}
NORMAL_ORIGINS = {"nLung", "nLN"}


def _open(path: str):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


# Byte offset (past the header line) where the gene rows begin — set per worker via
# the initializer so each process knows the numeric column count and file path.
_W: dict = {}


def _worker_init(path: str, n_cells: int) -> None:
    _W["path"] = path
    _W["n_cells"] = n_cells


def _parse_byte_range(rng: tuple[int, int, int]) -> tuple[str, int, int]:
    """Parse the gene rows whose START byte falls in [start, end) of the decompressed
    TSV, in a SEPARATE PROCESS (no GIL, no shared-allocator contention → real N× scaling).
    np.fromstring tokenises each row in C; we keep only nonzeros (matrix is ~96% zero)
    and write this shard's CSR block to a temp .npz, returning its path + gene names so
    the parent doesn't pickle hundreds of MB back through the pipe."""
    idx, start, end = rng
    path, n_cells = _W["path"], _W["n_cells"]
    data: list[np.ndarray] = []
    indices: list[np.ndarray] = []
    indptr: list[int] = [0]
    genes: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # np.fromstring text mode is deprecated but fastest
        with open(path, "rb") as f:
            f.seek(start)
            if idx > 0:                      # a line straddling `start` belongs to the previous shard;
                f.readline()                 # shard 0 starts exactly on the first gene line (no skip)
            while f.tell() < end:
                raw = f.readline()
                if not raw:
                    break
                t = raw.index(b"\t")
                genes.append(raw[:t].decode())
                row = np.fromstring(raw[t + 1:], sep="\t", dtype=np.float32)   # length = n_cells
                nz = np.nonzero(row)[0]
                indices.append(nz.astype(np.int32))
                data.append(row[nz])
                indptr.append(indptr[-1] + nz.size)
    out = os.path.join(tempfile.gettempdir(), f"lung_shard_{idx:04d}.npz")
    np.savez(out,
             data=np.concatenate(data) if data else np.zeros(0, np.float32),
             indices=np.concatenate(indices) if indices else np.zeros(0, np.int32),
             indptr=np.asarray(indptr, dtype=np.int64),
             genes=np.asarray(genes, dtype=object))
    return out, idx, len(genes)


def load_dense_tsv(counts_path: str, workers: int = 16) -> ad.AnnData:
    """Read the dense genes×cells UMI TSV into a sparse cells×genes AnnData — FAST.

    The deposit is a pathological shape: ~29k genes × 208,506 cells, i.e. a 208k-COLUMN
    dense text grid. pandas.read_csv builds per-column machinery for all 208k columns
    and crawls (~30 min). Text tokenisation is inherently CPU work — a GPU CSV reader
    (cuDF) is columnar and chokes on 208k columns just the same, and an in-process
    ThreadPool is throttled by the GIL + the shared malloc lock (each row allocs a
    208k-float buffer). So we decompress ONCE to a temp file and fan the parse out over
    `workers` SEPARATE PROCESSES, each owning a disjoint byte range — true N× scaling,
    no shared-lock contention. Each shard keeps only nonzeros and hands back a temp
    .npz; the parent stitches the CSR blocks in gene order. Result is cached to h5ad by
    the caller so re-runs are instant."""
    # 1) decompress once to a plain temp file (gzip is inherently sequential) ----------
    if counts_path.endswith(".gz"):
        tmp = tempfile.NamedTemporaryFile(prefix="lung_counts_", suffix=".tsv", delete=False)
        plain = tmp.name
        with gzip.open(counts_path, "rb") as src:
            shutil.copyfileobj(src, tmp, length=1 << 22)
        tmp.close()
    else:
        plain = counts_path

    try:
        # 2) read the header + find where the gene rows start ---------------------------
        with open(plain, "rb") as f:
            header = f.readline()
            body_start = f.tell()
            file_end = f.seek(0, os.SEEK_END)
        cells = [c.decode() for c in header.rstrip(b"\n").split(b"\t")[1:]]   # 1st header cell = gene axis
        n_cells = len(cells)

        # 3) split the body into `workers` contiguous byte ranges -----------------------
        span = file_end - body_start
        n = max(1, workers)
        edges = [body_start + (span * i) // n for i in range(n)] + [file_end]
        ranges = [(i, edges[i], edges[i + 1]) for i in range(n) if edges[i] < edges[i + 1]]

        # 4) parse shards in parallel processes -----------------------------------------
        shards: list[tuple[str, int, int]] = []
        with ProcessPoolExecutor(max_workers=n, initializer=_worker_init,
                                 initargs=(plain, n_cells)) as ex:
            for out, idx, ngenes in ex.map(_parse_byte_range, ranges):
                shards.append((out, idx, ngenes))
                print(f"    …shard {idx} parsed ({ngenes:,} genes)", flush=True)
    finally:
        if plain != counts_path and os.path.exists(plain):
            os.remove(plain)

    # 5) stitch shard CSR blocks back together in gene order ----------------------------
    shards.sort(key=lambda s: s[1])
    data_all, ind_all, indptr_all, genes = [], [], [np.zeros(1, dtype=np.int64)], []
    offset = 0
    for out, _idx, _ng in shards:
        z = np.load(out, allow_pickle=True)
        d, ix, ip, gs = z["data"], z["indices"], z["indptr"], z["genes"]
        data_all.append(d)
        ind_all.append(ix)
        indptr_all.append(ip[1:] + offset)      # drop the leading 0, rebase onto running offset
        offset += ip[-1]
        genes.extend(str(g) for g in gs)
        z.close()
        os.remove(out)
    if not genes:
        raise RuntimeError(f"no data read from {counts_path}")
    G = sparse.csr_matrix(
        (np.concatenate(data_all), np.concatenate(ind_all), np.concatenate(indptr_all)),
        shape=(len(genes), n_cells),
    )                                                       # genes × cells
    X = G.T.tocsr()                                         # → cells × genes
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
        "~/ghbio-tutorial/data/lung-kim2020"))
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
    ap.add_argument("--max-cells", type=int, default=0,
                    help="optional random subsample cap for a faster run (0 = use all 208k cells)")
    ap.add_argument("--batch-key", default="sample")
    ap.add_argument("--seed", type=int, default=2020)
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

    counts = os.path.join(args.source, "GSE131907_Lung_Cancer_raw_UMI_matrix.txt.gz")
    meta_path = os.path.join(args.source, "GSE131907_Lung_Cancer_cell_annotation.txt.gz")
    if not os.path.exists(counts):
        print(f"ERROR: {counts} not found (run step 1 first).", file=sys.stderr)
        sys.exit(1)

    # --- load the dense UMI matrix (genes × cells) → sparse cells × genes --------
    # One-time cache: the first parse writes a compact sparse h5ad next to the raw
    # deposit; every later run (and the report/AI steps) load it in seconds instead
    # of re-tokenising 6 billion text fields. Invalidated if the .gz is newer.
    cache = os.path.join(args.source, "GSE131907_raw_counts.h5ad")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(counts):
        with progress("Loading cached raw counts (GSE131907_raw_counts.h5ad)"):
            adata = ad.read_h5ad(cache)
    else:
        with progress("Parsing dense UMI matrix (GSE131907, 208k cells) — parallel CPU tokenise"):
            adata = load_dense_tsv(counts)
        with progress("Caching raw counts → GSE131907_raw_counts.h5ad (one-time)"):
            try:
                adata.write_h5ad(cache, compression="lzf")
            except Exception as e:
                print(f"    WARNING: could not write raw-counts cache ({e}); continuing.", file=sys.stderr)
    print(f"    loaded: {adata.n_obs:,} cells × {adata.n_vars:,} genes", flush=True)

    # --- join per-barcode metadata (origin + sample + authors' Cell_type/subtype) -
    with progress("Joining per-barcode annotation"):
        meta = pd.read_csv(meta_path, sep="\t", index_col=0)
        meta.index = meta.index.astype(str)
        cols = {c.lower().strip(): c for c in meta.columns}
        sm_col = cols.get("sample")
        or_col = cols.get("sample_origin") or cols.get("origin")
        ty_col = cols.get("cell_type") or cols.get("celltype")
        sub_col = cols.get("cell_subtype") or cols.get("cell_subtype".replace("_", "."))
        m = meta.reindex(adata.obs_names)
        adata.obs["sample"] = m[sm_col].astype(str).values if sm_col else "unknown"
        # ORIGIN is experimental design (which specimen), NOT a cell label → kept.
        raw_origin = m[or_col].astype(str).values if or_col else np.array(["NA"] * adata.n_obs)
        adata.obs["origin"] = raw_origin
        adata.obs["origin_label"] = [ORIGIN_CANON.get(s, s) for s in raw_origin]
        author_type = m[ty_col].astype(str).values if ty_col else np.array(["unclassified"] * adata.n_obs)
        author_sub = m[sub_col].astype(str).values if sub_col else np.array(["NA"] * adata.n_obs)

    # optional subsample (keeps the run tractable if requested) --------------------
    if args.max_cells and adata.n_obs > args.max_cells:
        rng = np.random.default_rng(args.seed)
        keep = rng.choice(adata.n_obs, size=args.max_cells, replace=False)
        keep.sort()
        adata = adata[keep].copy()
        author_type = author_type[keep]
        author_sub = author_sub[keep]
        print(f"    subsampled → {adata.n_obs:,} cells (--max-cells {args.max_cells})", flush=True)

    # 헌장 제1조: stash the authors' labels for validation ONLY, then forget them.
    author = pd.DataFrame(index=adata.obs_names)
    author["author_cell_type"] = author_type
    author["author_subtype"] = author_sub
    author["sample"] = adata.obs["sample"].astype(str).values
    author["origin"] = adata.obs["origin"].astype(str).values
    author.to_csv(os.path.join(R, "author_labels.csv"))
    print(f"    authors' Cell_type/Cell_subtype withheld → author_labels.csv "
          f"({author['author_cell_type'].nunique()} cell types, "
          f"{int((author['author_subtype']=='Malignant cells').sum()):,} author-malignant)", flush=True)
    print("    origins: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["origin"].value_counts().items()), flush=True)

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
    sc.tl.score_genes(adata, sig_dif, score_name="ads_score", use_raw=False)   # alveolar differentiation score
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
                 - adata.obs.loc[epi_mask, "ads_score"]).to_numpy().reshape(-1, 1)
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

    # cell-type composition per tissue origin (nLung/tLung/…/mBrain)
    comp_origin = None
    has_origins = "origin" in adata.obs and adata.obs["origin"].nunique() > 1
    if has_origins:
        comp_origin = (pd.crosstab(adata.obs["origin"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp_origin = comp_origin.reindex(sorted(comp_origin.index, key=lambda s: ORIGIN_RANK.get(s, 99)))
        comp_origin.to_csv(os.path.join(R, "composition_by_origin.csv"))

    # epithelial split summary (malignant vs normal: malignancy/ADS/proliferation)
    esum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean"),
                 mean_ads=("ads_score", "mean"),
                 mean_prolif=("prolif_score", "mean")).round(4).reset_index())
    esum.to_csv(os.path.join(R, "epithelial_summary.csv"), index=False)

    # THE PROGRESSION CLAIM (제2조 target): malignant-epithelial fraction per origin.
    # Kim et al. report malignant epithelial cells enriched in tumour/metastatic
    # tissue vs normal lung/LN. We quantify % malignant among epithelial per origin.
    if n_epi > 20 and has_origins:
        epi = adata[epi_mask].copy()
        by = pd.DataFrame({
            "origin": epi.obs["origin"].values,
            "is_mal": (epi.obs["malignant_call"] == "malignant epithelial").astype(int).values,
            "prolif": epi.obs["prolif_score"].values,
        })
        agg = by.groupby("origin").agg(n_epithelial=("is_mal", "size"),
                                       pct_malignant=("is_mal", lambda s: round(100 * s.mean(), 2)),
                                       mean_prolif=("prolif", "mean")).round(4)
        agg["origin_rank"] = [ORIGIN_RANK.get(s, -1) for s in agg.index]
        agg = agg.sort_values("origin_rank")
        agg.to_csv(os.path.join(R, "malignant_by_origin.csv"))

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/정상 상피세포 판정"),
            ("origin_label", "umap_origin.png", "조직 기원 (정상 폐→종양→전이)"),
        ]:
            if color not in adata.obs:
                continue
            fig, ax = plt.subplots(figsize=(8, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=2, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if comp_origin is not None:
            fig, ax = plt.subplots(figsize=(8, 5))
            comp_origin.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.8)
            ax.set_ylabel("% of cells"); ax.set_title("조직 기원별 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=6, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=20)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

    # --- summary / provenance ---------------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant epithelial").sum())
    n_norm = int((adata.obs["malignant_call"] == "normal epithelial").sum())
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs['sample'].nunique()}\n")
        fh.write(f"origins={adata.obs['origin'].nunique()}\n")
        fh.write(f"malignant_epithelial_cells={n_mal}\nnormal_epithelial_cells={n_norm}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; authors' Cell_type/Cell_subtype NOT used as input (Sample_Origin is experimental design, kept).",
        "method": "dense UMI matrix (genes×cells) → sparse cells×genes + QC + normalize + HVG + GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant/normal epithelial split + per-origin progression composition",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "differentiation_signature_used": sig_dif,
        "proliferation_signature_used": sig_pro,
        "params": vars(args),
        "cell_type_counts": {str(k): int(v) for k, v in counts_by.items()},
        "origin_counts": {str(k): int(v) for k, v in adata.obs["origin"].value_counts().items()},
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
