#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_melanoma.sh
# Download the authors' published single-cell expression matrix for
# Tirosh et al., Science 2016 (metastatic melanoma), from NCBI GEO GSE72056.
# 저자가 GEO에 공개한 흑색종 단일세포 발현 행렬을 내려받습니다.
#
# The file is the processed log2(TPM/10+1) matrix (~23k genes x 4,645 cells)
# whose header rows carry the authors' own malignant / cell-type labels — this
# is what lets us reproduce the paper's figures without raw FASTQ.
#
# Idempotent: skips the download if a complete file already exists.
# 이미 받아둔 완전한 파일이 있으면 다시 받지 않습니다.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/melanoma-gse72056"
FILE="GSE72056_melanoma_single_cell_revised_v2.txt.gz"
DEST="${DATA_DIR}/${FILE}"
# GEO stores supplementary files under series/GSE72nnn/GSE72056/suppl/
URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE72nnn/GSE72056/suppl/${FILE}"

mkdir -p "${DATA_DIR}"

echo "==> [01] Melanoma matrix target: ${DEST}"

# A complete gzip decompresses cleanly; use that as the integrity check so a
# half-downloaded file is re-fetched instead of silently breaking step 2.
if [[ -f "${DEST}" ]] && gzip -t "${DEST}" 2>/dev/null; then
  echo "==> Already downloaded and valid — skipping."
  ls -lh "${DEST}"
  exit 0
fi

echo "==> Downloading from GEO (about 44 MB)…"
echo "    ${URL}"
# -C - resumes a partial file; --retry rides out transient network hiccups.
if command -v curl >/dev/null 2>&1; then
  curl -fL --retry 5 --retry-delay 3 -C - -o "${DEST}" "${URL}"
else
  wget -c -t 5 -O "${DEST}" "${URL}"
fi

echo "==> Verifying gzip integrity…"
if ! gzip -t "${DEST}" 2>/dev/null; then
  echo "ERROR: downloaded file failed the gzip integrity check. Delete it and retry:" >&2
  echo "       rm -f '${DEST}'" >&2
  exit 1
fi

echo "==> [01] Done."
ls -lh "${DEST}"
echo "    Next: 2. Figure 1 — inferCNV (02_figure1_infercnv.py)."
