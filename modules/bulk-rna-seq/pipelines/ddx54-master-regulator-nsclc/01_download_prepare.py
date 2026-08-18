#!/usr/bin/env python3
"""
01_download_prepare.py — fetch the public GEO count matrix (GSE285342, LLC1
WT-Ddx54 vs Ddx54-KD), build a clean gene-level RAW count matrix + sample
metadata + QC (PCA / sample correlation), and confirm the knockdown worked
(Ddx54 itself must drop in the KD arm). We re-derive our OWN CPM/log2 from raw
counts rather than trusting any author-normalized column — that is the point of
an independent reproduction.

Reads GHBIO_RESULTS (per CLAUDE.md). Idempotent: caches the download + gene
counts under ~/ghbio-tutorial/data/ddx54-llc1 so re-runs are instant.

Outputs: counts_gene.csv, logcpm_gene.csv, samples.csv, qc_pca.png,
ddx54_knockdown.png, prepare_summary.txt
"""
import os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

RESULTS = C.RESULTS
print(f"==> [01] results dir: {RESULTS}")


def load_counts() -> pd.DataFrame:
    """Raw gene x sample counts from the GEO tsv.gz (cached to CSV)."""
    if os.path.exists(C.COUNTS_CACHE):
        print(f"==> using cached gene counts: {C.COUNTS_CACHE}")
        return pd.read_csv(C.COUNTS_CACHE, index_col=0)
    tsv = C.fetch_counts()
    print(f"==> reading {tsv}")
    df = pd.read_csv(tsv, sep="\t", index_col=0)
    # collapse any duplicate gene symbols by summing (keeps counts additive)
    df = df.groupby(level=0).sum()
    missing = [c for c in C.SAMPLES if c not in df.columns]
    if missing:
        raise RuntimeError(f"count matrix에 예상 컬럼이 없습니다: {missing}; 실제={list(df.columns)}")
    counts = df[C.SAMPLES].astype(float)
    counts.to_csv(C.COUNTS_CACHE)
    print(f"==> wrote {C.COUNTS_CACHE}  ({counts.shape[0]:,} genes x {counts.shape[1]} samples)")
    return counts


