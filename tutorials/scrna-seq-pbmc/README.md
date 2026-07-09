# GHBIO AI Co-Scientist — Hands-on scRNA-seq Tutorial

단일세포 RNA 시퀀싱(scRNA-seq) 실습 튜토리얼 / Single-cell RNA-seq hands-on tutorial

This tutorial walks you through a complete **single-cell RNA-seq (scRNA-seq)** pipeline —
from raw 10x Genomics FASTQ reads to annotated cell clusters — and then shows how to feed
the results into the **GHBIO AI Co-Scientist** for hypothesis generation.

> 이 튜토리얼은 원시 FASTQ 데이터에서 시작해 세포 클러스터 주석까지 진행한 뒤,
> 결과를 AI Co-Scientist에 입력해 가설을 생성하는 전체 과정을 다룹니다.

---

## ⚠️ Platform note — ARM64 / no Cell Ranger

The target machine is **aarch64 (ARM64) Linux** (an NVIDIA GB10 box with large unified RAM).

- **Cell Ranger is x86-64 only and is NOT used here.** 10x's official Cell Ranger ships as an
  x86-64 binary and will not run on ARM64.
- Instead we use **STARsolo** (part of the STAR aligner), which **builds from source on ARM**
  and reproduces Cell Ranger's core gene-barcode counting.
- **Scanpy** (pure Python) handles QC, normalization, clustering and marker detection — it runs
  natively on ARM64.

> ARM64 환경에서는 Cell Ranger(x86 전용)를 사용할 수 없으므로, 소스에서 빌드 가능한
> STARsolo와 순수 파이썬 라이브러리인 Scanpy를 사용합니다.

---

## The 4-step pipeline

```
  ┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐
  │ 1. FASTQ   │→→ │ 2. STARsolo  │→→ │ 3. Scanpy QC  │→→ │ 4. AI Co-Scientist │
  │  download  │   │  count matrix│   │  + clustering │   │  hypotheses        │
  └────────────┘   └──────────────┘   └───────────────┘   └────────────────────┘
```

| Step | What happens | Tool |
|------|--------------|------|
| **1. FASTQ**       | Download a small public 10x PBMC dataset (raw reads).            | `curl` |
| **2. STARsolo**    | Align reads to GRCh38 and produce a gene × cell count matrix.    | STAR / STARsolo |
| **3. Scanpy**      | QC filtering, normalization, PCA/UMAP, Leiden clustering, markers.| Scanpy |
| **4. Co-Scientist**| Feed markers + draft cell types into the AI to generate hypotheses.| GHBIO AI |
| **5. Report**      | Merge figures + write-ups + marker appendix into one branded PDF.  | pandoc + wkhtmltopdf |

---

## Prerequisites / 사전 준비물

- **OS**: aarch64 (ARM64) Linux
- **Compilers**: `gcc`/`g++` with C++11 support, `make` (for building STAR)
  - Debian/Ubuntu: `sudo apt-get install -y build-essential zlib1g-dev`
