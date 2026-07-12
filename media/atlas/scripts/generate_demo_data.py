#!/usr/bin/env python3
"""
Generate a biologically plausible synthetic NSCLC (non-small cell lung cancer)
single-cell RNA-seq demo dataset for the NSCLC Atlas app.

This is *synthetic teaching data*. It models the real tumor microenvironment:
real cell-type labels, real canonical marker genes, and expression drawn from a
generative model with dropout so feature plots and dot plots look like real
scRNA-seq. To use REAL public data instead, see scripts/convert_h5ad.py.

Outputs (into ../public/data):
  meta.json  -> cell types, colors, samples, gene panel, UMAP coords,
                categorical labels, precomputed dot-plot + composition.
  expr.bin   -> per-gene min-max normalized expression, uint8, row-major
                (cell-major): value at index (cell * nGenes + gene).
"""
import json
import os
import struct
import numpy as np

RNG = np.random.default_rng(42)  # deterministic

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "data")
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Cell types (tumor microenvironment of NSCLC) + display colors
# ---------------------------------------------------------------------------
CELL_TYPES = [
    ("Malignant epithelial", "#e6194B"),
    ("Alveolar epithelial",  "#f58231"),
    ("CD8+ T",               "#4363d8"),
    ("CD4+ T",               "#42d4f4"),
    ("Treg",                 "#911eb4"),
    ("NK",                   "#000075"),
    ("B",                    "#3cb44b"),
    ("Plasma",               "#469990"),
    ("Macrophage/Myeloid",   "#9A6324"),
    ("Dendritic",            "#808000"),
    ("Mast",                 "#fabed4"),
    ("Fibroblast",           "#a9a9a9"),
    ("Endothelial",          "#ffe119"),
]
CT_NAMES = [c[0] for c in CELL_TYPES]
CT_COLORS = [c[1] for c in CELL_TYPES]
N_CT = len(CELL_TYPES)

# 2D layout: cluster centers in UMAP-like space. Related lineages placed near
# each other (T/NK together, epithelial together, stroma together).
CENTERS = np.array([
    [ 7.5,  6.5],   # Malignant epithelial
    [ 6.0,  8.5],   # Alveolar epithelial
    [-6.0,  2.0],   # CD8 T
    [-7.5,  0.0],   # CD4 T
    [-6.5, -2.0],   # Treg
    [-4.0,  4.0],   # NK
    [-8.0,  5.5],   # B
    [-9.5,  7.5],   # Plasma
    [ 2.0, -7.0],   # Macrophage
    [ 0.0, -5.0],   # Dendritic
    [ 3.5, -4.5],   # Mast
    [ 8.0, -6.0],   # Fibroblast
    [ 9.5, -2.0],   # Endothelial
])
SPREAD = np.array([
    1.6, 1.1, 1.2, 1.2, 0.8, 0.8, 0.9, 0.7,
    1.4, 0.8, 0.6, 1.3, 1.1,
])

# ---------------------------------------------------------------------------
# 2. Composition: target fraction of each cell type in Tumor vs Normal tissue
# ---------------------------------------------------------------------------
# (indices match CELL_TYPES order)
FRAC_TUMOR = np.array([0.30, 0.02, 0.14, 0.10, 0.05, 0.03, 0.03, 0.03,
                       0.14, 0.03, 0.02, 0.06, 0.05])
FRAC_NORMAL = np.array([0.01, 0.22, 0.10, 0.10, 0.02, 0.05, 0.05, 0.02,
                        0.09, 0.02, 0.03, 0.10, 0.19])
FRAC_TUMOR /= FRAC_TUMOR.sum()
FRAC_NORMAL /= FRAC_NORMAL.sum()

N_TUMOR = 5600
N_NORMAL = 3400
PATIENTS = ["P01", "P02", "P03", "P04", "P05", "P06"]

