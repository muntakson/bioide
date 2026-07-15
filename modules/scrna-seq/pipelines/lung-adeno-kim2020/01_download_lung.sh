#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_lung.sh
# Download the authors' published single-cell data for Kim et al., Nature
# Communications 2020 — "Single-cell RNA sequencing demonstrates the molecular
# and cellular reprogramming of metastatic lung adenocarcinoma". 208,506 cells
# from 44 patients / 58 specimens across the normal→tumour→metastasis axis:
# normal lung (nLung) → primary tumour (tLung / tL/B) → normal & metastatic
# lymph node (nLN / mLN) → brain metastasis (mBrain) → pleural effusion (PE).
# 저자가 GEO에 공개한 dense UMI 발현 행렬 + 세포 주석(annotation)을 내려받습니다.
#
# Source: GEO series GSE131907 — two supplementary files:
#   GSE131907_Lung_Cancer_raw_UMI_matrix.txt.gz   (~390 MB) dense TSV UMI matrix (genes × cells)
#   GSE131907_Lung_Cancer_cell_annotation.txt.gz  (~1.8 MB) per-cell metadata
#     (Barcode, Sample, Sample_Origin = tissue class, Cell_type, Cell_subtype)
# We start from the RAW UMI counts and re-derive the whole analysis with our own
# GPU code. The authors' Cell_type/Cell_subtype labels ship in the annotation but
# are consumed ONLY by the validation step (03) — never as an analysis input
# (헌장 제1·2조). The tissue origin (Sample_Origin) is experimental design, kept
# as a covariate. (The 2.9 GB normalized log2TPM matrix is NOT needed — we
# normalise the raw counts ourselves.)
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked with `gzip -t`; a truncated download is re-fetched.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/lung-kim2020"
BASE_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE131nnn/GSE131907/suppl"
LOCK="${DATA_DIR}/.download.lock"

FILES=(
  "GSE131907_Lung_Cancer_raw_UMI_matrix.txt.gz"
  "GSE131907_Lung_Cancer_cell_annotation.txt.gz"
)

mkdir -p "${DATA_DIR}"
echo "==> [01] Lung adeno (Kim 2020, GSE131907) data target: ${DATA_DIR}"

ok_gz() { [[ -f "$1" ]] && gzip -t "$1" >/dev/null 2>&1; }

fetch() {
  local url="$1" dest="$2"
  echo "==> Downloading $(basename "$dest")"
  echo "    ${url}"
  # -C -           resume a partial file
  # --retry        ride out transient network errors
  # --speed-limit/--speed-time  abort if < 1 KB/s for 60 s (a stalled half-open
  #                connection) so the run fails fast instead of hanging forever.
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 5 --retry-delay 3 -C - \
         --speed-limit 1024 --speed-time 60 \
         -o "${dest}" "${url}"
  else
    wget -c -t 5 --read-timeout=60 -O "${dest}" "${url}"
  fi
}

# Serialize concurrent runs; the second run waits, then finds the files complete.
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting for it to finish…"
  flock 9
fi

for f in "${FILES[@]}"; do
  DEST="${DATA_DIR}/${f}"
  if ok_gz "${DEST}"; then
    echo "==> ${f} already downloaded and valid — skipping."
  else
    fetch "${BASE_URL}/${f}" "${DEST}"
    echo "==> Verifying gzip integrity of ${f}…"
    if ! ok_gz "${DEST}"; then
      echo "ERROR: ${f} failed the gzip integrity check. Delete it and retry:" >&2
      echo "       rm -f '${DEST}'" >&2
      exit 1
    fi
  fi
  ls -lh "${DEST}"
done

echo "==> [01] Done. Both files present under ${DATA_DIR}."
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
