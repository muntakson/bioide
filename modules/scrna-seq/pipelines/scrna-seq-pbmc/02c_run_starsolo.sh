#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 02c_run_starsolo.sh
# Run STARsolo on the downloaded 10x FASTQs -> gene-barcode count matrix.
# 다운로드한 10x FASTQ에 STARsolo를 실행해 유전자 x 세포 카운트 행렬을 만듭니다.
#
# Handles 10x chemistry correctly:
#   * v3 (this dataset): CB length 16, UMI length 12, whitelist 3M-february-2018.txt
#   * v2:                CB length 16, UMI length 10, whitelist 737K-august-2016.txt
# 이 데이터셋은 v3 chemistry입니다 (CB=16, UMI=12).
# =============================================================================

# ---- Configuration ----------------------------------------------------------
CHEMISTRY="v3"                                    # "v3" or "v2"

TUT="${HOME}/ghbio-tutorial"
STAR_BIN="${HOME}/bin/STAR"
INDEX_DIR="${TUT}/ref/star_index"
FASTQ_DIR="${TUT}/data/fastq/pbmc_1k_v3_fastqs"
WL_DIR="${TUT}/ref/whitelist"
# Results are first-class project files. GHBIO_RESULTS is injected by the extension and
# points at the project (~/ghbio-workspace/projects/<tutorial>/results). Falls back to the
# legacy path (a symlink to the project) for manual runs.
RESULTS="${GHBIO_RESULTS:-${TUT}/results}"
OUT_DIR="${RESULTS}/starsolo"

mkdir -p "${WL_DIR}" "${OUT_DIR}"

echo "==> [02c] Running STARsolo (${CHEMISTRY} chemistry)"

# --- 0. Preconditions ---------------------------------------------------------
if [[ ! -x "${STAR_BIN}" ]]; then
  echo "ERROR: STAR not found at ${STAR_BIN}. Run 02a first." >&2; exit 1
fi
if [[ ! -f "${INDEX_DIR}/SAindex" ]]; then
  echo "ERROR: STAR index not found in ${INDEX_DIR}. Run 02b first." >&2; exit 1
fi

# --- 0b. Idempotency: skip if the count matrix already exists -----------------
# 이미 count matrix가 있으면 재정렬(10~30분)을 건너뜁니다. 다시 하려면 FORCE=1.
FILTERED_MTX="${OUT_DIR}/Solo.out/Gene/filtered/matrix.mtx"
if [[ -f "${FILTERED_MTX}" && "${FORCE:-0}" != "1" ]]; then
  echo "==> Count matrix already exists — skipping STARsolo (no re-alignment)."
  echo "    ${FILTERED_MTX}"
  echo "    Re-run from scratch with:  FORCE=1 bash 02c_run_starsolo.sh"
  echo "==> [02c] Done (reused)."
  exit 0
fi

# --- 1. Chemistry-specific parameters + whitelist ----------------------------
# chemistry에 따라 CB/UMI 길이와 whitelist 파일을 선택합니다.
if [[ "${CHEMISTRY}" == "v3" ]]; then
  CB_LEN=16
  UMI_LEN=12
  WL_FILE="${WL_DIR}/3M-february-2018.txt"
  # Primary: Teichlab scg_lib_structs (stable, well-known single-cell library
  # structure reference). Mirror: 10x cellranger repo (path changes over time).
  WL_PRIMARY="https://teichlab.github.io/scg_lib_structs/data/10X-Genomics/3M-february-2018.txt.gz"
  WL_MIRROR="https://github.com/10XGenomics/cellranger/raw/master/lib/python/cellranger/barcodes/3M-february-2018.txt.gz"
  WL_IS_GZ=1
elif [[ "${CHEMISTRY}" == "v2" ]]; then
  CB_LEN=16
  UMI_LEN=10
  WL_FILE="${WL_DIR}/737K-august-2016.txt"
  WL_PRIMARY="https://github.com/10XGenomics/cellranger/raw/master/lib/python/cellranger/barcodes/737K-august-2016.txt"
  WL_MIRROR=""     # plain text; primary is usually reliable
  WL_IS_GZ=0
else
  echo "ERROR: unknown CHEMISTRY='${CHEMISTRY}' (use 'v3' or 'v2')." >&2; exit 1
fi