# ---------------------------------------------------------------------------
# 3. Gene panel: canonical NSCLC markers -> cell-type indices they mark
# ---------------------------------------------------------------------------
MARKERS = {
    "EPCAM": [0, 1], "KRT19": [0, 1], "KRT8": [0, 1], "NAPSA": [0, 1],
    "SFTPC": [1], "SFTPB": [1], "SCGB1A1": [1],
    "MKI67": [0], "TOP2A": [0],
    "PTPRC": [2, 3, 4, 5, 6, 7, 8, 9, 10],  # CD45, pan-immune
    "CD3D": [2, 3, 4], "CD3E": [2, 3, 4],
    "CD8A": [2], "CD8B": [2], "GZMK": [2],
    "CD4": [3, 4], "IL7R": [3],
    "FOXP3": [4], "CTLA4": [4], "IL2RA": [4],
    "GZMB": [2, 5], "NKG7": [2, 5], "GNLY": [5], "KLRD1": [5], "NCAM1": [5],
    "CD79A": [6], "MS4A1": [6], "CD19": [6],
    "MZB1": [7], "IGHG1": [7], "JCHAIN": [7],
    "CD68": [8], "CD14": [8], "LYZ": [8, 9], "MARCO": [8], "FCGR3A": [8],
    "CLEC9A": [9], "LILRA4": [9], "FCER1A": [9],
    "TPSAB1": [10], "CPA3": [10], "KIT": [10],
    "COL1A1": [11], "DCN": [11], "PDGFRB": [11], "ACTA2": [11],
    "PECAM1": [12], "VWF": [12], "CLDN5": [12], "CDH5": [12],
}
GENES = list(MARKERS.keys())
N_GENES = len(GENES)

# baseline mean log-expression matrix (gene x celltype)
HIGH, LOW = 3.4, 0.12
BASE = np.full((N_GENES, N_CT), LOW)
for gi, g in enumerate(GENES):
    for ct in MARKERS[g]:
        # pan-immune marker slightly lower than lineage-defining markers
        BASE[gi, ct] = 2.2 if len(MARKERS[g]) > 4 else HIGH

# ---------------------------------------------------------------------------
# 4. Assign cells
# ---------------------------------------------------------------------------
def assign(n, frac, condition_id):
    counts = np.floor(frac * n).astype(int)
    counts[0] += n - counts.sum()  # fix rounding on the largest bucket
    ct = np.concatenate([np.full(c, i) for i, c in enumerate(counts)])
    cond = np.full(n, condition_id, dtype=np.int32)
    return ct, cond

ct_t, cond_t = assign(N_TUMOR, FRAC_TUMOR, 1)
ct_n, cond_n = assign(N_NORMAL, FRAC_NORMAL, 0)
ct = np.concatenate([ct_t, ct_n]).astype(np.int32)
cond = np.concatenate([cond_t, cond_n]).astype(np.int32)
N = ct.shape[0]

# shuffle
order = RNG.permutation(N)
ct, cond = ct[order], cond[order]

# patient assignment (each patient contributes both tumor + normal cells)
patient = RNG.integers(0, len(PATIENTS), size=N).astype(np.int32)
# sample label = "P0x Tumor" / "P0x Normal"
sample_names = []
sample_index_map = {}
for p in PATIENTS:
    for c in ("Normal", "Tumor"):
        sample_index_map[(p, c)] = len(sample_names)
        sample_names.append(f"{p} {c}")
sample = np.array([
    sample_index_map[(PATIENTS[patient[i]], "Tumor" if cond[i] == 1 else "Normal")]
    for i in range(N)
], dtype=np.int32)

# ---------------------------------------------------------------------------
# 5. UMAP-like coordinates
# ---------------------------------------------------------------------------
coords = np.empty((N, 2), dtype=np.float64)
for i in range(N):
    c = ct[i]
    coords[i] = CENTERS[c] + RNG.normal(0, SPREAD[c], size=2)
# gentle global warp so it looks organic, not gaussian blobs
coords[:, 0] += 0.35 * np.sin(coords[:, 1] * 0.4)
coords[:, 1] += 0.30 * np.cos(coords[:, 0] * 0.4)

