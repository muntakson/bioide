#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_liver.sh
# Download the authors' published single-cell count matrices for Ma et al.,
# Cancer Cell 2019 — "Tumor Cell Biodiversity Drives Microenvironmental
# Reprogramming in Liver Cancer". ~9,900 cells from 19 liver-cancer patients
# (HCC + iCCA), profiled with 10x Genomics in two batches (Set1, Set2).
# 저자가 GEO(GSE125449)에 공개한 10x 카운트 행렬을 내려받습니다.
#
# Source: GEO series GSE125449 — per-Set 10x triplets (matrix.mtx / genes.tsv /
# barcodes.tsv, gzip) plus a per-cell annotation table (samples.txt: Sample,
# Cell Barcode, Type). Total ~46 MB. We start from the RAW UMI count matrices and
# re-derive the whole analysis with our own GPU code; the authors' cell-type
# labels in samples.txt (Type) are held back and used ONLY by the validation step
# (03) — never as an analysis input (헌장 제1조).
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same files in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - each gzip member is integrity-checked (gzip -t); a truncated file is re-fetched.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/liver-ma2019"
BASE="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE125nnn/GSE125449/suppl"
LOCK="${DATA_DIR}/.download.lock"

mkdir -p "${DATA_DIR}"
echo "==> [01] Liver 10x count-matrix target dir: ${DATA_DIR}"

# GEO file  ->  local (per-Set subdir, standardised 10x names)
#   GSE125449_Set1_matrix.mtx.gz   -> Set1/matrix.mtx.gz     (etc.)
declare -A FILES=(
  ["GSE125449_Set1_matrix.mtx.gz"]="Set1/matrix.mtx.gz"
  ["GSE125449_Set1_genes.tsv.gz"]="Set1/genes.tsv.gz"
  ["GSE125449_Set1_barcodes.tsv.gz"]="Set1/barcodes.tsv.gz"
  ["GSE125449_Set1_samples.txt.gz"]="Set1/samples.txt.gz"
  ["GSE125449_Set2_matrix.mtx.gz"]="Set2/matrix.mtx.gz"
  ["GSE125449_Set2_genes.tsv.gz"]="Set2/genes.tsv.gz"
  ["GSE125449_Set2_barcodes.tsv.gz"]="Set2/barcodes.tsv.gz"
  ["GSE125449_Set2_samples.txt.gz"]="Set2/samples.txt.gz"
)

ok_gz() { [[ -f "$1" ]] && gzip -t "$1" >/dev/null 2>&1; }

fetch() {
  local url="$1" dest="$2"
  echo "==> Downloading $(basename "$dest") …"
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

for remote in "${!FILES[@]}"; do
  dest="${DATA_DIR}/${FILES[$remote]}"
  mkdir -p "$(dirname "${dest}")"
  if ok_gz "${dest}"; then
    echo "==> $(basename "${dest}") already present and valid — skipping."
    continue
  fi
  fetch "${BASE}/${remote}" "${dest}"
  if ! ok_gz "${dest}"; then
    echo "ERROR: ${dest} failed the gzip integrity check. Delete it and retry:" >&2
    echo "       rm -f '${dest}'" >&2
    exit 1
  fi
done

echo "==> Downloaded files:"
find "${DATA_DIR}" -type f \( -name '*.gz' \) | sort | while read -r f; do
  printf '    %8s  %s\n' "$(du -h "$f" | cut -f1)" "${f#${DATA_DIR}/}"
done

# quick sanity summary
for S in Set1 Set2; do
  nc=$(zcat "${DATA_DIR}/${S}/barcodes.tsv.gz" 2>/dev/null | wc -l || echo 0)
  ng=$(zcat "${DATA_DIR}/${S}/genes.tsv.gz" 2>/dev/null | wc -l || echo 0)
  echo "    ${S}: ${nc} cells × ${ng} genes"
done

echo "==> [01] Done."
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