def main():
    counts = load_counts()
    counts.to_csv(os.path.join(RESULTS, "counts_gene.csv"))

    # filter low-count genes (>=10 total, detected in >=3 samples), then CPM + log2
    raw = counts.values
    keep = (raw.sum(1) >= 10) & ((raw >= 1).sum(1) >= 3)
    counts_f = counts.loc[keep]
    lib = counts_f.values.sum(0)
    cpm = counts_f.values / lib * 1e6
    logcpm = np.log2(cpm + 1)
    logcpm_df = pd.DataFrame(logcpm, index=counts_f.index, columns=C.SAMPLES)
    logcpm_df.to_csv(os.path.join(RESULTS, "logcpm_gene.csv"))
    print(f"==> {counts.shape[0]:,} genes -> {counts_f.shape[0]:,} after filter; "
          f"lib sizes: {[int(x) for x in lib]}")

    # sample metadata
    samp = pd.DataFrame({
        "sample": C.SAMPLES,
        "group": [C.SAMPLE_GROUP[s] for s in C.SAMPLES],
        "condition": ["WT-Ddx54 (control)" if C.SAMPLE_GROUP[s] == "WT" else "Ddx54 knockdown"
                      for s in C.SAMPLES],
        "lib_size": [int(x) for x in lib],
    })
    samp.to_csv(os.path.join(RESULTS, "samples.csv"), index=False)

    # ---- QC figure: PCA (top-variable genes) + sample correlation heatmap ----
    v = logcpm.var(1)
    top = np.argsort(v)[::-1][:2000]
    X = logcpm[top].T
    Xc = X - X.mean(0)
    U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
    pcs = U * S
    pcvar = (S ** 2) / (S ** 2).sum() * 100
    colors = {"WT": "#3b6fd6", "KD": "#d64545"}
    fig, ax = plt.subplots(1, 2, figsize=(12, 5))
    for i, s in enumerate(C.SAMPLES):
        g = C.SAMPLE_GROUP[s]
        ax[0].scatter(pcs[i, 0], pcs[i, 1], s=170, c=colors[g], edgecolor="k", zorder=3)
        ax[0].annotate(s, (pcs[i, 0], pcs[i, 1]), fontsize=8,
                       xytext=(6, 4), textcoords="offset points")
    ax[0].set_xlabel(f"PC1 ({pcvar[0]:.0f}%)"); ax[0].set_ylabel(f"PC2 ({pcvar[1]:.0f}%)")
    ax[0].set_title("PCA — WT-Ddx54 vs Ddx54-KD  [top 2000 HVG]")
    ax[0].axhline(0, color="grey", lw=.5); ax[0].axvline(0, color="grey", lw=.5)
    handles = [plt.Line2D([0], [0], marker="o", ls="", mec="k", mfc=c,
                          label=("WT-Ddx54 (대조)" if g == "WT" else "Ddx54-KD (녹다운)"))
               for g, c in colors.items()]
    ax[0].legend(handles=handles, fontsize=8, title="group")

    corr = np.corrcoef(logcpm.T)
    im = ax[1].imshow(corr, cmap="viridis", vmin=corr.min(), vmax=1)
    ax[1].set_xticks(range(len(C.SAMPLES))); ax[1].set_xticklabels(C.SAMPLES, rotation=45, ha="right", fontsize=7)
    ax[1].set_yticks(range(len(C.SAMPLES))); ax[1].set_yticklabels(C.SAMPLES, fontsize=7)
    ax[1].set_title("시료간 Pearson 상관 (log2CPM)")
    fig.colorbar(im, ax=ax[1], fraction=0.046)
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "qc_pca.png.tmp"), dpi=130, format="png")
    os.replace(os.path.join(RESULTS, "qc_pca.png.tmp"), os.path.join(RESULTS, "qc_pca.png"))
    plt.close(fig)

    # ---- knockdown confirmation: Ddx54 log2CPM per sample ----
    kd_ok = "n/a"
    if "Ddx54" in logcpm_df.index:
        d = logcpm_df.loc["Ddx54"]
        wt_m = d[C.WT_COLS].mean(); kd_m = d[C.KD_COLS].mean()
        drop = wt_m - kd_m
        kd_ok = f"{drop:+.2f} log2 (WT {wt_m:.2f} -> KD {kd_m:.2f})"
        fig, ax = plt.subplots(figsize=(7, 4.5))
        bar_c = [colors[C.SAMPLE_GROUP[s]] for s in C.SAMPLES]
        ax.bar(range(len(C.SAMPLES)), d[C.SAMPLES].values, color=bar_c, edgecolor="k", lw=.5)
        ax.axhline(wt_m, color="#3b6fd6", ls="--", lw=.9)
        ax.axhline(kd_m, color="#d64545", ls="--", lw=.9)
        ax.set_xticks(range(len(C.SAMPLES))); ax.set_xticklabels(C.SAMPLES, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("Ddx54  log2CPM")
        ax.set_title(f"녹다운 확인 — Ddx54 발현 (WT {wt_m:.1f} → KD {kd_m:.1f}, Δ={drop:.2f} log2)")
        fig.tight_layout()
        fig.savefig(os.path.join(RESULTS, "ddx54_knockdown.png.tmp"), dpi=135, format="png")
        os.replace(os.path.join(RESULTS, "ddx54_knockdown.png.tmp"),
                   os.path.join(RESULTS, "ddx54_knockdown.png"))
        plt.close(fig)

    with open(os.path.join(RESULTS, "prepare_summary.txt"), "w") as f:
        f.write("DDX54 (LLC1 Ddx54-KD) — count matrix 준비 요약\n")
        f.write(f"  source: GSE285342_LLC1_cnt_DDX54.tsv.gz (GEO 공개)\n")
        f.write(f"  genes: {counts.shape[0]:,}; filtered {counts_f.shape[0]:,}\n")
        f.write(f"  design: WT n={len(C.WT_COLS)} vs KD n={len(C.KD_COLS)}\n")
        f.write(f"  lib sizes: {dict(zip(C.SAMPLES, [int(x) for x in lib]))}\n")
        f.write(f"  PC1 variance: {pcvar[0]:.1f}%\n")
        f.write(f"  Ddx54 녹다운: {kd_ok}\n")
    print(f"==> Ddx54 knockdown: {kd_ok}")
    print("==> [01] done: counts_gene.csv, logcpm_gene.csv, samples.csv, qc_pca.png, ddx54_knockdown.png")


if __name__ == "__main__":
    main()
