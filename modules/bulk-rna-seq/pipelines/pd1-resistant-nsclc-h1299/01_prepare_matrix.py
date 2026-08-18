#!/usr/bin/env python3
"""
01_prepare_matrix.py — locate the vendor isoform xlsx from the LLMwiki, collapse
180k isoforms to gene-level RAW counts, and emit a clean count matrix + sample
metadata + QC (PCA / sample correlation). We deliberately re-derive our OWN
normalization from raw counts rather than trusting the vendor's TMM/CPM columns —
that is the point of an independent reproduction.

Reads GHBIO_RESULTS (per CLAUDE.md). Idempotent: caches the parsed gene counts
under ~/ghbio-tutorial/data/pd1-h1299 and the xlsx itself so re-runs are instant.
"""
import os, sys, shutil
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

RESULTS = C.RESULTS
print(f"==> [01] results dir: {RESULTS}")


def parse_isoforms_to_gene(xlsx: str) -> pd.DataFrame:
    """Sum RAW-count columns (32..37) per gene symbol (col 1) across all isoforms."""
    import openpyxl
    from collections import defaultdict
    print(f"==> parsing {xlsx} (180k isoforms — 약 1~2분)...")
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    ws = wb["Data"]
    # header rows 1-2; data starts at row 3. Raw-count cols are 0-based 32..37.
    graw = defaultdict(lambda: np.zeros(6))
    n = 0
    for r in ws.iter_rows(min_row=3, values_only=True):
        g = r[1]
        if not g:
            continue
        for j in range(6):
            v = r[32 + j]
            if isinstance(v, (int, float)):
                graw[g][j] += v
        n += 1
    print(f"    parsed {n:,} isoform rows -> {len(graw):,} genes")
    genes = sorted(graw)
    M = np.vstack([graw[g] for g in genes]).astype(float)
    return pd.DataFrame(M, index=genes, columns=C.SAMPLES)


