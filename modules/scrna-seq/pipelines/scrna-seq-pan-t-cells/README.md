# GHBIO AI Co-Scientist — Glioblastoma scRNA-seq Tutorial

사람 교모세포종(뇌종양) 단일세포 RNA 시퀀싱 실습 / Human glioblastoma single-cell RNA-seq hands-on tutorial

This is a **second scRNA-seq tutorial** built on the same pipeline as the PBMC one, but on a
very different tissue: a **dissociated human glioblastoma (brain tumor)**. Blood (PBMC) is a
handful of immune cell types; a glioblastoma contains **malignant glioma cells** plus a rich
**tumor microenvironment** — astrocytes, oligodendrocytes/OPCs, neurons, microglia and
tumor-associated macrophages, T cells, endothelium and pericytes — so the clustering and the
AI interpretation are much richer.

> 이 튜토리얼은 PBMC 튜토리얼과 동일한 파이프라인을 사용하지만, 혈액 대신 **사람 교모세포종
> (뇌종양)** 조직을 분석합니다. 종양세포와 다양한 미세환경 세포가 섞여 있어 클러스터링과
> AI 해석이 훨씬 풍부합니다.

---

## Why this dataset / 이 데이터를 고른 이유

- **Dataset:** [Human Glioblastoma Multiforme: 3' v3 Whole Transcriptome Analysis](https://www.10xgenomics.com/datasets/human-glioblastoma-multiforme-3-v-3-whole-transcriptome-analysis-3-standard-4-0-0) (10x Genomics)
- **Human** → reuses the **same GRCh38 STAR index** built for the PBMC tutorial (no rebuild).
- **Same 3' v3 chemistry** (CB=16 bp, UMI=12 bp) → identical STARsolo barcode settings.
- **Different biology** → a brain-tumor marker panel in `03_scanpy_qc.py` and glioblastoma-specific
  AI prompts in `04_ai_coscientist_prompts.md`.

> **If you already ran the PBMC tutorial**, steps `00`, `02a`, `02b` are already done and will be
> skipped — you effectively only need step `01` (download) and steps `2c`/`3`/`4`/`5`.

---

## ⚠️ Platform note — ARM64 / no Cell Ranger

The target machine is **aarch64 (ARM64) Linux**.

- **Cell Ranger is x86-64 only and is NOT used here.**
- We use **STARsolo** (builds from source on ARM) for gene-barcode counting, and **Scanpy**
  (pure Python) for QC, normalization, clustering and marker detection.

> ARM64 환경에서는 Cell Ranger(x86 전용) 대신 STARsolo와 Scanpy를 사용합니다.

---

## The 5-step pipeline

```
  ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐
  │ 1. FASTQ   │→→ │ 2. STARsolo  │→→ │ 3. Scanpy QC  │→→ │ 4. AI Co-Scientist │
  │  download  │   │  count matrix│   │  + clustering │   │  hypotheses        │
  └────────────┘   └──────────────┘   └───────────────┘   └────────────────────┘
```

| Step | What happens | Tool |
|------|--------------|------|
| **1. FASTQ**       | Download the public 10x glioblastoma dataset (raw reads, ~19 GB tar).  | `curl` |
| **2. STARsolo**    | Align reads to GRCh38 and produce a gene × cell count matrix.          | STAR / STARsolo |
| **3. Scanpy**      | QC filtering, normalization, PCA/UMAP, Leiden clustering, markers.     | Scanpy |
| **4. Co-Scientist**| Feed markers + draft cell types into the AI to generate hypotheses.    | GHBIO AI |
| **5. Report**      | Merge figures + write-ups + marker appendix into one branded PDF.      | pandoc + wkhtmltopdf |

---

## Scripts and run order / 실행 순서

Run them in numeric order. Each script is idempotent (safe to re-run).

| # | Script | Purpose | Typical time |
|---|--------|---------|--------------|
| 0 | `00_setup_env.sh`            | Create `~/ghbio-venv` and pip-install Scanpy + friends. | 2–5 min (skipped if done) |
| 1 | `01_download_glioblastoma.sh`| Download the 10x glioblastoma FASTQ sample (~19 GB tar). | 15–40 min (network) |
| 2a| `02a_build_starsolo.sh`     | Build the `STAR` binary from source on ARM64.           | 5–15 min (skipped if done) |
| 2b| `02b_reference.sh`          | GRCh38 FASTA+GTF + STAR index (**shared with PBMC**).    | one-time, 30–60 min (skipped if done) |
| 2c| `02c_run_starsolo.sh`       | Run STARsolo → gene-barcode count matrix (`Solo.out/`).  | 20–60 min |
| 3 | `03_scanpy_qc.py`           | QC, clustering, markers, **brain-tumor** draft annotation. | 2–10 min |
| 4 | `04_ai_coscientist_prompts.md` | Reference: glioblastoma-specific AI Co-Scientist prompts. | — |
| 5 | `05_make_report.sh`         | Merge figures + reports + marker appendix into one PDF.   | 1–2 min |

### Quick start

```bash
cd /path/to/tutorial

bash 00_setup_env.sh              # 0. environment (shared venv)
bash 01_download_glioblastoma.sh  # 1. data (~19 GB)
bash 02a_build_starsolo.sh        # 2a. STAR binary (shared)
bash 02b_reference.sh             # 2b. GRCh38 index (shared, one-time)
bash 02c_run_starsolo.sh          # 2c. count matrix

source ~/ghbio-venv/bin/activate  # 3. analysis
python 03_scanpy_qc.py
deactivate

less 04_ai_coscientist_prompts.md # 4. prompt the AI Co-Scientist with your results

GHBIO_REPORT_AUTHOR="Your Name" bash 05_make_report.sh   # 5. one PDF
```

### Shortcut for people who skip STARsolo

If you only want to learn the **analysis** side, skip steps 2a–2c and point step 3 at 10x's
**pre-computed** filtered matrix (a small ~72 MB download for this dataset):

```bash
curl -L -O https://cf.10xgenomics.com/samples/cell-exp/4.0.0/Parent_SC3v3_Human_Glioblastoma/Parent_SC3v3_Human_Glioblastoma_filtered_feature_bc_matrix.tar.gz
tar -xzf Parent_SC3v3_Human_Glioblastoma_filtered_feature_bc_matrix.tar.gz
python 03_scanpy_qc.py --matrix ./filtered_feature_bc_matrix
```

`03_scanpy_qc.py` accepts any 10x-format filtered matrix directory (STARsolo **or** Cell Ranger,
gzipped or plain).

---

## The brain-tumor marker panel / 뇌종양 마커 패널

`03_scanpy_qc.py` scores each cluster against a glioblastoma-oriented dictionary to produce a
**draft** label (verify with the AI Co-Scientist — these are starting points, not ground truth):

| Draft cell type | Example markers |
|-----------------|-----------------|
| Malignant glioma | EGFR, SOX2, CHI3L1, VIM, PTPRZ1 |
| Astrocyte        | GFAP, AQP4, SLC1A3, S100B |
| OPC-like         | OLIG1, OLIG2, PDGFRA, CSPG4 |
| Oligodendrocyte  | MBP, PLP1, MOG, MAG |
| Neuron           | RBFOX3, SYT1, STMN2, MAP2 |
| Microglia        | P2RY12, CX3CR1, TMEM119, AIF1 |
| Macrophage (TAM) | CD68, CD163, C1QA, C1QB |
| T cell           | CD3D, CD3E, CD2, CD8A |
| Endothelial      | PECAM1, VWF, CLDN5, FLT1 |
| Pericyte/Mural   | PDGFRB, RGS5, ACTA2 |
| Proliferating    | MKI67, TOP2A |

> Malignant glioma cells often co-opt astrocyte/OPC programs, so a cluster can look "glial" yet
> be tumor. Confirming malignancy usually needs CNV inference (e.g. inferCNV) — see the AI prompts.

---

## Resource & time expectations (summary)

| Resource | Requirement |
|----------|-------------|
| Disk     | ~50 GB (FASTQ ~19 GB, genome+GTF ~4 GB, index ~30 GB, results small) |
| RAM      | ~30+ GB for `genomeGenerate` (one-time); a few GB for mapping and Scanpy |
| CPU      | Multi-core recommended (`--runThreadN` auto-set to `nproc`) |
| Network  | ~23 GB total (FASTQ ~19 GB + reference ~4 GB), or ~72 MB with the matrix shortcut |

The reference/index build is shared with the PBMC tutorial and never needs rebuilding.