# --- 2. Download the barcode whitelist (idempotent, with fallback) -----------
# 바코드 whitelist 다운로드 (이미 있으면 건너뜀, 미러 fallback 포함).
if [[ ! -f "${WL_FILE}" ]]; then
  echo "==> Downloading ${CHEMISTRY} barcode whitelist..."
  TMP="${WL_FILE}.download"
  if [[ "${WL_IS_GZ}" -eq 1 ]]; then
    TMP="${TMP}.gz"
    if ! curl -L -C - -f -o "${TMP}" "${WL_PRIMARY}"; then
      echo "==> Primary source failed, trying mirror..."
      curl -L -C - -f -o "${TMP}" "${WL_MIRROR}"
    fi
    echo "==> Decompressing whitelist..."
    gunzip -c "${TMP}" > "${WL_FILE}"
    rm -f "${TMP}"
  else
    curl -L -C - -f -o "${WL_FILE}" "${WL_PRIMARY}"
  fi
else
  echo "==> Whitelist already present: ${WL_FILE}"
fi
echo "==> Whitelist barcode count: $(wc -l < "${WL_FILE}")"

# --- 3. Assemble comma-separated R1 and R2 file lists ------------------------
# STARsolo expects: --readFilesIn <cDNA=R2 list> <barcode=R1 list>
# (즉 R2가 먼저, R1이 나중입니다. lane별 파일을 콤마로 연결합니다.)
R1_LIST="$(ls "${FASTQ_DIR}"/*_R1_*.fastq.gz | sort | paste -sd, -)"
R2_LIST="$(ls "${FASTQ_DIR}"/*_R2_*.fastq.gz | sort | paste -sd, -)"

if [[ -z "${R1_LIST}" || -z "${R2_LIST}" ]]; then
  echo "ERROR: Could not find R1/R2 FASTQ files in ${FASTQ_DIR}." >&2; exit 1
fi
echo "==> R1 (barcode+UMI): ${R1_LIST}"
echo "==> R2 (cDNA):        ${R2_LIST}"

THREADS="$(nproc)"

# --- 4. Run STARsolo ----------------------------------------------------------
# Key options / 주요 옵션:
#   --soloType CB_UMI_Simple : standard 10x droplet layout (one CB + one UMI in R1)
#   --soloCBwhitelist        : the barcode whitelist we just downloaded
#   --soloCBstart/CBlen/UMIstart/UMIlen : 10x layout (CB then UMI in R1)
#   --soloFeatures Gene      : produce a gene x cell matrix
#   --soloCellFilter EmptyDrops_CR : Cell Ranger-like cell calling (filtered matrix)
#   --readFilesCommand zcat  : inputs are gzipped
#   STARsolo writes BOTH a 'raw' (all barcodes) and 'filtered' (real cells) matrix.
echo ""
echo "==> Launching STARsolo with ${THREADS} threads..."
cd "${OUT_DIR}"

# STAR refuses to start if a leftover temp dir from an interrupted run exists.
# 중단된 이전 실행이 남긴 임시 디렉터리를 제거합니다(있으면 STAR가 실패함).
rm -rf "${OUT_DIR}/_STARtmp"

"${STAR_BIN}" \
  --runMode alignReads \
  --runThreadN "${THREADS}" \
  --genomeDir "${INDEX_DIR}" \
  --readFilesIn "${R2_LIST}" "${R1_LIST}" \
  --readFilesCommand zcat \
  --soloType CB_UMI_Simple \
  --soloCBwhitelist "${WL_FILE}" \
  --soloCBstart 1 --soloCBlen "${CB_LEN}" \
  --soloUMIstart $((CB_LEN + 1)) --soloUMIlen "${UMI_LEN}" \
  --soloFeatures Gene \
  --soloCellFilter EmptyDrops_CR \
  --outSAMtype BAM Unsorted \
  --outFileNamePrefix "${OUT_DIR}/"

# --- 5. Explain the output ----------------------------------------------------
cat <<EOF

------------------------------------------------------------------------------
STARsolo output  /  STARsolo 출력물
------------------------------------------------------------------------------
Main result directory:
    ${OUT_DIR}/Solo.out/Gene/

  Solo.out/Gene/Summary.csv     : mapping + cell-calling summary stats
  Solo.out/Gene/raw/            : ALL barcodes (mostly empty droplets)
  Solo.out/Gene/filtered/       : only barcodes called as real cells  <-- use this

The 'filtered/' matrix is what Scanpy loads. It contains 3 files (10x MEX format):
  matrix.mtx      : sparse gene x cell count matrix (MatrixMarket format)
                    -> 값 = 각 세포에서 각 유전자의 UMI 카운트
  barcodes.tsv    : one cell barcode per column of the matrix (세포 = 열)
  features.tsv    : one gene per row (gene_id, gene_name, "Gene Expression") (유전자 = 행)

Step 3 (03_scanpy_qc.py) reads:
    ${OUT_DIR}/Solo.out/Gene/filtered/
via scanpy.read_10x_mtx().
------------------------------------------------------------------------------
EOF

echo "==> [02c] Done. Filtered matrix: ${OUT_DIR}/Solo.out/Gene/filtered/"
