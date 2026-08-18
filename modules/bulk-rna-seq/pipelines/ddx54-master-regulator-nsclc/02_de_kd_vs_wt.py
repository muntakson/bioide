#!/usr/bin/env python3
"""
02_de_kd_vs_wt.py — INDEPENDENT differential expression for the effect of
removing Ddx54 (KD vs WT), using our own limma-style empirical-Bayes moderated
t-test (self-contained, no author padj consumed). n=4 WT / n=3 KD are real
replicates, so this is honest DE strengthened by cross-gene variance shrinkage.

Also draws the immune-evasion / oncogenic gene panel that the paper's Fig 6
highlights (Cd47, Cd38, Myc ...), coloured by our own KD-vs-WT direction.

Outputs: de_kd_vs_wt.csv, volcano_kd_vs_wt.png, immune_evasion_genes.png.
Reads GHBIO_RESULTS.
"""
import os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C

RESULTS = C.RESULTS
print(f"==> [02] results dir: {RESULTS}")

logcpm = pd.read_csv(os.path.join(RESULTS, "logcpm_gene.csv"), index_col=0)
genes = logcpm.index.to_numpy()
L = logcpm.values

# --- KD vs WT moderated t-test (effect of Ddx54 loss) ---
lfc, t, p, s2, df = C.moderated_ttest(L, C.GROUPS["WT"], C.GROUPS["KD"])
q = C.bh_fdr(p)
de = pd.DataFrame({
    "gene": genes, "logFC": lfc, "t": t, "p": p, "q": q,
    "WT_mean": L[:, C.GROUPS["WT"]].mean(1),
    "KD_mean": L[:, C.GROUPS["KD"]].mean(1),
}).set_index("gene")
de = de.sort_values("t", key=lambda s: s.abs(), ascending=False)
de.to_csv(os.path.join(RESULTS, "de_kd_vs_wt.csv"))

up = ((de.q < 0.05) & (de.logFC > 1)).sum()
dn = ((de.q < 0.05) & (de.logFC < -1)).sum()
ddx = de.loc["Ddx54"] if "Ddx54" in de.index else None
print(f"==> KD vs WT: {up} up, {dn} down (q<0.05,|logFC|>1)"
      + (f"; Ddx54 logFC={ddx['logFC']:.2f} q={ddx['q']:.3f}" if ddx is not None else ""))

# --- Volcano (KD vs WT), report/focus genes labelled ---
fig, ax = plt.subplots(figsize=(8.5, 7))
x = de["logFC"].values; y = -np.log10(np.clip(de["p"].values, 1e-300, None))
sig = (de["q"].values < 0.05) & (np.abs(x) > 1)
ax.scatter(x[~sig], y[~sig], s=6, c="#cfcfcf", alpha=.5, rasterized=True)
ax.scatter(x[sig & (x > 0)], y[sig & (x > 0)], s=9, c="#d64545", alpha=.7, rasterized=True)
ax.scatter(x[sig & (x < 0)], y[sig & (x < 0)], s=9, c="#3b6fd6", alpha=.7, rasterized=True)
for g in dict.fromkeys(C.FOCUS_GENES):
    if g in de.index:
        r = de.loc[g]
        ax.annotate(g, (r["logFC"], -np.log10(max(r["p"], 1e-300))),
                    fontsize=8, fontweight="bold", xytext=(4, 3), textcoords="offset points")
        ax.scatter([r["logFC"]], [-np.log10(max(r["p"], 1e-300))], s=26,
                   facecolor="none", edgecolor="k", lw=.8, zorder=5)
ax.axvline(1, color="grey", ls="--", lw=.7); ax.axvline(-1, color="grey", ls="--", lw=.7)
ax.axvline(0, color="grey", lw=.5)
ax.axhline(-np.log10(0.05), color="grey", ls=":", lw=.7)
ax.set_xlabel("log2 fold change  (Ddx54-KD / WT)")
ax.set_ylabel("-log10 p  (moderated t)")
ax.set_title("독립재현 — Ddx54 녹다운 차등발현 (KD vs WT, LLC1)")
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "volcano_kd_vs_wt.png.tmp"), dpi=140, format="png")
os.replace(os.path.join(RESULTS, "volcano_kd_vs_wt.png.tmp"),
           os.path.join(RESULTS, "volcano_kd_vs_wt.png"))
plt.close(fig)

# --- Immune-evasion / oncogenic gene panel (paper Fig 6 focus) ---
panel = ["Ddx54", "Cd47", "Cd38", "Myc", "Jak1", "Jak2", "Stat3",
         "Ctnnb1", "Ccnd1", "Cd274", "Nt5e"]
rows = [(g, float(de.loc[g, "logFC"]), float(de.loc[g, "q"])) for g in panel if g in de.index]
rows.sort(key=lambda r: r[1])
gnames = [r[0] for r in rows]; vals = [r[1] for r in rows]; qs = [r[2] for r in rows]
prot = set(C.PROTEIN_LEVEL_ONLY)
fig, ax = plt.subplots(figsize=(8, max(4, 0.5 * len(rows))))
yy = np.arange(len(rows))
bar_c = ["#3b6fd6" if v < 0 else "#d64545" for v in vals]
ax.barh(yy, vals, color=bar_c, edgecolor="k", lw=.4)
for i, (g, v, qv) in enumerate(zip(gnames, vals, qs)):
    star = "*" if qv < 0.05 else ""
    tag = "  (단백질 지표)" if g in prot else ""
    ax.text(v + (0.02 if v >= 0 else -0.02), i, f"{v:+.2f}{star}{tag}",
            va="center", ha="left" if v >= 0 else "right", fontsize=8)
ax.set_yticks(yy); ax.set_yticklabels(gnames, fontsize=9)
ax.axvline(0, color="k", lw=.7)
mx = max(abs(min(vals)), abs(max(vals))) + 0.6
ax.set_xlim(-mx, mx)
ax.set_xlabel("log2 fold change  (Ddx54-KD / WT)   ·   * q<0.05")
ax.set_title("면역회피·발암 유전자 — Ddx54 녹다운 시 방향 (독립재현)")
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "immune_evasion_genes.png.tmp"), dpi=135, format="png")
os.replace(os.path.join(RESULTS, "immune_evasion_genes.png.tmp"),
           os.path.join(RESULTS, "immune_evasion_genes.png"))
plt.close(fig)
print("==> [02] done: de_kd_vs_wt.csv, volcano_kd_vs_wt.png, immune_evasion_genes.png")
