#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_hnscc.sh
# Download the authors' published single-cell data for Choi et al., Nature
# Communications 2023 — "Single-cell transcriptome profiling of the stepwise
# progression of head and neck cancer". 54,239 cells from 37 specimens / 23
# patients across four stages: normal mucosa (NL) → leukoplakia (LP, precancer)
# → carcinoma (CA) → lymph-node metastasis (LN).
# 저자가 GEO에 공개한 단일세포 발현 행렬 + 바코드 메타데이터를 내려받습니다.
#
# Source: GEO series GSE181919 — two supplementary files:
#   GSE181919_UMI_counts.txt.gz      (~122 MB) dense TSV UMI matrix, genes × cells
#   GSE181919_Barcode_metadata.txt.gz (~0.3 MB) per-barcode metadata
#     (patient.id, sample.id, tissue.type = STAGE, subsite, hpv, cell.type)
# We start from the RAW UMI counts and re-derive the whole analysis with our own
# GPU code. The authors' `cell.type` labels ship in the metadata but are consumed
# ONLY by the validation step (03) — never as an analysis input (헌장 제1·2조).
# The disease STAGE (tissue.type) is experimental design, kept as a covariate.
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked with `gzip -t`; a truncated download is re-fetched.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/hnscc-choi2023"
BASE_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE181nnn/GSE181919/suppl"
LOCK="${DATA_DIR}/.download.lock"

# file → remote name (destination keeps the same basename)
FILES=(
  "GSE181919_UMI_counts.txt.gz"
  "GSE181919_Barcode_metadata.txt.gz"
)

mkdir -p "${DATA_DIR}"
echo "==> [01] Head&neck (Choi 2023, GSE181919) data target: ${DATA_DIR}"

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
