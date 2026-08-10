#!/usr/bin/env python3
"""
02_de_p3c_vs_p0c.py — INDEPENDENT differential expression for resistance
acquisition (P3C vs P0C), using our own limma-style empirical-Bayes moderated
t-test (self-contained, no author padj consumed). Also classifies the anti-PD-1
drug-response pattern (REVERSED / CONSTITUTIVE / LOST-INDUCTION / PARADOXICAL)
from the single-replicate drug arms (P0D, P3D) — qualitative, n=1, flagged as such.

Outputs: de_p3c_vs_p0c.csv, drug_response.csv, volcano_p3c_vs_p0c.png,
drug_response_patterns.png. Reads GHBIO_RESULTS.
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

# --- P3C vs P0C moderated t-test (the resistance-acquisition contrast) ---
lfc, t, p, s2, df = C.moderated_ttest(L, C.GROUPS["P0C"], C.GROUPS["P3C"])
q = C.bh_fdr(p)
de = pd.DataFrame({
    "gene": genes, "logFC": lfc, "t": t, "p": p, "q": q,
    "P0C_mean": L[:, C.GROUPS["P0C"]].mean(1),
    "P3C_mean": L[:, C.GROUPS["P3C"]].mean(1),
}).set_index("gene")
de = de.sort_values("t", key=lambda s: s.abs(), ascending=False)
de.to_csv(os.path.join(RESULTS, "de_p3c_vs_p0c.csv"))

up = ((de.q < 0.05) & (de.logFC > 1)).sum()
dn = ((de.q < 0.05) & (de.logFC < -1)).sum()
print(f"==> P3C vs P0C: {up} up, {dn} down (q<0.05,|logFC|>1); "
      f"XYLT1 logFC={de.loc['XYLT1','logFC']:.2f} q={de.loc['XYLT1','q']:.3f}" if 'XYLT1' in de.index else "")

# --- Volcano ---
fig, ax = plt.subplots(figsize=(8.5, 7))
x = de["logFC"].values; y = -np.log10(np.clip(de["p"].values, 1e-300, None))
sig = (de["q"].values < 0.05) & (np.abs(x) > 1)
ax.scatter(x[~sig], y[~sig], s=6, c="#cfcfcf", alpha=.5, rasterized=True)
ax.scatter(x[sig & (x > 0)], y[sig & (x > 0)], s=9, c="#d64545", alpha=.7, rasterized=True)
ax.scatter(x[sig & (x < 0)], y[sig & (x < 0)], s=9, c="#3b6fd6", alpha=.7, rasterized=True)
label_genes = C.TIER1_TARGETS + C.TIER2_TARGETS + ["SLCO1B3", "NDRG1", "FGF5", "ITGA6",
              "LAMB3", "CD274", "EPAS1", "HLA-DMB", "NDRG1", "MST1R", "CA2"]
for g in dict.fromkeys(label_genes):
    if g in de.index:
        r = de.loc[g]
        ax.annotate(g, (r["logFC"], -np.log10(max(r["p"], 1e-300))),
                    fontsize=8, fontweight="bold",
                    xytext=(4, 3), textcoords="offset points")
        ax.scatter([r["logFC"]], [-np.log10(max(r["p"], 1e-300))], s=26,
                   facecolor="none", edgecolor="k", lw=.8, zorder=5)
ax.axvline(1, color="grey", ls="--", lw=.7); ax.axvline(-1, color="grey", ls="--", lw=.7)
ax.axhline(-np.log10(0.05), color="grey", ls=":", lw=.7)
ax.set_xlabel("log2 fold change  (P3C / P0C)")
ax.set_ylabel("-log10 p  (moderated t)")
ax.set_title("독립재현 — 내성 획득 차등발현 (P3 내성 vs P0 민감, vehicle)")
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "volcano_p3c_vs_p0c.png.tmp"), dpi=140, format="png")
os.replace(os.path.join(RESULTS, "volcano_p3c_vs_p0c.png.tmp"),
           os.path.join(RESULTS, "volcano_p3c_vs_p0c.png"))
plt.close(fig)

# --- Drug-response patterns (qualitative; drug arms are n=1) ---
# P0 drug effect = P0D - mean(P0C); P3 drug effect = P3D - mean(P3C)
p0c = L[:, C.GROUPS["P0C"]].mean(1)
p3c = L[:, C.GROUPS["P3C"]].mean(1)
p0d = L[:, C.GROUPS["P0D"][0]]
p3d = L[:, C.GROUPS["P3D"][0]]
d0 = p0d - p0c   # anti-PD-1 effect in sensitive line
d3 = p3d - p3c   # anti-PD-1 effect in resistant line
TH = 0.7


def classify(a, b):
    # a = P0 drug effect, b = P3 drug effect
    if a < -TH and b > TH:
        return "PARADOXICAL"          # P0 suppressed -> P3 up
    if a > TH and b < TH * 0.5:
        return "REVERSED"             # P0 induced -> P3 lost/reversed (induction failed)
    if a > TH and b > TH:
        return "BOTH-INDUCED"
    if abs(a) < TH and abs(b) < TH:
        return "CONSTITUTIVE"         # drug-independent (fixed program)
    if a > TH and b <= TH:
        return "LOST-INDUCTION"
    return "OTHER"


drug = pd.DataFrame({
    "gene": genes, "P0_drug_effect": d0, "P3_drug_effect": d3,
    "pattern": [classify(a, b) for a, b in zip(d0, d3)],
}).set_index("gene")
drug.to_csv(os.path.join(RESULTS, "drug_response.csv"))

# figure: scatter of P0 vs P3 drug effect, with report-cited genes labeled
fig, ax = plt.subplots(figsize=(8, 7))
ax.scatter(d0, d3, s=5, c="#d0d0d0", alpha=.4, rasterized=True)
pat_colors = {"REVERSED": "#d64545", "CONSTITUTIVE": "#2c8a4a", "PARADOXICAL": "#8a5cd6",
              "LOST-INDUCTION": "#d68a2c"}
cited = list(C.REPORT_DRUG_PATTERN.keys())
for g in cited:
    if g in drug.index:
        r = drug.loc[g]
        c = pat_colors.get(C.REPORT_DRUG_PATTERN[g], "k")
        ax.scatter([r["P0_drug_effect"]], [r["P3_drug_effect"]], s=55, c=c,
                   edgecolor="k", lw=.6, zorder=4)
        ax.annotate(g, (r["P0_drug_effect"], r["P3_drug_effect"]), fontsize=8,
                    xytext=(4, 3), textcoords="offset points")
ax.axhline(0, color="grey", lw=.6); ax.axvline(0, color="grey", lw=.6)
ax.set_xlabel("anti-PD-1 효과, 민감주  (P0D − P0C)")
ax.set_ylabel("anti-PD-1 효과, 내성주  (P3D − P3C)")
ax.set_title("약물반응 패턴 (n=1 정성적) — 보고서 지목 유전자")
handles = [plt.Line2D([0], [0], marker="o", ls="", mec="k", mfc=c, label=k)
           for k, c in pat_colors.items()]
ax.legend(handles=handles, fontsize=8, loc="upper left")
fig.tight_layout()
fig.savefig(os.path.join(RESULTS, "drug_response_patterns.png.tmp"), dpi=135, format="png")
os.replace(os.path.join(RESULTS, "drug_response_patterns.png.tmp"),
           os.path.join(RESULTS, "drug_response_patterns.png"))
plt.close(fig)
print("==> [02] done: de_p3c_vs_p0c.csv, drug_response.csv, volcano + drug figures")
