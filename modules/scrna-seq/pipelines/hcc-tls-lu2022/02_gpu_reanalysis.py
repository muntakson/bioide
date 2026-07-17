#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
02_gpu_reanalysis.py  (Lu 2022, HCC ecosystem / TLS — INDEPENDENT GPU reanalysis)

BioIDE 헌장 제1조 (Reproduce, don't consume): we DO NOT read the authors'
per-cell `celltype` labels (T/NK / Hepatocyte / Myeloid / B / Endothelial /
Fibroblast) as an input. We start from the authors' RAW dense UMI count matrix
(GSE149614_HCC.scRNAseq.S71915.count.txt.gz, genes × cells) and RE-DERIVE the
whole analysis with our own, freshly-written, GPU-accelerated code:

  1. load the dense TSV UMI matrix (genes × cells; the header row is the cell
     barcodes) in gene-chunks into a sparse cells×genes AnnData, and join each
     cell's per-barcode metadata (GSE149614_HCC.metadata.updated.txt.gz:
     Cell, sample, site, patient, stage, virus, celltype). The matrix column
     headers and the metadata `Cell` id are the SAME `<sample>_<barcode>` string,
     so they join one-to-one,
  2. QC filter (min genes/cells, mitochondrial %),
  3. our own normalisation (normalize_total + log1p) — the deposit is raw counts,
  4. highly-variable genes,
  5. **GPU (PyTorch)** z-score scaling + PCA (SVD) — the heavy dense algebra,
  6. Harmony batch-integration across the samples (harmonypy),
  7. neighbours → Leiden clustering → UMAP (Scanpy),
  8. Wilcoxon markers per cluster,
  9. marker-based cell-type annotation (canonical HCC-ecosystem signatures),
 10. an INDEPENDENT malignant-vs-normal HEPATOCYTE split (unsupervised GMM on an
     HCC-malignancy − mature-hepatocyte-differentiation signature),
 11. a **TLS (tertiary lymphoid structure) module**: per-cell scores for the
     B/plasma, CXCL13⁺ Tfh, TLS-chemokine (CXCL13/CCL19/CCL21/CXCL9-11) and
     central-memory-T programs that define an intratumoral lymphoid aggregate,
     then per-site / per-sample aggregates that test the paper's TLS claim.

The tissue SITE (Normal liver / Tumor primary HCC / PVTT portal-vein tumour
thrombus / Lymph metastatic node) is EXPERIMENTAL DESIGN metadata (which specimen
a cell came from), NOT an author-derived cell label — so it is kept as a covariate
and used to test the paper's claims: malignant hepatocytes enriched in
tumour/metastatic sites, and TLS (B / Tfh / CXCL13) enrichment in intratumoral
tissue.

The authors' `celltype` is stripped from the working object and saved verbatim to
`author_labels.csv` for the SEPARATE validation step (03), which is the only place
it is allowed to be touched (헌장 제2조).

Outputs (into $GHBIO_RESULTS):
  gpu_reanalysis.h5ad          our processed object (latent, clusters, cell_type, malignant_call, site, tls scores)
  celltype_annotation.csv      per-cluster: cell_type + lineage scores + n_cells
  markers_by_cluster.csv       Wilcoxon markers per Leiden cluster
  celltype_composition.csv     per cell-type counts / % / top markers
  malignant_hepatocyte.csv     DE (our malignant vs our normal hepatocyte)
  hepatocyte_summary.csv       our hepatocyte split counts + mean scores (malignancy/diff/prolif)
  composition_by_site.csv      cell-type % per tissue site (Normal/Tumor/PVTT/Lymph)
  malignant_by_site.csv        malignant-hepatocyte % among hepatocytes per site (the progression claim)
  tls_module_by_site.csv       TLS score · B% · Tfh% · Tcm% · chemokine expr per site (the TLS claim)
  tls_by_sample.csv            per-sample TLS score / B-fraction / central-memory-T signature (for correlation)
  author_labels.csv            authors' celltype per cell (for step 3 validation ONLY)
  umap_celltypes.png, umap_clusters.png, umap_malignant.png, umap_site.png, umap_tls.png, composition.png, tls_by_site.png
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


