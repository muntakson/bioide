#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_pan_t_cells.sh
# Download ONE public 10x Genomics human Pan T cells scRNA-seq FASTQ sample.
# 공개된 10x 사람 Pan T세포 scRNA-seq FASTQ 샘플 하나를 다운로드합니다.
#
# Dataset: "4k Pan T Cells from a Healthy Donor" (10x Genomics, cell-exp 2.1.0)
#   https://www.10xgenomics.com/datasets/4-k-pan-t-cells-from-a-healthy-donor-2-standard-2-1-0
#   - FACS-sorted human pan T cells from a healthy donor's PBMC
#   - 10x Chromium 3' v2 chemistry  (CB=16 bp, UMI=10 bp)  <-- step 2c uses CHEMISTRY=v2
#   - tar archive is ~33 GB
#   - Nearly pure T cells → clusters are T-cell SUBSETS (CD4/CD8, naive/memory,
#     Treg, proliferating) plus a little NK; very different structure from the
#     mixed PBMC/glioblastoma tumor examples.
#
# Why this dataset for another tutorial:
#   * Human → reuses the SAME GRCh38 STAR index built in step 2b (no rebuild).
#   * 3' v2 chemistry → exercises the v2 barcode path (10 bp UMI, 737K whitelist).
#   * Sorted single lineage → a clean lesson in sub-clustering one cell type.
#
# Idempotent: skips download if the FASTQs are already extracted; curl -C - resumes.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/fastq"
mkdir -p "${DATA_DIR}"

# --- Single-instance guard: prevent concurrent duplicate downloads -----------
# 중복 다운로드 방지 잠금장치. Step 1을 두 번 누르면 같은 .tar에 두 curl이 겹쳐
# 대역폭 낭비·아카이브 손상 위험이 있으므로 flock으로 한 번에 하나만 실행합니다.
LOCK_FILE="${DATA_DIR}/.pan_t_cells_download.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "==> 이미 Pan T세포 다운로드가 진행 중입니다 — 이 중복 실행을 건너뜁니다."
  echo "==> A Pan T cells download is already running; skipping this duplicate run."
  exit 1
fi

# --- Verified public download URL (10x Genomics CDN) -------------------------
# 10x 공식 CDN의 검증된 다운로드 URL.
FASTQ_URL="https://cf.10xgenomics.com/samples/cell-exp/2.1.0/t_4k/t_4k_fastqs.tar"
TAR_NAME="t_4k_fastqs.tar"
TAR_PATH="${DATA_DIR}/${TAR_NAME}"

# This tar extracts to a GENERIC top-level "fastqs/" dir (files: t_4k_S1_L00x_R1_001.fastq.gz).
# To avoid colliding with other datasets that also use "fastqs/", extract into a
# dataset-specific parent dir. Final layout: <DATA_DIR>/t_4k/fastqs/t_4k_*.fastq.gz
DEST_PARENT="${DATA_DIR}/t_4k"
FASTQ_SUBDIR="${DEST_PARENT}/fastqs"

echo "==> [01] Downloading 10x human Pan T cells 3' v2 FASTQs into: ${DEST_PARENT}"

# --- 1. Download (resumable) --------------------------------------------------
# curl -L : follow redirects,  -C - : resume a partial download.
if [[ -d "${FASTQ_SUBDIR}" ]] && \
   compgen -G "${FASTQ_SUBDIR}/*_R1_*.fastq.gz" > /dev/null; then
  echo "==> FASTQ files already extracted, skipping download."
else
  echo "==> Downloading ${TAR_NAME} (~33 GB, may take a while)..."
  curl -L -C - -o "${TAR_PATH}" "${FASTQ_URL}"

  echo "==> Extracting tar archive into ${DEST_PARENT} ..."
  mkdir -p "${DEST_PARENT}"
  tar -xvf "${TAR_PATH}" -C "${DEST_PARENT}"
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
    t_4k_S1_L001_R1_001.fastq.gz
    t_4k_S1_L001_R2_001.fastq.gz

  <sample>_S<n>_L00<lane>_<read>_001.fastq.gz
    R1/R2  = read 1 / read 2   (I1 = sample index, not needed by STARsolo)

What each read contains  /  각 read가 담고 있는 정보:
  R1 = Cell Barcode (CB) + UMI
       - For 10x 3' v2: first 16 bp = CB, next 10 bp = UMI  (total 26 bp)
  R2 = cDNA (the transcript sequence aligned to the genome)

=> STARsolo reads BOTH: R1 for the cell+molecule, R2 for the gene.
------------------------------------------------------------------------------
EOF

echo "==> [01] Done. FASTQ files are in: ${FASTQ_SUBDIR}"
