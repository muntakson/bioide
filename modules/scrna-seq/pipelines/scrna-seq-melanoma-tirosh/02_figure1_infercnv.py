#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
02_figure1_infercnv.py  —  Tirosh et al., Science 2016 (GSE72056), Figure 1
===========================================================================
Reproduce Figure 1 of the metastatic-melanoma single-cell paper from the
authors' published log2(TPM/10+1) matrix:

  Fig 1B  inferred large-scale CNV heatmap that separates malignant cells
          from normal immune/stromal cells (paper's method: order genes by
          chromosomal position, moving average over 100-gene windows,
          relative to the average of reference normal cells).
  Fig 1C  tSNE of MALIGNANT cells, colored by tumor of origin.
  Fig 1D  tSNE of NON-MALIGNANT cells, colored by cell type.

The GSE72056 matrix header carries the authors' own labels:
  row "Cell"                                 -> cell names
  row "tumor" (if present)                   -> tumor of origin
  row "malignant(1=no,2=yes,0=unresolved)"   -> 0/1/2
  row "non-malignant cell type (1=T,2=B,3=Macro.,4=Endo.,5=CAF,6=NK)" -> 0..6

Also writes, for the downstream steps + AI hand-off:
  melanoma_processed.h5ad   AnnData (X = log2(TPM/10+1), obs labels)
  markers_by_cluster.csv    top markers per authors' cell-type group
  celltype_draft.csv        cell-type composition (authors' labels)
  run_summary.txt           cover metadata for the report

Run inside the shared venv:  ~/ghbio-venv/bin/python 02_figure1_infercnv.py
"""

import os
import re
import sys

import numpy as np
import pandas as pd
import scanpy as sc
import anndata as ad
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# Optional GPU acceleration for the inferCNV moving-average. The result is
# numerically identical to the NumPy path (uniform kernel + zero padding), so the
# tutorial stays correct — and reproducible — on machines without a GPU.
try:
    import torch

    _GPU = bool(torch.cuda.is_available())
except Exception:  # torch not installed or no CUDA runtime
    torch = None
    _GPU = False

HOME = os.path.expanduser("~")
RESULTS_DIR = os.environ.get("GHBIO_RESULTS", os.path.join(HOME, "ghbio-tutorial", "results"))
DATA = os.path.join(HOME, "ghbio-tutorial", "data", "melanoma-gse72056",
                    "GSE72056_melanoma_single_cell_revised_v2.txt.gz")
REF_DIR = os.path.join(HOME, "ghbio-tutorial", "ref")
GTF = os.path.join(REF_DIR, "refdata-gex-GRCh38-2020-A", "genes", "genes.gtf")
GENEPOS_CACHE = os.path.join(REF_DIR, "gene_positions_grch38.tsv")

CELLTYPE_NAMES = {1: "T cell", 2: "B cell", 3: "Macrophage",
                  4: "Endothelial", 5: "CAF", 6: "NK"}

# Blue-white-red diverging map for CNV log-ratio, matching the paper's palette.
CNV_CMAP = LinearSegmentedColormap.from_list(
    "cnv", ["#2166ac", "#4393c3", "#f7f7f7", "#d6604d", "#b2182b"])


# -----------------------------------------------------------------------------
# 1. Load the authors' matrix + labels
# -----------------------------------------------------------------------------
def load_matrix():
    if not os.path.exists(DATA):
        sys.exit(f"ERROR: matrix not found: {DATA}\nRun step 1 (01_download_melanoma.sh) first.")
    print(f"==> Loading matrix: {DATA}")
    raw = pd.read_csv(DATA, sep="\t", header=None, dtype=str,
                      compression="gzip", low_memory=False)
    labels = raw.iloc[:, 0].astype(str).str.strip()

    def find_row(prefix):
        hit = labels.str.lower().str.startswith(prefix.lower())
        idx = np.where(hit.values)[0]
        return int(idx[0]) if len(idx) else None

    i_cell = find_row("Cell")
    i_mal = find_row("malignant")
    i_type = find_row("non-malignant cell type")
    i_tumor = find_row("tumor")
    if i_cell is None or i_mal is None or i_type is None:
        sys.exit("ERROR: could not find the expected header rows (Cell / malignant / cell type).")

    meta_rows = {i_cell, i_mal, i_type} | ({i_tumor} if i_tumor is not None else set())
    values = raw.iloc[:, 1:]  # everything except the row-label column

    cell_names = values.iloc[i_cell].astype(str).values
    malignant = pd.to_numeric(values.iloc[i_mal], errors="coerce").fillna(0).astype(int).values
    ctype = pd.to_numeric(values.iloc[i_type], errors="coerce").fillna(0).astype(int).values
    if i_tumor is not None:
        tumor = values.iloc[i_tumor].astype(str).values
    else:
        # Tumor of origin encoded in the cell name prefix, e.g. "Cy79_..." / "cy88...".
        tumor = np.array([re.match(r"^([A-Za-z]*\d+)", str(c)).group(1)
                          if re.match(r"^([A-Za-z]*\d+)", str(c)) else "NA"
                          for c in cell_names])
    tumor = np.array([f"Mel{re.sub(r'[^0-9]', '', str(t))}" if re.sub(r'[^0-9]', '', str(t)) else str(t)
                      for t in tumor])

    gene_rows = [i for i in range(raw.shape[0]) if i not in meta_rows]
    genes = labels.iloc[gene_rows].values
    expr = values.iloc[gene_rows].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    # AnnData is cell x gene; the matrix is gene x cell, so transpose.
    X = expr.values.astype(np.float32).T

    mal_label = np.where(malignant == 2, "malignant",
                np.where(malignant == 1, "normal", "unresolved"))
    ct_label = np.array([CELLTYPE_NAMES.get(c, "") for c in ctype])
    # One grouping used for marker detection: malignant cells + each normal cell type.
    group = np.where(mal_label == "malignant", "Malignant",
            np.where(np.isin(ct_label, list(CELLTYPE_NAMES.values())), ct_label, "Unresolved"))

    adata = ad.AnnData(X=X, obs=pd.DataFrame({
        "tumor": pd.Categorical(tumor),
        "malignant": pd.Categorical(mal_label, categories=["normal", "malignant", "unresolved"]),
        "celltype": pd.Categorical(np.where(ct_label == "", "—", ct_label)),
        "group": pd.Categorical(group),
    }, index=[str(c) for c in cell_names]),
        var=pd.DataFrame(index=[str(g) for g in genes]))
    adata.var_names_make_unique()
    print(f"==> Loaded {adata.n_obs} cells x {adata.n_vars} genes.")
    print("    malignant flag:", dict(pd.Series(mal_label).value_counts()))
    print("    cell types    :", dict(pd.Series(np.where(ct_label == '', 'malignant/—', ct_label)).value_counts()))
    return adata


# -----------------------------------------------------------------------------
# 2. Gene -> (chrom, start) positions from the installed GRCh38 GTF (cached)
# -----------------------------------------------------------------------------
def gene_positions():
    if os.path.exists(GENEPOS_CACHE):
        print(f"==> Using cached gene positions: {GENEPOS_CACHE}")
        return pd.read_csv(GENEPOS_CACHE, sep="\t")
    if not os.path.exists(GTF):
        sys.exit(f"ERROR: GTF not found: {GTF}\n"
                 "The GRCh38 reference (used by the other tutorials) is required for inferCNV.")
    print(f"==> Building gene-position cache from GTF (first run only): {GTF}")
    name_re = re.compile(r'gene_name "([^"]+)"')
    rows = []
    seen = set()
    with open(GTF) as fh:
        for line in fh:
            if "\tgene\t" not in line:
                continue
            f = line.split("\t")
            if len(f) < 9 or f[2] != "gene":
                continue
            m = name_re.search(f[8])
            if not m:
                continue
            g = m.group(1)
            if g in seen:
                continue
            seen.add(g)
            rows.append((g, f[0], int(f[3])))
    df = pd.DataFrame(rows, columns=["gene", "chrom", "start"])
    os.makedirs(REF_DIR, exist_ok=True)
    df.to_csv(GENEPOS_CACHE, sep="\t", index=False)
    print(f"==> Cached {len(df)} gene positions -> {GENEPOS_CACHE}")
    return df


def chrom_order(chrom):
    c = str(chrom).replace("chr", "")
    if c == "X":
        return 23
    if c == "Y":
        return 24
    try:
        return int(c)
    except ValueError:
        return 99  # scaffolds / MT -> dropped


# -----------------------------------------------------------------------------
# 3. inferCNV (paper's method) + Figure 1B heatmap
# -----------------------------------------------------------------------------
def _uniform_smooth_gpu(block, k, device):
    """np.convolve(row, ones(k)/k, mode='same') for every row of `block`, on GPU.

    A uniform kernel is symmetric, so cross-correlation (conv1d) equals convolution.
    A full zero-padded convolution then the centered 'same' slice reproduces NumPy's
    edge attenuation exactly.
    """
    kernel = torch.full((1, 1, k), 1.0 / k, dtype=block.dtype, device=device)
    full = torch.nn.functional.conv1d(block.unsqueeze(1), kernel, padding=k - 1)
    start = (k - 1) // 2
    return full[:, 0, start:start + block.shape[1]]


def _verify_gpu_conv(device):
    """One-time guard: confirm the GPU convolution matches NumPy before trusting it."""
    rng = np.random.RandomState(0)
    r = rng.randn(3, 37).astype(np.float32)
    k = 10
    ref = np.stack([np.convolve(row, np.ones(k) / k, mode="same") for row in r])
    got = _uniform_smooth_gpu(torch.from_numpy(r).to(device), k, device).cpu().numpy()
    return np.allclose(ref, got, atol=1e-5)


def _moving_average_by_chrom(E, ords, win):
    """Per-chromosome centered moving average (paper's inferCNV smoothing).

    Batched GPU conv1d per chromosome when CUDA is available, else a vectorized
    NumPy fallback. Both match the original per-cell np.convolve loop bit-for-bit.
    """
    use_gpu = _GPU
    if use_gpu:
        device = torch.device("cuda")
        if not _verify_gpu_conv(device):
            print("==> GPU convolution self-check failed; falling back to CPU.")
            use_gpu = False
    if use_gpu:
        print(f"==> inferCNV smoothing on GPU: {torch.cuda.get_device_name(0)}")
        Et = torch.from_numpy(np.ascontiguousarray(E, dtype=np.float32)).to(device)
        out = torch.empty_like(Et)
        for ch in np.unique(ords):
            col_t = torch.as_tensor(np.where(ords == ch)[0], device=device, dtype=torch.long)
            k = min(win, int(col_t.numel()))
            block = Et.index_select(1, col_t)
            out[:, col_t] = block if k < 5 else _uniform_smooth_gpu(block, k, device)
        return out.cpu().numpy()

    print("==> inferCNV smoothing on CPU (no GPU detected).")
    out = np.zeros_like(E, dtype=np.float32)
    for ch in np.unique(ords):
        cols = np.where(ords == ch)[0]
        block = E[:, cols]
        k = min(win, block.shape[1])
        if k < 5:
            out[:, cols] = block
            continue
        kernel = np.ones(k) / k
        out[:, cols] = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="same"), 1, block)
    return out


def infer_cnv(adata):
    print("==> Computing inferred CNV profiles (moving average over chromosomes)…")
    pos = gene_positions()
    pos["ord"] = pos["chrom"].map(chrom_order)
    pos = pos[pos["ord"] < 99].copy()

    # Genes shared between matrix and GTF, expressed on average (reduce noise).
    expr_mean = np.asarray(adata.X.mean(axis=0)).ravel()
    keep_expr = set(np.array(adata.var_names)[expr_mean > 0.1])
    pos = pos[pos["gene"].isin(keep_expr) & pos["gene"].isin(set(adata.var_names))]
    pos = pos.sort_values(["ord", "start"]).drop_duplicates("gene")
    genes = pos["gene"].tolist()
    if len(genes) < 500:
        sys.exit("ERROR: too few positioned genes for inferCNV — check the GTF/matrix gene symbols.")
    print(f"==> {len(genes)} positioned, expressed genes ordered along the genome.")

    E = adata[:, genes].X
    E = np.asarray(E.todense()) if hasattr(E, "todense") else np.asarray(E)
    # Relative expression: center each gene across cells, clip to [-3, 3] (paper).
    E = E - E.mean(axis=0, keepdims=True)
    np.clip(E, -3.0, 3.0, out=E)

    ords = pos["ord"].values
    win = 100  # window of 100 genes, not crossing chromosome boundaries (paper)
    cnv = _moving_average_by_chrom(E, ords, win)

    # Express CNV relative to the average of reference NORMAL cells (immune/stromal),
    # so malignant aneuploidy stands out. (Paper baselines against normal cells.)
    ref = (adata.obs["malignant"].values == "normal")
    if ref.sum() >= 20:
        cnv = cnv - cnv[ref].mean(axis=0, keepdims=True)

    adata.obs["cnv_signal"] = (cnv ** 2).mean(axis=1)  # aneuploidy magnitude per cell
    _plot_fig1B(adata, cnv, ords)
    return adata


def _plot_fig1B(adata, cnv, ords):
    # Order cells: non-malignant on top, malignant below; within each, by tumor.
    mal = adata.obs["malignant"].values
    order = np.lexsort((adata.obs["tumor"].astype(str).values,
                        (mal == "malignant").astype(int)))
    M = cnv[order]
    is_mal = (mal[order] == "malignant")

    fig, ax = plt.subplots(figsize=(13, 8))
    im = ax.imshow(M, aspect="auto", cmap=CNV_CMAP, vmin=-0.6, vmax=0.6, interpolation="nearest")
    # Chromosome boundaries + centered labels.
    bounds, labels_pos, prev, startc = [], [], None, 0
    uord = ords
    for i, ch in enumerate(uord):
        if ch != prev:
            if prev is not None:
                bounds.append(i)
                labels_pos.append(((startc + i) / 2, prev))
                startc = i
            prev = ch
    labels_pos.append(((startc + len(uord)) / 2, prev))
    for b in bounds:
        ax.axvline(b, color="#333", lw=0.4)
    lab = {23: "X", 24: "Y"}
    ax.set_xticks([p for p, _ in labels_pos])
    ax.set_xticklabels([lab.get(int(c), str(int(c))) for _, c in labels_pos], fontsize=7)
    # Malignant / non-malignant divider.
    split = np.searchsorted(is_mal, True)
    ax.axhline(split, color="black", lw=1.2)
    ax.text(-0.01, split / 2, "Non-malignant", rotation=90, va="center", ha="right",
            transform=ax.get_yaxis_transform(), fontsize=9, color="#555")
    ax.text(-0.01, (split + len(is_mal)) / 2, "Malignant", rotation=90, va="center", ha="right",
            transform=ax.get_yaxis_transform(), fontsize=9, color="#b2182b")
    ax.set_yticks([])
    ax.set_xlabel("Chromosomal position (genes ordered along the genome)")
    ax.set_title("Figure 1B — Inferred large-scale CNVs separate malignant from normal cells\n"
                 "Tirosh et al., Science 2016 (GSE72056), reproduced")
    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
    cbar.set_label("Inferred CNV (log-ratio)")
    fig.tight_layout()
    out = os.path.join(RESULTS_DIR, "fig1B_infercnv_heatmap.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"==> Saved {out}")


# -----------------------------------------------------------------------------
# 4. tSNE of malignant (Fig 1C) and non-malignant (Fig 1D) cells
# -----------------------------------------------------------------------------
def _tsne_embed(sub):
    sub = sub.copy()
    sc.pp.scale(sub, max_value=10)
    sc.tl.pca(sub, n_comps=min(30, sub.n_obs - 1, sub.n_vars - 1), svd_solver="arpack")
    sc.tl.tsne(sub, n_pcs=min(30, sub.obsm["X_pca"].shape[1]), random_state=0)
    return sub


def _scatter(sub, color_key, title, out, legend_title):
    xy = sub.obsm["X_tsne"]
    cats = sub.obs[color_key].astype(str).values
    uniq = sorted(pd.unique(cats))
    cmap = plt.get_cmap("tab20" if len(uniq) > 10 else "tab10")
    fig, ax = plt.subplots(figsize=(7.2, 6))
    for i, c in enumerate(uniq):
        m = cats == c
        ax.scatter(xy[m, 0], xy[m, 1], s=10, color=cmap(i % cmap.N), label=c, linewidths=0)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel("tSNE1"); ax.set_ylabel("tSNE2")
    ax.set_title(title)
    ax.legend(title=legend_title, fontsize=7, title_fontsize=8, markerscale=1.4,
              loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"==> Saved {out}")


def tsne_figures(adata):
    print("==> Figure 1C/1D: tSNE of malignant / non-malignant cells…")
    mal = adata[adata.obs["malignant"] == "malignant"]
    if mal.n_obs > 20:
        _scatter(_tsne_embed(mal), "tumor",
                 "Figure 1C — Malignant cells (tSNE), colored by tumor",
                 os.path.join(RESULTS_DIR, "fig1C_tsne_malignant.png"), "Tumor")
    non = adata[adata.obs["celltype"] != "—"]
    if non.n_obs > 20:
        _scatter(_tsne_embed(non), "celltype",
                 "Figure 1D — Non-malignant cells (tSNE), colored by cell type",
                 os.path.join(RESULTS_DIR, "fig1D_tsne_nonmalignant.png"), "Cell type")


# -----------------------------------------------------------------------------
# 5. Markers + composition tables (AI hand-off)
# -----------------------------------------------------------------------------
def markers_and_tables(adata):
    print("==> rank_genes_groups over authors' cell-type groups…")
    a = adata.copy()
    # Keep groups with enough cells for a stable Wilcoxon test.
    vc = a.obs["group"].value_counts()
    keep = vc[vc >= 10].index.tolist()
    a = a[a.obs["group"].isin(keep)].copy()
    a.obs["group"] = a.obs["group"].astype(str).astype("category")
    sc.tl.rank_genes_groups(a, groupby="group", method="wilcoxon")
    res = a.uns["rank_genes_groups"]
    groups = res["names"].dtype.names
    rows, top5 = [], {}
    for g in groups:
        names = res["names"][g][:25]
        lfc = res["logfoldchanges"][g][:25]
        padj = res["pvals_adj"][g][:25]
        top5[g] = list(names[:5])
        for rank, (nm, l, p) in enumerate(zip(names, lfc, padj), start=1):
            rows.append({"cluster": g, "rank": rank, "gene": nm,
                         "log2FC": float(l), "pval_adj": float(p)})
    pd.DataFrame(rows).to_csv(os.path.join(RESULTS_DIR, "markers_by_cluster.csv"), index=False)
    print(f"==> Saved markers_by_cluster.csv ({len(groups)} groups)")

    # Composition table (authors' labels) -> celltype_draft.csv
    n = adata.n_obs
    comp = []
    for g, cnt in adata.obs["group"].value_counts().items():
        comp.append({"cluster": g, "n_cells": int(cnt), "pct_of_cells": round(100 * cnt / n, 1),
                     "top5_markers": ";".join(top5.get(g, []))})
    pd.DataFrame(comp).sort_values("n_cells", ascending=False).to_csv(
        os.path.join(RESULTS_DIR, "celltype_draft.csv"), index=False)
    print("==> Saved celltype_draft.csv")


def write_summary(adata):
    n = adata.n_obs
    n_mal = int((adata.obs["malignant"] == "malignant").sum())
    n_norm = int((adata.obs["malignant"] == "normal").sum())
    n_tum = adata.obs["tumor"].nunique()
    with open(os.path.join(RESULTS_DIR, "run_summary.txt"), "w") as fh:
        fh.write(f"dataset=Tirosh et al. 2016 (GSE72056) metastatic melanoma\n")
        fh.write(f"cells={n}\ntumors={n_tum}\nmalignant_cells={n_mal}\nnormal_cells={n_norm}\n")
    print(f"==> {n} cells | {n_tum} tumors | {n_mal} malignant | {n_norm} normal")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    sc.settings.verbosity = 1
    adata = load_matrix()
    adata = infer_cnv(adata)
    tsne_figures(adata)
    markers_and_tables(adata)
    write_summary(adata)
    adata.write(os.path.join(RESULTS_DIR, "melanoma_processed.h5ad"))
    print(f"==> Saved melanoma_processed.h5ad")
    print("==> [02] Figure 1 complete. Next: 03_figures2_3_malignant_states.py")


if __name__ == "__main__":
    main()