# ---- canonical HCC-ecosystem markers (for INDEPENDENT annotation) ------------
# Lineages reported by Lu et al. 2022: hepatocyte (normal + malignant), T/NK,
# B (incl. plasma), myeloid (macrophage/monocyte/DC), endothelial (incl. liver
# LSEC), fibroblast/stellate. We deliberately re-derive these WITHOUT the authors'
# labels; the malignant hepatocyte split is a separate unsupervised call below.
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
# HCC malignant hepatocyte signature (up) vs a mature-hepatocyte differentiation
# signature (down). Lu et al. 2022 report malignant hepatocytes that lose normal
# liver-metabolic identity while gaining an HCC program (AFP/GPC3/SPINK1…).
MALIGNANT_SIG = ["AFP", "GPC3", "SPINK1", "AKR1B10", "CAP2", "MDK", "S100A6", "REG3A",
                 "GDF15", "MID1IP1", "PEG10", "LCN2", "SPP1", "CD24", "TOP2A"]
# Mature-hepatocyte / metabolic Differentiation Score (HDS) genes — high in normal
# hepatocytes, lost in malignant cells.
DIFFERENTIATION_SIG = ["CYP2E1", "CYP3A4", "CYP2A6", "ADH1B", "ADH4", "ALB", "APOA1",
                       "APOC3", "ASGR1", "ASGR2", "HP", "TF", "TTR", "SERPINA1", "ARG1",
                       "PCK1", "CPS1", "GLUL", "APOB"]
# Cell-cycle / proliferation program (malignant hepatocytes are more proliferative).
PROLIF_SIG = ["MKI67", "TOP2A", "PCNA", "CCNB1", "CCNB2", "CENPF", "UBE2C", "BIRC5", "TYMS"]
HEPATOCYTE_TYPES = {"Hepatocyte"}

# ---- TLS (tertiary lymphoid structure) programs ------------------------------
# A TLS is an organised lymphoid aggregate that forms inside tumour tissue: naïve/
# germinal-centre B cells + antibody-producing plasma cells, CXCL13⁺ T-follicular-
# helper cells, follicular DCs, and a defining chemokine milieu (CXCL13 recruits
# CXCR5⁺ B/Tfh; CCL19/CCL21 recruit CCR7⁺ naïve/central-memory T). Fridman and
# colleagues showed intratumoral TLS predict better survival and immunotherapy
# response, and that CCL21/CXCL13 can seed TLS de novo. We re-derive these programs
# from expression alone (no author labels) and quantify them by tissue site.
TLS_CHEMOKINE_SIG = ["CXCL13", "CCL19", "CCL21", "CXCL9", "CXCL10", "CXCL11", "CCL5", "CCL2"]
B_TLS_SIG = ["CD79A", "CD79B", "MS4A1", "CD19", "IGHM", "IGHD", "MZB1", "IGHG1",
             "IGKC", "JCHAIN", "BANK1", "CR2", "FCER2", "LTB"]
TFH_SIG = ["CXCL13", "CXCR5", "PDCD1", "ICOS", "BCL6", "IL21", "TOX", "CD4", "MAF", "CD200"]
# central-memory T program — the paper's specific TLS claim (Tcm enriched in TLS).
TCM_SIG = ["CCR7", "SELL", "TCF7", "IL7R", "LEF1", "CD28", "CD27"]
# Composite "TLS niche" score: the organised-lymphoid-aggregate signature.
TLS_NICHE_SIG = sorted(set(TLS_CHEMOKINE_SIG + B_TLS_SIG + TFH_SIG))

# tissue site: normal → primary tumour → vascular/LN metastasis.
SITE_CANON = {
    "Normal": "Normal (정상 간)", "Tumor": "Tumor (원발 종양)",
    "PVTT": "PVTT (문맥 종양전)", "Lymph": "Lymph (전이 림프절)",
}
# rank for ordering figures/tables along the progression axis (normal → metastasis)
SITE_RANK = {"Normal": 0, "Tumor": 1, "PVTT": 2, "Lymph": 3}
# sites that are tumour-bearing / metastatic (malignant expected) vs normal
TUMOR_SITES = {"Tumor", "PVTT", "Lymph"}
NORMAL_SITES = {"Normal"}


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
    np.fromstring tokenises each row in C; we keep only nonzeros (matrix is mostly zero)
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
    out = os.path.join(tempfile.gettempdir(), f"hcc_shard_{idx:04d}.npz")
    np.savez(out,
             data=np.concatenate(data) if data else np.zeros(0, np.float32),
             indices=np.concatenate(indices) if indices else np.zeros(0, np.int32),
             indptr=np.asarray(indptr, dtype=np.int64),
             genes=np.asarray(genes, dtype=object))
    return out, idx, len(genes)


