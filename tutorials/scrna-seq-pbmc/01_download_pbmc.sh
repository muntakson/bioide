#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_pbmc.sh
# Download ONE small public 10x Genomics PBMC scRNA-seq FASTQ sample.
# 공개된 작은 10x PBMC scRNA-seq FASTQ 샘플 하나를 다운로드합니다.
#
# Dataset: "1k PBMCs from a Healthy Donor (v3 chemistry)"
#   https://www.10xgenomics.com/datasets/1-k-pbm-cs-from-a-healthy-donor-v-3-chemistry-3-standard-3-0-0
#   - ~1,000 peripheral blood mononuclear cells
#   - 10x Chromium 3' v3 chemistry  (CB=16 bp, UMI=12 bp)  <-- important for step 2c
#   - tar archive is ~5 GB
#
# Idempotent: skips download if the tar already exists; curl -C - resumes.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/fastq"
mkdir -p "${DATA_DIR}"

# --- Verified public download URL (10x Genomics CDN) -------------------------
# 10x 공식 CDN의 검증된 다운로드 URL.
FASTQ_URL="https://cf.10xgenomics.com/samples/cell-exp/3.0.0/pbmc_1k_v3/pbmc_1k_v3_fastqs.tar"
TAR_NAME="pbmc_1k_v3_fastqs.tar"
TAR_PATH="${DATA_DIR}/${TAR_NAME}"

echo "==> [01] Downloading 10x 1k PBMC v3 FASTQs into: ${DATA_DIR}"

# --- 1. Download (resumable) --------------------------------------------------
# curl -L : follow redirects,  -C - : resume a partial download.
# 이어받기(-C -)와 리다이렉트 추적(-L)을 사용해 다운로드합니다.
if [[ -d "${DATA_DIR}/pbmc_1k_v3_fastqs" ]] && \
   compgen -G "${DATA_DIR}/pbmc_1k_v3_fastqs/*_R1_*.fastq.gz" > /dev/null; then
  echo "==> FASTQ files already extracted, skipping download."
else
  echo "==> Downloading ${TAR_NAME} (~5 GB, may take several minutes)..."
  curl -L -C - -o "${TAR_PATH}" "${FASTQ_URL}"

  echo "==> Extracting tar archive..."
  tar -xvf "${TAR_PATH}" -C "${DATA_DIR}"
  # Keep the tar so a re-run can skip re-downloading; delete manually to save disk.
fi

# --- 2. Locate the extracted FASTQ directory ---------------------------------
FASTQ_SUBDIR="${DATA_DIR}/pbmc_1k_v3_fastqs"

echo ""
echo "==> Downloaded / extracted FASTQ files and sizes:"
ls -lh "${FASTQ_SUBDIR}"/*.fastq.gz

# --- 3. Explain the 10x FASTQ naming convention ------------------------------
cat <<'EOF'

------------------------------------------------------------------------------
10x FASTQ naming convention  /  10x FASTQ 파일 이름 규칙
------------------------------------------------------------------------------
Files look like:
    pbmc_1k_v3_S1_L001_R1_001.fastq.gz
    pbmc_1k_v3_S1_L001_R2_001.fastq.gz
    pbmc_1k_v3_S1_L001_I1_001.fastq.gz    (index read, optional)

  <sample>_S<n>_L00<lane>_<read>_001.fastq.gz
    S1     = sample number
    L001   = sequencer lane (this dataset has L001 and L002)
    R1/R2  = read 1 / read 2
    I1     = i7 sample index (used for demultiplexing; not needed by STARsolo)

What each read contains  /  각 read가 담고 있는 정보:
  R1 = Cell Barcode (CB) + UMI
       - 세포 바코드(어느 세포에서 왔는지) + UMI(고유 분자 식별자)
       - For 10x 3' v3: first 16 bp = CB, next 12 bp = UMI  (total 28 bp)
  R2 = cDNA (the actual transcript sequence that gets aligned to the genome)
       - 실제 유전자(전사체) 서열. 게놈에 정렬되는 read.

=> STARsolo reads BOTH: it uses R1 to know the cell+molecule, and R2 to know
   the gene. The result is a gene x cell count matrix.
   (STARsolo 명령에서는 R2(cDNA)를 첫 번째, R1(barcode)을 두 번째 인자로 전달합니다.)
------------------------------------------------------------------------------
EOF

echo "==> [01] Done. FASTQ files are in: ${FASTQ_SUBDIR}"