- **Python**: 3.9+ (a virtual environment is created for you)
- **Tools**: `curl`, `tar`, `gzip`
- **Disk**: ~40 GB free (reference + index + FASTQs + results)
- **RAM**: ~30+ GB for building the STAR genome index (the GB10's unified RAM is plenty)

---

## Directory layout / 디렉터리 구조

The scripts use these fixed locations (created automatically):

```
~/ghbio-venv/                         # Python virtual environment (step 0)
~/bin/STAR                            # compiled STAR binary (step 2a)
~/ghbio-tutorial/
├── data/
│   └── fastq/                        # downloaded 10x FASTQ files (step 1)
├── ref/
│   ├── GRCh38.primary_assembly.genome.fa   # reference genome (step 2b)
│   ├── gencode.vXX.annotation.gtf          # gene annotation (step 2b)
│   ├── star_index/                         # STAR genome index (step 2b)
│   └── whitelist/                          # 10x barcode whitelists (step 2c)
└── results/
    ├── starsolo/                    # STARsolo output incl. Solo.out/ (step 2c)
    ├── umap_clusters.png            # Scanpy UMAP (step 3)
    ├── qc_violin.png                # Scanpy QC plots (step 3)
    ├── markers_by_cluster.csv       # top markers per cluster (step 3)
    └── celltype_draft.csv           # draft cell-type annotation (step 3)
```

---

## Scripts and run order / 실행 순서

Run them in numeric order. Each script is idempotent (safe to re-run).

| # | Script | Purpose | Typical time |
|---|--------|---------|--------------|
| 0 | `00_setup_env.sh`      | Create the `~/ghbio-venv` venv and pip-install Scanpy + friends. | 2–5 min |
| 1 | `01_download_pbmc.sh`  | Download one small public 10x PBMC FASTQ sample (~5 GB tar).     | 5–15 min (network) |
| 2a| `02a_build_starsolo.sh`| Build the `STAR` binary from source **on ARM64**.               | 5–15 min |
| 2b| `02b_reference.sh`     | Download GRCh38 FASTA+GTF and build the STAR genome index.       | **one-time**, 30–60 min, ~30 GB RAM |
| 2c| `02c_run_starsolo.sh`  | Run STARsolo → gene-barcode count matrix (`Solo.out/`).          | 10–30 min |
| 3 | `03_scanpy_qc.py`      | QC, normalization, clustering, markers, draft annotation.       | 2–10 min |
| 4 | `04_ai_coscientist_prompts.md` | Reference: how to prompt the AI Co-Scientist with results. | — |
| 5 | `05_make_report.sh`    | Merge figures + easy/expert reports + marker appendix into one branded PDF. | 1–2 min |

### Quick start

```bash
cd /path/to/tutorial

# 0. environment
bash 00_setup_env.sh

# 1. data
bash 01_download_pbmc.sh

# 2. alignment / counting  (2b is the expensive one-time step)
bash 02a_build_starsolo.sh
bash 02b_reference.sh
bash 02c_run_starsolo.sh

# 3. analysis (uses the venv from step 0)
source ~/ghbio-venv/bin/activate
python 03_scanpy_qc.py
deactivate

# 4. read this and paste your results into the AI Co-Scientist
less 04_ai_coscientist_prompts.md

# 5. merge figures + reports (easy + expert) + marker appendix into one PDF
#    (after you've saved the Step-4 AI write-ups as step4_ai_report*.md)
GHBIO_REPORT_AUTHOR="Your Name" bash 05_make_report.sh
# -> ~/ghbio-tutorial/results/GHBIO_scRNAseq_tutorial_report.pdf
```

> **Tip:** `02b_reference.sh` is a one-time cost. Once `~/ghbio-tutorial/ref/star_index/` exists,
> you can reuse it for every future sample — you never need to rebuild it.

### Shortcut for people who skip STARsolo

Steps 2a–2c are heavy (reference download + index build). If you just want to learn the
**analysis** side, you can skip them: download a 10x *pre-computed* filtered matrix and point
step 3 at it:

```bash
python 03_scanpy_qc.py --matrix /path/to/filtered_feature_bc_matrix
```

`03_scanpy_qc.py` accepts any 10x-format filtered matrix directory (STARsolo **or** Cell Ranger).

---

## Resource & time expectations (summary)

| Resource | Requirement |
|----------|-------------|
| Disk     | ~40 GB (FASTQ ~5 GB, genome+GTF ~4 GB, index ~30 GB, results small) |
| RAM      | ~30+ GB for `genomeGenerate`; a few GB for STARsolo mapping and Scanpy |
| CPU      | Multi-core recommended (`--runThreadN` auto-set to `nproc`) |
| Network  | ~10 GB of downloads total (FASTQ + reference + whitelist) |

All heavy compute is one-time (index build) or short (mapping a 1k-cell sample).
