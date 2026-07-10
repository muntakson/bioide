#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_glioblastoma.sh
# Download ONE public 10x Genomics human glioblastoma scRNA-seq FASTQ sample.
# 공개된 10x 사람 교모세포종(뇌종양) scRNA-seq FASTQ 샘플 하나를 다운로드합니다.
#
# Dataset: "Human Glioblastoma Multiforme: 3' v3 Whole Transcriptome Analysis"
#   https://www.10xgenomics.com/datasets/human-glioblastoma-multiforme-3-v-3-whole-transcriptome-analysis-3-standard-4-0-0
#   - Dissociated tumor from a human glioblastoma (male donor)
#   - 10x Chromium 3' v3 chemistry  (CB=16 bp, UMI=12 bp)  <-- same as step 2c
#   - tar archive is ~19 GB (bigger than the PBMC sample — plan disk/time)
#   - Unlike blood PBMC, this tumor tissue contains MANY distinct cell types:
#     malignant glioma cells, astrocytes, oligodendrocytes/OPCs, neurons,
#     microglia/tumor-associated macrophages, T cells, endothelium, pericytes.
#
# Why this dataset for a SECOND tutorial:
#   * Human → reuses the SAME GRCh38 STAR index built in step 2b (no rebuild).
#   * Same 3' v3 chemistry → identical STARsolo barcode settings as the PBMC run.
#   * Very different biology from PBMC → richer clustering + a brain-tumor marker
#     panel in 03_scanpy_qc.py, so the AI Co-Scientist has more to interpret.
#
# Idempotent: skips download if the FASTQs are already extracted; curl -C - resumes.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/fastq"
mkdir -p "${DATA_DIR}"

# --- Single-instance guard: prevent concurrent duplicate downloads -----------
# 중복 다운로드 방지 잠금장치.
# Clicking "Step 1" twice (e.g. via the full pipeline AND the standalone step)
# would start two curls writing to the SAME .tar file — wasting bandwidth and
# risking a corrupted archive. flock lets only ONE download run at a time;
# a second run aborts with a message instead of colliding with the first.
# The lock is held on fd 9 for the life of this script and released on exit.
LOCK_FILE="${DATA_DIR}/.glioblastoma_download.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "==> 이미 교모세포종 다운로드가 진행 중입니다 — 이 중복 실행을 건너뜁니다."
  echo "==> A glioblastoma download is already running; skipping this duplicate run."
  echo "    (진행 상황은 기존 창에서 확인하세요. / Watch the existing run for progress.)"
  exit 1
fi

# --- Verified public download URL (10x Genomics CDN) -------------------------
# 10x 공식 CDN의 검증된 다운로드 URL.
FASTQ_URL="https://cf.10xgenomics.com/samples/cell-exp/4.0.0/Parent_SC3v3_Human_Glioblastoma/Parent_SC3v3_Human_Glioblastoma_fastqs.tar"
TAR_NAME="Parent_SC3v3_Human_Glioblastoma_fastqs.tar"
TAR_PATH="${DATA_DIR}/${TAR_NAME}"

# The tar extracts to a NESTED layout:
#   Parent_SC3v3_Human_Glioblastoma_fastqs/Parent_SC3v3_Human_Glioblastoma/*.fastq.gz
# (the PBMC tar was one level; this one has an extra sample subdir — step 2c knows this.)
OUTER_DIR="${DATA_DIR}/Parent_SC3v3_Human_Glioblastoma_fastqs"
FASTQ_SUBDIR="${OUTER_DIR}/Parent_SC3v3_Human_Glioblastoma"

echo "==> [01] Downloading 10x human glioblastoma 3' v3 FASTQs into: ${DATA_DIR}"

# --- 1. Download (resumable) --------------------------------------------------
# curl -L : follow redirects,  -C - : resume a partial download.
# 이어받기(-C -)와 리다이렉트 추적(-L)을 사용해 다운로드합니다.
if [[ -d "${FASTQ_SUBDIR}" ]] && \
   compgen -G "${FASTQ_SUBDIR}/*_R1_*.fastq.gz" > /dev/null; then
  echo "==> FASTQ files already extracted, skipping download."
else
  echo "==> Downloading ${TAR_NAME} (~19 GB, may take a while)..."
  curl -L -C - -o "${TAR_PATH}" "${FASTQ_URL}"

  echo "==> Extracting tar archive..."
  tar -xvf "${TAR_PATH}" -C "${DATA_DIR}"
  # Keep the tar so a re-run can skip re-downloading; delete manually to save disk.
fi

echo ""
echo "==> Downloaded / extracted FASTQ files and sizes:"
ls -lh "${FASTQ_SUBDIR}"/*.fastq.gz

# --- 2. Explain the 10x FASTQ naming convention ------------------------------
cat <<'EOF'

------------------------------------------------------------------------------
10x FASTQ naming convention  /  10x FASTQ 파일 이름 규칙
------------------------------------------------------------------------------
Files look like:
    Parent_SC3v3_Human_Glioblastoma_S1_L001_R1_001.fastq.gz
    Parent_SC3v3_Human_Glioblastoma_S1_L001_R2_001.fastq.gz

  <sample>_S<n>_L00<lane>_<read>_001.fastq.gz
    S1     = sample number
    L00x   = sequencer lane
    R1/R2  = read 1 / read 2
    I1/I2  = sample index reads (used for demultiplexing; not needed by STARsolo)

What each read contains  /  각 read가 담고 있는 정보:
  R1 = Cell Barcode (CB) + UMI
       - 세포 바코드(어느 세포에서 왔는지) + UMI(고유 분자 식별자)
       - For 10x 3' v3: first 16 bp = CB, next 12 bp = UMI  (total 28 bp)
  R2 = cDNA (the actual transcript sequence that gets aligned to the genome)
       - 실제 유전자(전사체) 서열. 게놈에 정렬되는 read.

=> STARsolo reads BOTH: R1 to know the cell+molecule, R2 to know the gene,
   producing a gene x cell count matrix.
------------------------------------------------------------------------------
EOF

echo "==> [01] Done. FASTQ files are in: ${FASTQ_SUBDIR}"