# ---------------------------------------------------------------------------
# 6. Expression matrix (cells x genes) with dropout
# ---------------------------------------------------------------------------
expr = np.zeros((N, N_GENES), dtype=np.float32)
for gi in range(N_GENES):
    mu = BASE[gi, ct]                        # per-cell mean for this gene
    vals = RNG.normal(mu, 0.55)              # biological + technical noise
    vals = np.clip(vals, 0, None)
    # dropout: low-mean genes drop out more (classic scRNA-seq sparsity)
    p_detect = 1.0 / (1.0 + np.exp(-(mu - 0.9) * 2.2))
    detected = RNG.random(N) < p_detect
    vals = vals * detected
    expr[:, gi] = vals

# precompute dot-plot (per celltype x gene): mean expr among all cells + pct>0
dot_mean = np.zeros((N_CT, N_GENES))
dot_pct = np.zeros((N_CT, N_GENES))
for c in range(N_CT):
    m = ct == c
    if m.sum() == 0:
        continue
    sub = expr[m]
    dot_mean[c] = sub.mean(axis=0)
    dot_pct[c] = (sub > 0).mean(axis=0) * 100.0

# per-gene min-max normalize for the color overlay, then quantize to uint8
gmax = expr.max(axis=0)
gmax[gmax == 0] = 1.0
expr_norm = expr / gmax
expr_u8 = np.clip(np.round(expr_norm * 255), 0, 255).astype(np.uint8)

# ---------------------------------------------------------------------------
# 7. Composition summaries
# ---------------------------------------------------------------------------
def composition_by(group_vals, n_groups):
    out = np.zeros((n_groups, N_CT), dtype=int)
    for i in range(N):
        out[group_vals[i], ct[i]] += 1
    return out.tolist()

comp_by_condition = composition_by(cond, 2)            # [Normal, Tumor]
comp_by_patient = composition_by(patient, len(PATIENTS))

# ---------------------------------------------------------------------------
# 8. Write files
# ---------------------------------------------------------------------------
meta = {
    "dataset": {
        "name": "NSCLC Atlas (synthetic demo)",
        "description": "Synthetic non-small cell lung cancer tumor microenvironment "
                       "modeled on published scRNA-seq studies. Replace with real "
                       "data via scripts/convert_h5ad.py.",
        "nCells": int(N),
        "nGenes": int(N_GENES),
    },
    "cellTypes": [{"id": i, "name": CT_NAMES[i], "color": CT_COLORS[i]} for i in range(N_CT)],
    "conditions": ["Normal", "Tumor"],
    "patients": PATIENTS,
    "samples": sample_names,
    "genes": GENES,
    "markerGenes": {CT_NAMES[c]: [g for g in GENES if c in MARKERS[g] and len(MARKERS[g]) <= 3]
                    for c in range(N_CT)},
    # per-cell arrays (coordinates rounded to keep file small)
    "x": [round(float(v), 3) for v in coords[:, 0]],
    "y": [round(float(v), 3) for v in coords[:, 1]],
    "cellType": ct.tolist(),
    "condition": cond.tolist(),
    "sample": sample.tolist(),
    "patient": patient.tolist(),
    # precomputed analytics
    "dotPlot": {
        "mean": [[round(float(v), 3) for v in row] for row in dot_mean],
        "pct": [[round(float(v), 1) for v in row] for row in dot_pct],
    },
    "composition": {
        "byCondition": comp_by_condition,
        "byPatient": comp_by_patient,
    },
}

with open(os.path.join(OUT_DIR, "meta.json"), "w") as f:
    json.dump(meta, f, separators=(",", ":"))

with open(os.path.join(OUT_DIR, "expr.bin"), "wb") as f:
    f.write(expr_u8.tobytes(order="C"))  # row-major: cell * nGenes + gene

print(f"Wrote {N} cells x {N_GENES} genes")
print(f"  meta.json : {os.path.getsize(os.path.join(OUT_DIR, 'meta.json'))/1024:.0f} KB")
print(f"  expr.bin  : {os.path.getsize(os.path.join(OUT_DIR, 'expr.bin'))/1024:.0f} KB")