def load_dense_tsv(counts_path: str, workers: int = 16) -> ad.AnnData:
    """Read the dense genes×cells UMI TSV into a sparse cells×genes AnnData — FAST.

    The deposit is ~20k genes × 71,915 cells, i.e. a 71k-COLUMN dense text grid.
    pandas.read_csv builds per-column machinery for all 71k columns and crawls; a
    GPU CSV reader (cuDF) is columnar and chokes on 71k columns just the same, and
    an in-process ThreadPool is throttled by the GIL + the shared malloc lock. So we
    decompress ONCE to a temp file and fan the parse out over `workers` SEPARATE
    PROCESSES, each owning a disjoint byte range — true N× scaling, no shared-lock
    contention. Each shard keeps only nonzeros and hands back a temp .npz; the parent
    stitches the CSR blocks in gene order. Result is cached to h5ad by the caller so
    re-runs are instant.

    NOTE on orientation: this file's header row is the cell barcodes with NO leading
    axis-label token (unlike some deposits), so we detect the header layout from the
    first data row's field count rather than assuming a leading label."""
    # 1) decompress once to a plain temp file (gzip is inherently sequential) ----------
    if counts_path.endswith(".gz"):
        tmp = tempfile.NamedTemporaryFile(prefix="hcc_counts_", suffix=".tsv", delete=False)
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
            first_row = f.readline()            # peek one data row to learn the layout
            file_end = f.seek(0, os.SEEK_END)
        hdr_tokens = [c.decode() for c in header.rstrip(b"\n").rstrip(b"\r").split(b"\t")]
        n_fields = len(first_row.rstrip(b"\n").rstrip(b"\r").split(b"\t"))  # 1 gene + n_cells values
        n_cells = n_fields - 1
        if len(hdr_tokens) == n_cells:
            cells = hdr_tokens                  # header is pure cell barcodes (this deposit)
        elif len(hdr_tokens) == n_cells + 1:
            cells = hdr_tokens[1:]              # header has a leading gene-axis label → drop it
        else:                                   # be forgiving: trust the data-row width
            cells = hdr_tokens[-n_cells:] if len(hdr_tokens) >= n_cells else hdr_tokens
            print(f"    WARNING: header tokens ({len(hdr_tokens)}) != n_cells "
                  f"({n_cells}); using last {len(cells)} header tokens as cells.", file=sys.stderr)

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
        "~/ghbio-tutorial/data/hcc-lu2022"))
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
                    help="optional random subsample cap for a faster run (0 = use all 72k cells)")
    ap.add_argument("--batch-key", default="sample")
    ap.add_argument("--seed", type=int, default=2022)
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

    counts = os.path.join(args.source, "GSE149614_HCC.scRNAseq.S71915.count.txt.gz")
    meta_path = os.path.join(args.source, "GSE149614_HCC.metadata.updated.txt.gz")
    if not os.path.exists(counts):
        print(f"ERROR: {counts} not found (run step 1 first).", file=sys.stderr)
        sys.exit(1)

    # --- load the dense UMI matrix (genes × cells) → sparse cells × genes --------
    # One-time cache: the first parse writes a compact sparse h5ad next to the raw
    # deposit; every later run (and the report/AI steps) load it in seconds instead
    # of re-tokenising billions of text fields. Invalidated if the .gz is newer.
    cache = os.path.join(args.source, "GSE149614_raw_counts.h5ad")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(counts):
        with progress("Loading cached raw counts (GSE149614_raw_counts.h5ad)"):
            adata = ad.read_h5ad(cache)
    else:
        with progress("Parsing dense UMI matrix (GSE149614, 72k cells) — parallel CPU tokenise"):
            adata = load_dense_tsv(counts)
        with progress("Caching raw counts → GSE149614_raw_counts.h5ad (one-time)"):
            try:
                adata.write_h5ad(cache, compression="lzf")
            except Exception as e:
                print(f"    WARNING: could not write raw-counts cache ({e}); continuing.", file=sys.stderr)
    print(f"    loaded: {adata.n_obs:,} cells × {adata.n_vars:,} genes", flush=True)

    # --- join per-barcode metadata (site + sample + authors' celltype) -----------
    with progress("Joining per-barcode annotation"):
        meta = pd.read_csv(meta_path, sep="\t", index_col=0)
        meta.index = meta.index.astype(str)
        cols = {c.lower().strip(): c for c in meta.columns}
        sm_col = cols.get("sample")
        st_col = cols.get("site") or cols.get("tissue")
        pt_col = cols.get("patient")
        ty_col = cols.get("celltype") or cols.get("cell_type")
        m = meta.reindex(adata.obs_names)
        adata.obs["sample"] = m[sm_col].astype(str).values if sm_col else "unknown"
        adata.obs["patient"] = m[pt_col].astype(str).values if pt_col else "NA"
        # SITE is experimental design (which specimen), NOT a cell label → kept.
        raw_site = m[st_col].astype(str).values if st_col else np.array(["NA"] * adata.n_obs)
        adata.obs["site"] = raw_site
        adata.obs["site_label"] = [SITE_CANON.get(s, s) for s in raw_site]
        author_type = m[ty_col].astype(str).values if ty_col else np.array(["unclassified"] * adata.n_obs)

    # optional subsample (keeps the run tractable if requested) --------------------
    if args.max_cells and adata.n_obs > args.max_cells:
        rng = np.random.default_rng(args.seed)
        keep = rng.choice(adata.n_obs, size=args.max_cells, replace=False)
        keep.sort()
        adata = adata[keep].copy()
        author_type = author_type[keep]
        print(f"    subsampled → {adata.n_obs:,} cells (--max-cells {args.max_cells})", flush=True)

    # 헌장 제1조: stash the authors' labels for validation ONLY, then forget them.
    author = pd.DataFrame(index=adata.obs_names)
    author["author_cell_type"] = author_type
    author["sample"] = adata.obs["sample"].astype(str).values
    author["site"] = adata.obs["site"].astype(str).values
    author["patient"] = adata.obs["patient"].astype(str).values
    author.to_csv(os.path.join(R, "author_labels.csv"))
    print(f"    authors' celltype withheld → author_labels.csv "
          f"({author['author_cell_type'].nunique()} cell types)", flush=True)
    print("    sites: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["site"].value_counts().items()), flush=True)

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

    # --- INDEPENDENT malignant vs normal hepatocyte split (unsupervised GMM) ------
    sig_mal = [g for g in MALIGNANT_SIG if g in adata.var_names]
    sig_dif = [g for g in DIFFERENTIATION_SIG if g in adata.var_names]
    sig_pro = [g for g in PROLIF_SIG if g in adata.var_names]
    sc.tl.score_genes(adata, sig_mal, score_name="malignancy_score", use_raw=False)
    sc.tl.score_genes(adata, sig_dif, score_name="hds_score", use_raw=False)   # hepatocyte differentiation score
    if sig_pro:
        sc.tl.score_genes(adata, sig_pro, score_name="prolif_score", use_raw=False)
    else:
        adata.obs["prolif_score"] = 0.0
    adata.obs["malignant_call"] = "n/a"
    hep_mask = adata.obs["cell_type"].astype(str).isin(HEPATOCYTE_TYPES).to_numpy()
    n_hep = int(hep_mask.sum())
    if n_hep > 20:
        from sklearn.mixture import GaussianMixture
        score = (adata.obs.loc[hep_mask, "malignancy_score"]
                 - adata.obs.loc[hep_mask, "hds_score"]).to_numpy().reshape(-1, 1)
        gm = GaussianMixture(n_components=2, random_state=args.seed).fit(score)
        comp = gm.predict(score)
        mal_comp = int(np.argmax(gm.means_.ravel()))   # higher (malignancy − differentiation) = malignant
        call = np.where(comp == mal_comp, "malignant hepatocyte", "normal hepatocyte")
        idx = adata.obs_names[hep_mask]
        adata.obs.loc[idx, "malignant_call"] = call
    print("    hepatocyte split: " + ", ".join(
        f"{k}×{v}" for k, v in adata.obs["malignant_call"].value_counts().items()), flush=True)

    # --- TLS module scoring (per-cell) ------------------------------------------
    # Score each cell for the programs that build a tertiary lymphoid structure.
    with progress("Scoring TLS programs (B/plasma · CXCL13⁺ Tfh · TLS chemokines · Tcm)"):
        for sig, name in [(TLS_NICHE_SIG, "tls_score"), (TLS_CHEMOKINE_SIG, "tls_chemokine_score"),
                          (B_TLS_SIG, "b_tls_score"), (TFH_SIG, "tfh_score"), (TCM_SIG, "tcm_score")]:
            present = [g for g in sig if g in adata.var_names]
            if present:
                sc.tl.score_genes(adata, present, score_name=name, use_raw=False)
            else:
                adata.obs[name] = 0.0
        # CXCL13 is THE canonical TLS chemokine — track it explicitly if present.
        adata.obs["CXCL13_expr"] = (
            np.asarray(adata[:, "CXCL13"].X.todense()).ravel()
            if "CXCL13" in adata.var_names else 0.0)

    # --- DE: our malignant vs our normal hepatocyte -----------------------------
    two = adata[adata.obs["malignant_call"].isin(["malignant hepatocyte", "normal hepatocyte"])].copy()
    if two.obs["malignant_call"].nunique() == 2:
        sc.tl.rank_genes_groups(two, "malignant_call", groups=["malignant hepatocyte"],
                                reference="normal hepatocyte", method="wilcoxon", use_raw=False, n_genes=40)
        de = sc.get.rank_genes_groups_df(two, group="malignant hepatocyte").rename(
            columns={"names": "gene", "logfoldchanges": "log2fc"})
        de.insert(0, "rank", range(1, len(de) + 1))
        de[["rank", "gene", "log2fc", "pvals_adj"]].to_csv(
            os.path.join(R, "malignant_hepatocyte.csv"), index=False)

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

    # cell-type composition per tissue site (Normal/Tumor/PVTT/Lymph)
    comp_site = None
    has_sites = "site" in adata.obs and adata.obs["site"].nunique() > 1
    if has_sites:
        comp_site = (pd.crosstab(adata.obs["site"], adata.obs["cell_type"], normalize="index") * 100).round(2)
        comp_site = comp_site.reindex(sorted(comp_site.index, key=lambda s: SITE_RANK.get(s, 99)))
        comp_site.to_csv(os.path.join(R, "composition_by_site.csv"))

    # hepatocyte split summary (malignant vs normal: malignancy/HDS/proliferation)
    hsum = (adata.obs[adata.obs["malignant_call"] != "n/a"]
            .groupby("malignant_call")
            .agg(n_cells=("malignancy_score", "size"),
                 mean_malignancy=("malignancy_score", "mean"),
                 mean_hds=("hds_score", "mean"),
                 mean_prolif=("prolif_score", "mean")).round(4).reset_index())
    hsum.to_csv(os.path.join(R, "hepatocyte_summary.csv"), index=False)

    # THE PROGRESSION CLAIM (제2조 target): malignant-hepatocyte fraction per site.
    if n_hep > 20 and has_sites:
        hep = adata[hep_mask].copy()
        by = pd.DataFrame({
            "site": hep.obs["site"].values,
            "is_mal": (hep.obs["malignant_call"] == "malignant hepatocyte").astype(int).values,
            "prolif": hep.obs["prolif_score"].values,
        })
        agg = by.groupby("site").agg(n_hepatocyte=("is_mal", "size"),
                                     pct_malignant=("is_mal", lambda s: round(100 * s.mean(), 2)),
                                     mean_prolif=("prolif", "mean")).round(4)
        agg["site_rank"] = [SITE_RANK.get(s, -1) for s in agg.index]
        agg = agg.sort_values("site_rank")
        agg.to_csv(os.path.join(R, "malignant_by_site.csv"))

    # THE TLS CLAIM (제2조 target): TLS module by tissue site.
    # A TLS forms inside tumour tissue → B/plasma + CXCL13⁺ Tfh + chemokine milieu +
    # central-memory T should be enriched in tumour/metastatic sites vs normal liver.
    tls_site = None
    if has_sites:
        tnk_mask = adata.obs["cell_type"].astype(str) == "T/NK"
        rows_ts = []
        for s in sorted(adata.obs["site"].unique(), key=lambda x: SITE_RANK.get(x, 99)):
            m = adata.obs["site"] == s
            n = int(m.sum())
            b_pct = 100 * float((adata.obs.loc[m, "cell_type"].astype(str) == "B").mean())
            tnk_pct = 100 * float((adata.obs.loc[m, "cell_type"].astype(str) == "T/NK").mean())
            # Tfh & Tcm quantified within the T/NK compartment of that site.
            tnk_here = m.to_numpy() & tnk_mask.to_numpy()
            tfh_pct = (100 * float((adata.obs.loc[tnk_here, "tfh_score"] > 0).mean())
                       if tnk_here.sum() else float("nan"))
            tcm_pct = (100 * float((adata.obs.loc[tnk_here, "tcm_score"] > 0).mean())
                       if tnk_here.sum() else float("nan"))
            rows_ts.append({
                "site": s,
                "n_cells": n,
                "pct_B": round(b_pct, 2),
                "pct_TNK": round(tnk_pct, 2),
                "pct_Tfh_of_TNK": round(tfh_pct, 2),
                "pct_Tcm_of_TNK": round(tcm_pct, 2),
                "mean_tls_score": round(float(adata.obs.loc[m, "tls_score"].mean()), 4),
                "mean_tls_chemokine": round(float(adata.obs.loc[m, "tls_chemokine_score"].mean()), 4),
                "mean_CXCL13": round(float(adata.obs.loc[m, "CXCL13_expr"].mean()), 4),
                "site_rank": SITE_RANK.get(s, -1),
            })
        tls_site = pd.DataFrame(rows_ts).set_index("site")
        tls_site.to_csv(os.path.join(R, "tls_module_by_site.csv"))

    # Per-sample TLS aggregate (for the Tcm–TLS correlation the paper implies).
    if "sample" in adata.obs:
        rows_sp = []
        for sp in adata.obs["sample"].unique():
            m = adata.obs["sample"] == sp
            site = adata.obs.loc[m, "site"].mode().iloc[0] if m.any() else "NA"
            tnk_here = m.to_numpy() & (adata.obs["cell_type"].astype(str) == "T/NK").to_numpy()
            rows_sp.append({
                "sample": sp, "site": site, "n_cells": int(m.sum()),
                "pct_B": round(100 * float((adata.obs.loc[m, "cell_type"].astype(str) == "B").mean()), 3),
                "mean_tls_score": round(float(adata.obs.loc[m, "tls_score"].mean()), 4),
                "mean_CXCL13": round(float(adata.obs.loc[m, "CXCL13_expr"].mean()), 4),
                "pct_Tcm_of_TNK": (round(100 * float((adata.obs.loc[tnk_here, "tcm_score"] > 0).mean()), 3)
                                   if tnk_here.sum() else float("nan")),
            })
        pd.DataFrame(rows_sp).to_csv(os.path.join(R, "tls_by_sample.csv"), index=False)

    # --- figures ----------------------------------------------------------------
    sc.settings.figdir = R
    with progress("UMAP figures"):
        for color, fn, title in [
            ("cell_type", "umap_celltypes.png", "독립 재분석 — 세포유형 (marker 기반)"),
            ("leiden_gpu", "umap_clusters.png", "독립 재분석 — Leiden 클러스터"),
            ("malignant_call", "umap_malignant.png", "독립 악성/정상 간세포 판정"),
            ("site_label", "umap_site.png", "조직 부위 (정상 간→종양→전이)"),
        ]:
            if color not in adata.obs:
                continue
            fig, ax = plt.subplots(figsize=(8, 6))
            sc.pl.umap(adata, color=color, ax=ax, show=False, size=3, frameon=False,
                       legend_loc="right margin", title=title)
            fig.tight_layout()
            fig.savefig(os.path.join(R, fn), bbox_inches="tight", dpi=130)
            plt.close(fig)

        # TLS niche score UMAP — where the lymphoid-aggregate programs light up.
        if "tls_score" in adata.obs:
            fig, ax = plt.subplots(figsize=(8, 6))
            sc.pl.umap(adata, color="tls_score", ax=ax, show=False, size=3, frameon=False,
                       color_map="magma", title="TLS 니치 점수 (B/형질·CXCL13+ Tfh·TLS 케모카인)")
            fig.tight_layout()
            fig.savefig(os.path.join(R, "umap_tls.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

        if comp_site is not None:
            fig, ax = plt.subplots(figsize=(8, 5))
            comp_site.plot.bar(stacked=True, ax=ax, colormap="tab20", width=0.8)
            ax.set_ylabel("% of cells"); ax.set_title("조직 부위별 세포유형 조성 (독립 재분석)")
            ax.legend(fontsize=7, bbox_to_anchor=(1.01, 1), loc="upper left")
            ax.tick_params(axis="x", rotation=15)
            fig.tight_layout(); fig.savefig(os.path.join(R, "composition.png"), bbox_inches="tight", dpi=130)
            plt.close(fig)

        # TLS module by site — the paper's intratumoral-TLS claim.
        if tls_site is not None:
            fig, ax = plt.subplots(figsize=(7.5, 4.5))
            xs = list(tls_site.index)
            width = 0.4
            x = np.arange(len(xs))
            ax.bar(x - width / 2, tls_site["pct_B"].values, width, label="B세포 %", color="#2563eb")
            ax.bar(x + width / 2, tls_site["pct_Tfh_of_TNK"].values, width,
                   label="CXCL13+ Tfh % (T/NK 중)", color="#dc2626")
            ax.set_xticks(x); ax.set_xticklabels(xs)
            ax.set_ylabel("비율 (%)")
            ax.set_title("조직 부위별 TLS 세포 (B세포·CXCL13+ Tfh) — 종양 내 림프구조 형성 주장")
            ax.legend(fontsize=8)
            ax2 = ax.twinx()
            ax2.plot(x, tls_site["mean_CXCL13"].values, "o-", color="#0d9488", label="평균 CXCL13")
            ax2.set_ylabel("평균 CXCL13 발현", color="#0d9488")
            fig.tight_layout(); fig.savefig(os.path.join(R, "tls_by_site.png"), bbox_inches="tight", dpi=140)
            plt.close(fig)

    # --- summary / provenance ---------------------------------------------------
    n_mal = int((adata.obs["malignant_call"] == "malignant hepatocyte").sum())
    n_norm = int((adata.obs["malignant_call"] == "normal hepatocyte").sum())
    with open(os.path.join(R, "run_summary.txt"), "w") as fh:
        fh.write(f"cells={total}\ngenes={adata.n_vars}\ncelltypes={adata.obs['cell_type'].nunique()}\n")
        fh.write(f"clusters={n_clusters}\nsamples={adata.obs['sample'].nunique()}\n")
        fh.write(f"sites={adata.obs['site'].nunique()}\n")
        fh.write(f"malignant_hepatocyte_cells={n_mal}\nnormal_hepatocyte_cells={n_norm}\n")
        if tls_site is not None and "Tumor" in tls_site.index and "Normal" in tls_site.index:
            fh.write(f"B_pct_tumor={tls_site.loc['Tumor','pct_B']}\nB_pct_normal={tls_site.loc['Normal','pct_B']}\n")

    prov = {
        "mission": "BioIDE 헌장 제1조 — independent re-derivation; authors' celltype NOT used as input (site is experimental design, kept).",
        "method": "dense UMI matrix (genes×cells) → sparse cells×genes + QC + normalize + HVG + GPU PyTorch (ScaleData + PCA-SVD) + Harmony + Leiden/UMAP + marker annotation + GMM malignant/normal hepatocyte split + TLS module scoring + per-site progression & TLS composition",
        "gpu_accelerated": ["ScaleData(z-score)", "PCA(SVD)"],
        "gpu": torch.cuda.get_device_name(0), "cuda": torch.version.cuda,
        "batch_key": args.batch_key, "harmony": rep == "X_pca_harmony",
        "cell_type_markers": CELL_TYPE_MARKERS,
        "malignant_signature_used": sig_mal, "differentiation_signature_used": sig_dif,
        "proliferation_signature_used": sig_pro,
        "tls_signatures": {"niche": TLS_NICHE_SIG, "chemokine": TLS_CHEMOKINE_SIG,
                           "b": B_TLS_SIG, "tfh": TFH_SIG, "tcm": TCM_SIG},
        "params": vars(args),
        "cell_type_counts": {str(k): int(v) for k, v in counts_by.items()},
        "site_counts": {str(k): int(v) for k, v in adata.obs["site"].value_counts().items()},
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
          f"{adata.obs['cell_type'].nunique()} cell types; malignant-hepatocyte={n_mal} / normal-hepatocyte={n_norm}.",
          flush=True)
    print("    Next: 3. Validate vs the authors' labels + the TLS/progression claims (03_validate_vs_authors.py).", flush=True)


if __name__ == "__main__":
    main()
