#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_nsclc.sh
# Obtain a public human NSCLC (non-small cell lung cancer) 10x scRNA-seq sample
# as FASTQ, by downloading the author-submitted Cell Ranger BAM and converting it
# back to original R1/R2 FASTQs.
#
# Dataset: GSE117570 / SRA SRR7586084 — "P1_Tumor" (patient 1 lung tumor)
#   https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE117570
#   - Human NSCLC dissociated tumor, 10x Chromium 3' Gene Expression
#   - Open access. ENA only exposes the cDNA read as FASTQ, but the *submitted*
#     file is the 10x `possorted_genome_bam.bam` (~8.6 GB), which keeps the raw
#     cell barcode (CR) + UMI (UR) in tags — so we losslessly reconstruct R1/R2.
#
# Why BAM->FASTQ:  Cell Ranger can't run on this aarch64 box (x86-64 only), and
# most open human tumor 10x data is deposited as BAM, not paired FASTQ. `bamtofastq`
# needs a Rust/htslib toolchain we can't install here, so we use pysam (bundled
# htslib, pip-installable) — see bam2fastq.py. STARsolo re-corrects barcodes against
# the whitelist, so the raw CR/UR reads are exactly what it needs.
#
# Idempotent: skips if FASTQs already exist; curl -C - resumes the BAM download.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/fastq"
mkdir -p "${DATA_DIR}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${HOME}/ghbio-venv/bin/python"

# --- Single-instance guard ----------------------------------------------------
LOCK_FILE="${DATA_DIR}/.nsclc_download.lock"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "==> 이미 NSCLC 다운로드/변환이 진행 중입니다 — 중복 실행을 건너뜁니다."
  echo "==> An NSCLC download/convert is already running; skipping this duplicate run."
  exit 1
fi

# --- Verified public download URL (ENA submitted file: 10x Cell Ranger BAM) ---
BAM_URL="https://ftp.sra.ebi.ac.uk/vol1/run/SRR758/SRR7586084/P1_Tumor_possorted_genome_bam.bam.1"
BAM_PATH="${DATA_DIR}/nsclc_P1_Tumor.bam"
OUT_DIR="${DATA_DIR}/nsclc_p1_tumor"
PREFIX="${OUT_DIR}/nsclc_p1_tumor_S1_L001"   # -> *_R1_001.fastq.gz / *_R2_001.fastq.gz
mkdir -p "${OUT_DIR}"

echo "==> [01] NSCLC sample: download 10x BAM (~8.6 GB) + convert to FASTQ"

# --- 0. Ensure pysam (bundled htslib; no system packages needed) -------------
if ! "${PY}" -c "import pysam" 2>/dev/null; then
  echo "==> Installing pysam into the venv..."
  "${HOME}/ghbio-venv/bin/pip" install --quiet pysam
fi

# --- 1. Already converted? skip everything -----------------------------------
if compgen -G "${OUT_DIR}/*_R1_*.fastq.gz" > /dev/null; then
  echo "==> FASTQ already reconstructed, skipping download+convert."
  ls -lh "${OUT_DIR}"/*.fastq.gz
  echo "==> [01] Done (reused): ${OUT_DIR}"
  exit 0
fi

# --- 2. Download the BAM (resumable) -----------------------------------------
if [[ ! -s "${BAM_PATH}" ]]; then
  echo "==> Downloading Cell Ranger BAM (~8.6 GB, may take a while)..."
fi
curl -L -C - -o "${BAM_PATH}" "${BAM_URL}"

# --- 3. Reconstruct original FASTQs from the BAM -----------------------------
echo "==> Converting BAM -> FASTQ (R1 = barcode+UMI, R2 = cDNA) via pysam..."
"${PY}" "${HERE}/bam2fastq.py" --bam "${BAM_PATH}" --out-prefix "${PREFIX}"

echo ""
echo "==> Reconstructed FASTQ files:"
ls -lh "${OUT_DIR}"/*.fastq.gz

# Optionally free ~8.6 GB by removing the BAM once FASTQs exist:
#   rm -f "${BAM_PATH}"

cat <<'EOF'

------------------------------------------------------------------------------
BAM -> FASTQ 재구성  /  Reconstructing FASTQ from a 10x BAM
------------------------------------------------------------------------------
공개 사람 종양 10x 데이터는 대개 원본 FASTQ가 아니라 Cell Ranger BAM으로 올라옵니다.
이 BAM에는 각 read의 원본 <b>세포 바코드(CR)</b>와 <b>UMI(UR)</b>가 태그로 들어 있어,
  R1 = CR + UR   (바코드 + UMI)
  R2 = cDNA 서열 (역방향 매핑이면 원본으로 되돌림)
로 손실 없이 원래 FASTQ를 복원합니다. 이후 STARsolo가 whitelist로 바코드를 다시 보정합니다.
------------------------------------------------------------------------------
EOF

echo "==> [01] Done. FASTQ in: ${OUT_DIR}"
