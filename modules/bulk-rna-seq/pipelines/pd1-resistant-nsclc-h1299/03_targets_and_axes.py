#!/usr/bin/env python3
"""
03_targets_and_axes.py — check whether the report's prioritized targets and its
7 tumor-cell-intrinsic (Cat.A) functional axes re-emerge from OUR independent DE.
Produces target_reproduction.csv (our logFC/q vs report FC, per target),
targets_vs_report.png (concordance scatter + bar), and cat_a_heatmap.png
(z-scored log2CPM of Cat.A candidates across the 6 samples). Reads GHBIO_RESULTS.
"""
import os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

RESULTS = C.RESULTS
print(f"==> [03] results dir: {RESULTS}")

de = pd.read_csv(os.path.join(RESULTS, "de_p3c_vs_p0c.csv"), index_col=0)
logcpm = pd.read_csv(os.path.join(RESULTS, "logcpm_gene.csv"), index_col=0)

# --- target-by-target reproduction table ---
rows = []
for g, repfc in C.REPORT_TISSUE_FC.items():
    if g in de.index:
        r = de.loc[g]
        tier = "Tier1" if g in C.TIER1_TARGETS else ("Tier2" if g in C.TIER2_TARGETS else "")
        rows.append({
            "gene": g, "tier": tier, "report_logFC": repfc,
            "our_logFC": round(float(r["logFC"]), 3), "our_q": float(r["q"]),
            "sign_match": bool((r["logFC"] > 0) == (repfc > 0)),
            "our_sig": bool(r["q"] < 0.05),
        })
    else:
        rows.append({"gene": g, "tier": "", "report_logFC": repfc, "our_logFC": np.nan,
                     "our_q": np.nan, "sign_match": False, "our_sig": False})
tr = pd.DataFrame(rows).set_index("gene")
tr.to_csv(os.path.join(RESULTS, "target_reproduction.csv"))
present = tr.dropna(subset=["our_logFC"])
sign_rate = present["sign_match"].mean() * 100
r_pear = np.corrcoef(present["report_logFC"], present["our_logFC"])[0, 1]
print(f"==> targets present {len(present)}/{len(tr)}; sign-match {sign_rate:.0f}%; "
      f"Pearson r(our vs report FC)={r_pear:.3f}")

# --- concordance figure: scatter (all) + bar (Tier1/2) ---
fig, ax = plt.subplots(1, 2, figsize=(14, 6))
xy = present
tier1 = xy[xy["tier"] == "Tier1"]; tier2 = xy[xy["tier"] == "Tier2"]
other = xy[xy["tier"] == ""]
ax[0].scatter(other["report_logFC"], other["our_logFC"], s=22, c="#9fb3c8",
              alpha=.7, label="기타 타깃")
ax[0].scatter(tier2["report_logFC"], tier2["our_logFC"], s=70, c="#d68a2c",
              edgecolor="k", label="Tier2")
ax[0].scatter(tier1["report_logFC"], tier1["our_logFC"], s=100, c="#d64545",
              edgecolor="k", label="Tier1", zorder=5)
for g, r in pd.concat([tier1, tier2]).iterrows():
    ax[0].annotate(g, (r["report_logFC"], r["our_logFC"]), fontsize=8,
                   xytext=(4, 3), textcoords="offset points")
lim = [min(xy["report_logFC"].min(), xy["our_logFC"].min()) - .5,
       max(xy["report_logFC"].max(), xy["our_logFC"].max()) + .5]
ax[0].plot(lim, lim, "k--", lw=.8, alpha=.6)
ax[0].axhline(0, color="grey", lw=.5); ax[0].axvline(0, color="grey", lw=.5)
ax[0].set_xlabel("보고서 log2FC (조직 P3C/P0C)")
ax[0].set_ylabel("독립재현 log2FC")
ax[0].set_title(f"타깃 FC 대조  (부호 일치 {sign_rate:.0f}%, r={r_pear:.2f})")
ax[0].legend(fontsize=8)

bar = pd.concat([tier1, tier2]).sort_values("report_logFC", ascending=True)
yy = np.arange(len(bar)); h = 0.4
ax[1].barh(yy + h/2, bar["report_logFC"], height=h, color="#8aa0b8", label="보고서")
ax[1].barh(yy - h/2, bar["our_logFC"], height=h, color="#d64545", label="독립재현")
ax[1].set_yticks(yy); ax[1].set_yticklabels(bar.index, fontsize=9)
ax[1].axvline(0, color="k", lw=.6)
ax[1].set_xlabel("log2 fold change")
ax[1].set_title("Tier1·Tier2 타깃 — 보고서 vs 독립재현")
ax[1].legend(fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "targets_vs_report.png.tmp"), dpi=135, format="png")
os.replace(os.path.join(RESULTS, "targets_vs_report.png.tmp"),
           os.path.join(RESULTS, "targets_vs_report.png"))
plt.close(fig)

# --- Cat.A candidate heatmap (z-scored log2CPM across 6 samples) ---
ordered, axis_labels = [], []
for axis, gl in C.CAT_A_AXES.items():
    for g in gl:
        if g in logcpm.index:
            ordered.append(g); axis_labels.append(axis)
mat = logcpm.loc[ordered, C.SAMPLES].values
z = (mat - mat.mean(1, keepdims=True)) / (mat.std(1, keepdims=True) + 1e-9)
fig, ax = plt.subplots(figsize=(7.5, max(6, 0.26 * len(ordered))))
im = ax.imshow(z, aspect="auto", cmap="RdBu_r", vmin=-1.5, vmax=1.5)
ax.set_xticks(range(6)); ax.set_xticklabels(C.SAMPLES, rotation=45, ha="right", fontsize=9)
ax.set_yticks(range(len(ordered))); ax.set_yticklabels(ordered, fontsize=7)
# axis separators + labels
prev = None
for i, a in enumerate(axis_labels):
    if a != prev:
        if i > 0:
            ax.axhline(i - 0.5, color="k", lw=.8)
        ax.text(6.05, i, a, fontsize=7, va="top", ha="left", rotation=0, color="#333")
        prev = a
# mark P3 columns
ax.axvline(2.5, color="k", lw=1.5)
ax.text(0.5, -0.9, "P0 (민감)", ha="center", fontsize=9, fontweight="bold")
ax.text(4, -0.9, "P3 (내성)", ha="center", fontsize=9, fontweight="bold")
ax.set_title("종양세포-내재적(Cat.A 후보) 타깃 — log2CPM z-score", fontsize=10)
fig.colorbar(im, ax=ax, fraction=0.03, pad=0.12, label="z-score")
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "cat_a_heatmap.png.tmp"), dpi=135, format="png")
os.replace(os.path.join(RESULTS, "cat_a_heatmap.png.tmp"),
           os.path.join(RESULTS, "cat_a_heatmap.png"))
plt.close(fig)
print("==> [03] done: target_reproduction.csv, targets_vs_report.png, cat_a_heatmap.png")
