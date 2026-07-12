# NSCLC Atlas — Project Summary

An interactive, full-stack web app that visualizes a **single-cell RNA-seq (scRNA-seq) cancer cell atlas** of the **non-small cell lung cancer (NSCLC)** tumor microenvironment. It is built as a **teaching tool for university (bioinformatics / graduate) students** learning the standard single-cell analysis workflow.

---

## At a glance

| | |
|---|---|
| **Purpose** | Teach the scRNA-seq analysis workflow through an explorable NSCLC atlas |
| **Audience** | University / graduate bioinformatics students |
| **Stack** | Next.js 14 (App Router) · TypeScript · Tailwind CSS |
| **Rendering** | Custom HTML5 Canvas UMAP renderer (no heavy chart deps) |
| **Dataset** | 9,000 cells · 13 cell types · 50 canonical marker genes |
| **Data size** | `meta.json` ≈ 194 KB + `expr.bin` ≈ 439 KB (loads in one round-trip) |
| **Deploy** | Static/SSR Next.js build — Vercel-ready, zero config |
| **Status** | Builds clean; verified in headless Chromium with zero console errors |

---

## What it does

### Core visualizations
- **UMAP cell map** — every point is one cell, positioned by a UMAP embedding so transcriptionally similar cells cluster together. Interactive zoom, pan, and per-cell hover tooltips. Color cells by **cell type**, **tissue** (tumor vs. normal), **patient**, or **sample**.
- **Gene feature plot** — search any of 50 canonical markers (e.g. `EPCAM`, `CD8A`, `FOXP3`) and recolor the UMAP by that gene's expression using a viridis scale.
- **Composition charts** — stacked bars comparing cell-type proportions across tumor vs. adjacent-normal tissue and across patients.
- **Marker dot plot** — the canonical scanpy-style plot: dot size = % of cells expressing, color = per-gene scaled mean expression. Click any gene to jump to its feature plot.
- **Legend isolation** — click a cell type to dim all others and inspect one compartment.

### Learning layer (grad level)
- **Guided tour** — auto-opens on first visit (reopenable via the **? Guided tour** button) and *drives the live app* — it sets the feature plot to EPCAM then CD8A so students see each concept happen as they read it.
- **Concepts tab** — expandable cards covering the real pipeline (QC → `normalize_total`/`log1p` → HVGs → PCA → kNN graph → Leiden → UMAP → marker DE), UMAP interpretation traps, dropout/zero-inflation, the NSCLC tumor microenvironment, and compositional-analysis caveats (scCODA / Milo).
- **Exercises tab** — interactive challenges whose checkmarks update **live** as the student drives the atlas (e.g. "color by a marker of CD8+ T cells" turns green when they do), each with a hint, a "Show me" button, and a grad-level explanation.
- **"How to read this" notes** — under every panel, flagging common misconceptions (UMAP distances aren't quantitative; proportions are compositional and protocol-biased).

---

## Architecture

```
app/
  page.tsx            # main dashboard (client): state, tabs, tour wiring, layout
  layout.tsx          # root layout + metadata
  globals.css         # Tailwind + base styles
  icon.svg            # favicon
components/
  UmapPlot.tsx        # canvas UMAP: zoom / pan / hover / color modes
  GeneSearch.tsx      # gene autocomplete → feature plot
  Legend.tsx          # cell-type legend, click to isolate
  CompositionChart.tsx# stacked composition bars (tissue / patient)
  DotPlot.tsx         # marker gene dot plot (SVG)
  Walkthrough.tsx     # guided tour overlay that drives app state
  ConceptCards.tsx    # expandable grad-level concept explainers
  Exercises.tsx       # live-checked interactive challenges
  InfoNote.tsx        # collapsible "how to read this" note
lib/
  types.ts            # shared TypeScript types
  data.ts             # loads meta.json + expr.bin, caches
  colors.ts           # viridis colormap + categorical palettes
  learn.ts            # all educational content (tour, concepts) — edit for your course
public/data/
  meta.json           # cell metadata, coords, precomputed dot plot + composition
  expr.bin            # uint8 expression matrix (cell-major)
scripts/
  generate_demo_data.py  # makes the synthetic dataset
  convert_h5ad.py        # converts a real .h5ad (AnnData) into the same format
```

### Data model
`meta.json` holds per-cell arrays (`x`, `y`, `cellType`, `condition`, `sample`, `patient`), the gene panel, cell-type colors, and precomputed `dotPlot` + `composition` analytics. `expr.bin` is a flat `Uint8Array` of per-gene min-max normalized expression in **cell-major** order — the value for cell *i*, gene *j* is at index `i * nGenes + j`, divided by 255 to get a 0–1 value for the color overlay. Keeping expression in a compact binary means the whole atlas loads fast, even on a phone.

### Design decisions
- **Custom canvas renderer** instead of a charting library — keeps the bundle small (~93 KB first load), stays smooth at 9,000 points, and works on mobile.
- **Precomputed analytics** (dot plot, composition) in Python so the client stays simple and instant.
- **Synthetic-but-honest data** — a generative model with canonical markers and dropout makes feature plots and dot plots behave like real scRNA-seq, while the app clearly states the data is simulated.

---

## The data

The app ships with a **biologically grounded synthetic dataset** so it runs instantly with no download. It models the NSCLC tumor microenvironment across 13 populations — malignant epithelial, alveolar epithelial, CD8+ T, CD4+ T, Treg, NK, B, plasma, macrophage/myeloid, dendritic, mast, fibroblast, endothelial — using canonical marker genes and a dropout model, with realistic tumor-vs-normal composition shifts (malignant and myeloid expansion in tumor tissue).

### Swapping in real public data
`scripts/convert_h5ad.py` converts a real published dataset into the exact same `meta.json` + `expr.bin` format — no frontend changes needed. Suggested sources:
- **CELLxGENE Discover** (filter for lung / NSCLC, download `.h5ad`)
- **Kim et al. 2020** — GEO `GSE131907` (~200k NSCLC cells)
- **Lambrechts et al. 2018** — ArrayExpress `E-MTAB-6149` / `E-MTAB-6653`

```bash
python scripts/convert_h5ad.py your_dataset.h5ad \
    --celltype cell_type --condition tissue \
    --sample sample_id --patient patient_id --max-cells 40000
```

---

## Running it

```bash
npm install
npm run dev          # http://localhost:3000

# production / deploy
npm run build && npm start
```

It is a standard Next.js App Router project — push to GitHub and import into Vercel for a zero-config deploy, giving every student a URL with no local setup.

---

## Verification

- `next build` compiles with **no type errors**.
- Headless Chromium smoke tests confirmed: the UMAP renders and loads data; the CD8A feature plot correctly localizes expression to the CD8+ T cluster; the guided tour opens and drives the app; the Concepts and Exercises tabs render; the exercise counter updates live (0 → 1) when an answer is applied; and there are **zero console errors**.

---

## Possible next steps
- **Differential-expression view** — tumor vs. normal per cell type with a volcano plot (a natural next exercise).
- **Dockerfile + Vercel config** for one-click class deployment.
- **Sub-clustering demo** — drill into the T-cell compartment to resolve exhausted states.
- **Real-data classroom pack** — a converted public dataset plus a guided assignment.

---

*NSCLC Atlas — a teaching tool built with Next.js. Demo data is synthetic; swap in real data with `scripts/convert_h5ad.py`. MIT licensed for teaching and coursework.*
