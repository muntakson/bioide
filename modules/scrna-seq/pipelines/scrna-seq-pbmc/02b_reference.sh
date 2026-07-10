#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 02b_reference.sh
# Download the human GRCh38 reference and build a STAR genome index.
# 사람 GRCh38 레퍼런스를 받아 STAR 게놈 인덱스를 생성합니다.
#
# We use the official 10x Genomics reference bundle (refdata-gex-GRCh38-2020-A):
#   - It is THE reference 10x/Cell Ranger use for human 3' data, so it matches
#     this tutorial's 10x PBMC sample (same `chr1` naming, filtered gene set).
#   - It ships genome FASTA + gene GTF together in one tar.
#   - It is served from the fast 10x CDN (cf.10xgenomics.com), unlike the EBI
#     GENCODE mirror which is often throttled to a crawl.
#   (대안: GENCODE FASTA/GTF from ftp.ebi.ac.uk — 동일하지만 미러가 느립니다.)
#
# ┌───────────────────────────────────────────────────────────────────────┐
# │  ONE-TIME COST  /  한 번만 수행하면 됩니다                              │
# │    * Download: the reference tar is ~11 GB.                            │
# │    * RAM: genomeGenerate for the full human genome needs ~30+ GB RAM.  │
# │      (The GB10's large unified memory handles this comfortably.)       │
# │    * Disk: extracted reference ~14 GB, the STAR index itself ~25-30 GB.│
# │    * Time: ~25 min download + ~20-40 min index build.                 │
# │  Once ~/ghbio-tutorial/ref/star_index/ exists, reuse it forever.      │
# └───────────────────────────────────────────────────────────────────────┘
# =============================================================================

REF_DIR="${HOME}/ghbio-tutorial/ref"
INDEX_DIR="${REF_DIR}/star_index"
STAR_BIN="${HOME}/bin/STAR"

mkdir -p "${REF_DIR}" "${INDEX_DIR}"

# --- 10x reference bundle (verified on the 10x CDN) --------------------------
REF_NAME="refdata-gex-GRCh38-2020-A"
REF_TAR_URL="https://cf.10xgenomics.com/supp/cell-exp/${REF_NAME}.tar.gz"
REF_TAR="${REF_DIR}/${REF_NAME}.tar.gz"
REF_ROOT="${REF_DIR}/${REF_NAME}"

FASTA="${REF_ROOT}/fasta/genome.fa"
GTF="${REF_ROOT}/genes/genes.gtf"

echo "==> [02b] Preparing GRCh38 reference (10x ${REF_NAME})"

# --- 0. STAR present? ---------------------------------------------------------
if [[ ! -x "${STAR_BIN}" ]]; then
  echo "ERROR: STAR not found at ${STAR_BIN}. Run 02a_build_starsolo.sh first." >&2
  exit 1
fi

# --- 1. Download + extract the reference bundle (resumable) -------------------
# 레퍼런스 번들 다운로드 및 압축 해제 (이어받기 지원).
if [[ -f "${FASTA}" && -f "${GTF}" ]]; then
  echo "==> Reference already extracted at ${REF_ROOT}"
else
  echo "==> Downloading 10x reference (~11 GB, from fast 10x CDN)..."
  curl -L -C - -o "${REF_TAR}" "${REF_TAR_URL}"
  echo "==> Extracting reference tar..."
  tar -xzf "${REF_TAR}" -C "${REF_DIR}"
  # Keep the tar so a re-run can skip re-downloading; delete manually to save disk.
fi

echo ""
echo "==> Reference file sizes:"
ls -lh "${FASTA}" "${GTF}"

# --- 2. Build the STAR genome index ------------------------------------------
# 이미 인덱스가 있으면 건너뜁니다.
if [[ -f "${INDEX_DIR}/SAindex" ]]; then
  echo ""
  echo "==> STAR index already exists at ${INDEX_DIR}, skipping genomeGenerate."
  echo "==> [02b] Done (index reused)."
  exit 0
fi

THREADS="$(nproc)"

# --sjdbOverhang 100 : good default for reads ~100 bp (10x R2 is ~90-100 bp).
# --genomeSAsparseD 3 : sparser suffix array -> lower RAM & smaller index,
#                       at a small speed cost. Keeps the index compact.
# 스레드 수는 nproc로 자동 설정, sjdbOverhang는 read 길이에 맞춰 100으로 설정합니다.
echo ""
echo "==> Building STAR genome index (needs ~30+ GB RAM; using ${THREADS} threads)..."
echo "    This is the one-time expensive step. Please be patient."

"${STAR_BIN}" \
  --runMode genomeGenerate \
  --runThreadN "${THREADS}" \
  --genomeDir "${INDEX_DIR}" \
  --genomeFastaFiles "${FASTA}" \
  --sjdbGTFfile "${GTF}" \
  --sjdbOverhang 100 \
  --genomeSAsparseD 3

echo ""
echo "==> STAR index contents:"
ls -lh "${INDEX_DIR}"

echo ""
echo "==> [02b] Done. Genome index built at: ${INDEX_DIR}"
echo "    Reuse this index for all future samples — no need to rebuild."
