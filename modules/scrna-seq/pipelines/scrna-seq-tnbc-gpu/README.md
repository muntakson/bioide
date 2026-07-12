# GHBIO AI Co-Scientist — TNBC 유방암 scRNA-seq (GPU 재현) Tutorial

사람 삼중음성 유방암(TNBC) 단일세포 RNA 시퀀싱을 **원시 read부터 GPU로 재현**하는 실습 /
Reproducing a triple-negative breast cancer single-cell RNA-seq discovery from **raw reads on a GPU**.

This tutorial reproduces the central result of **Gao et al., *Nature Biotechnology* 2021 —
"Delineating copy number and clonal substructure in human tumors from single-cell transcriptomes"
(the copyKAT paper)**: that genome-wide **copy-number aberrations (CNAs) inferred from the
transcriptome** separate **aneuploid malignant cells** from **diploid normal (immune/stromal)
cells**, and reveal **tumor subclones**.

Unlike the melanoma tutorial (which starts from the authors' published matrix), this one starts
from the **raw 10x reads** and reprocesses everything, using a **modern GPU stack** (scVI on
CUDA for the latent space + Leiden clustering) followed by a from-scratch **inferCNV** tumor call.

> 이 튜토리얼은 공개된 TNBC 종양 10x 데이터를 원시 read부터 다시 처리해, 최신 **GPU(scVI)**
> 클러스터링과 **inferCNV**로 종양(이배수성)세포를 정상(정배수성)세포와 구분하고 종양 아클론을
> 찾는 copyKAT(Gao et al. 2021)의 핵심 발견을 재현합니다. 발현 기반 추론이며 임상적 증명이
> 아닙니다.

---

## Dataset / 데이터

- **Dataset:** [GSE148673](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE148673) —
  human TNBC tumor, patient **TNBC1** (SRA `SRR11546787`, 10x Chromium 3′ GEX). Open access.
- **Raw data:** the author-submitted **Cell Ranger BAM** (~23 GB) on ENA. Cell Ranger cannot run
  on this aarch64 box, so `01_download_tnbc.sh` downloads the BAM and `bam2fastq.py` (pysam)
  losslessly reconstructs the original R1 (barcode+UMI) / R2 (cDNA) FASTQs. STARsolo re-corrects
  barcodes against the 10x whitelist.
- **Paper:** Gao et al., *Nature Biotechnology* 39:599–608 (2021).

## Pipeline / 파이프라인

| Step | Script | What it does |
|------|--------|--------------|
| 0  | `00_setup_env.sh`      | CPU Scanpy + pysam venv (`~/ghbio-venv`) |
| 0b | `00b_setup_gpu.sh`     | GPU venv `~/ghbio-venv-gpu/tnbc-copykat` (scvi-tools[cuda]); verifies CUDA |
| 1  | `01_download_tnbc.sh`  | Download TNBC1 Cell Ranger BAM → reconstruct FASTQ |
| 2a | `02a_build_starsolo.sh`| Compile STAR (shared, ARM) |
| 2b | `02b_reference.sh`     | GRCh38 index + GTF (shared; GTF also feeds inferCNV) |
| 2c | `02c_run_starsolo.sh`  | STARsolo → gene × cell count matrix (auto v2/v3) |
| 3  | `03_gpu_tumor_cnv.py`  | **GPU scVI** latent → UMAP/Leiden/markers → **inferCNV** tumor/normal call → **subclones** |
| 4  | (AI panel)             | Interpretation & hypotheses, with the CNV summary as context |
| 5  | `05_make_report.sh`    | Merged PDF report (figures + AI write-ups + marker appendix) |

`05_make_easy_report.sh` builds the one-click **🎓 고등학생 버전 보고서** PDF
(`GHBIO_고등학생_리포트.pdf`). `survey.json` powers the 이해도 테스트.

## Key outputs / 주요 산출물

- `cnv_heatmap.png` — inferred large-scale CNVs separating tumor (aneuploid) from normal (diploid)
- `umap_tumor_normal.png` — UMAP colored by inferred CNV status
- `tumor_subclones.png` + `subclone_composition.csv` — clonal substructure of the tumor
- `cnv_cluster_summary.csv` — per-cluster CNV/tumor-call summary (AI context)
- `markers_by_cluster.csv`, `celltype_draft.csv`, `tnbc_composition.png`, `tnbc_processed.h5ad`

> **Not a bit-for-bit rerun of the copyKAT R package** — it's a modern, GPU-accelerated
> reproduction of the *finding*. Malignancy is **inferred** from expression, not proven by DNA
> sequencing.