def main():
    # 1) locate + cache the xlsx
    xlsx = C.find_xlsx()
    print(f"==> found vendor xlsx: {xlsx}")
    if os.path.abspath(xlsx) != os.path.abspath(C.XLSX_CACHE):
        try:
            shutil.copy2(xlsx, C.XLSX_CACHE)
            print(f"==> cached xlsx -> {C.XLSX_CACHE}")
        except Exception as e:
            print(f"    (cache copy skipped: {e})")

    # 2) gene-level raw counts (cached)
    if os.path.exists(C.COUNTS_CACHE):
        print(f"==> using cached gene counts: {C.COUNTS_CACHE}")
        counts = pd.read_csv(C.COUNTS_CACHE, index_col=0)
    else:
        counts = parse_isoforms_to_gene(xlsx)
        counts.to_csv(C.COUNTS_CACHE)
        print(f"==> wrote {C.COUNTS_CACHE}")
    counts.to_csv(os.path.join(RESULTS, "counts_gene.csv"))

    # 3) filter low-count genes, CPM + log2
    raw = counts.values
    keep = (raw.sum(1) >= 10) & ((raw >= 1).sum(1) >= 2)
    counts_f = counts.loc[keep]
    lib = counts_f.values.sum(0)
    cpm = counts_f.values / lib * 1e6
    logcpm = np.log2(cpm + 1)
    logcpm_df = pd.DataFrame(logcpm, index=counts_f.index, columns=C.SAMPLES)
    logcpm_df.to_csv(os.path.join(RESULTS, "logcpm_gene.csv"))
    print(f"==> {counts.shape[0]:,} genes -> {counts_f.shape[0]:,} after filter; "
          f"lib sizes: {[int(x) for x in lib]}")

    # 4) sample metadata
    samp = pd.DataFrame({
        "sample": C.SAMPLES,
        "group": [C.SAMPLE_GROUP[s] for s in C.SAMPLES],
        "line": ["P0" if s.startswith("P0") else "P3" for s in C.SAMPLES],
        "treatment": ["anti-PD-1" if s.endswith("TD") else "vehicle" for s in C.SAMPLES],
        "lib_size": [int(x) for x in lib],
    })
    samp.to_csv(os.path.join(RESULTS, "samples.csv"), index=False)

    # 5) QC figure: PCA (top-variable genes) + sample correlation heatmap
    v = logcpm.var(1)
    top = np.argsort(v)[::-1][:2000]
    X = logcpm[top].T                      # samples x genes
    Xc = X - X.mean(0)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    pcs = U * S
    pcvar = (S ** 2) / (S ** 2).sum() * 100

    colors = {"P0C": "#3b6fd6", "P0D": "#9bbcf2", "P3C": "#d64545", "P3D": "#f2a19b"}
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    for i, s in enumerate(C.SAMPLES):
        g = C.SAMPLE_GROUP[s]
        ax[0].scatter(pcs[i, 0], pcs[i, 1], s=180, c=colors[g], edgecolor="k", zorder=3)
        ax[0].annotate(s, (pcs[i, 0], pcs[i, 1]), fontsize=9,
                       xytext=(6, 4), textcoords="offset points")
    ax[0].set_xlabel(f"PC1 ({pcvar[0]:.0f}%)"); ax[0].set_ylabel(f"PC2 ({pcvar[1]:.0f}%)")
    ax[0].set_title("PCA — P0(민감) vs P3(내성)  [top 2000 HVG]")
    ax[0].axhline(0, color="grey", lw=.5); ax[0].axvline(0, color="grey", lw=.5)
    handles = [plt.Line2D([0], [0], marker="o", ls="", mec="k", mfc=c, label=g)
               for g, c in colors.items()]
    ax[0].legend(handles=handles, fontsize=8, title="group")

    corr = np.corrcoef(logcpm.T)
    im = ax[1].imshow(corr, cmap="viridis", vmin=corr.min(), vmax=1)
    ax[1].set_xticks(range(6)); ax[1].set_xticklabels(C.SAMPLES, rotation=45, ha="right", fontsize=8)
    ax[1].set_yticks(range(6)); ax[1].set_yticklabels(C.SAMPLES, fontsize=8)
    ax[1].set_title("시료간 Pearson 상관 (log2CPM)")
    for i in range(6):
        for j in range(6):
            ax[1].text(j, i, f"{corr[i, j]:.2f}", ha="center", va="center",
                       color="w" if corr[i, j] < (corr.min()+1)/2 else "k", fontsize=7)
    fig.colorbar(im, ax=ax[1], fraction=0.046)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "qc_pca.png.tmp"), dpi=130, format="png")
    os.replace(os.path.join(RESULTS, "qc_pca.png.tmp"), os.path.join(RESULTS, "qc_pca.png"))
    plt.close(fig)

    # PC1 separation of P0 vs P3 — the "resistance acquisition dominates" check
    p0 = pcs[[0, 1, 2], 0].mean(); p3 = pcs[[3, 4, 5], 0].mean()
    with open(os.path.join(RESULTS, "prepare_summary.txt"), "w") as f:
        f.write("H1299-P3 PD-1 내성 — count matrix 준비 요약\n")
        f.write(f"  isoform->gene: {counts.shape[0]:,} genes; filtered {counts_f.shape[0]:,}\n")
        f.write(f"  lib sizes: {dict(zip(C.SAMPLES, [int(x) for x in lib]))}\n")
        f.write(f"  PC1 variance: {pcvar[0]:.1f}%  (P0 mean={p0:.1f}, P3 mean={p3:.1f})\n")
        f.write(f"  P0/P3 PC1 분리: {'예 (내성 획득이 주 변이축)' if abs(p3-p0) > abs(pcs[:,1]).mean() else '약함'}\n")
    print("==> [01] done: counts_gene.csv, logcpm_gene.csv, samples.csv, qc_pca.png")


if __name__ == "__main__":
    main()
