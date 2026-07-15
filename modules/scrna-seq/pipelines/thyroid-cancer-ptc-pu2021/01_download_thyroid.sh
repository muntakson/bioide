#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_thyroid.sh
# Download the authors' published single-cell count matrices for Pu et al.,
# Nature Communications 2021 — "Single-cell transcriptomic analysis of the tumor
# ecosystems underlying initiation and progression of papillary thyroid
# carcinoma" (PTC). 158,577 cells from 11 patients: paratumor, primary tumor,
# lymph-node metastasis and RAI-refractory distant metastasis.
# 저자가 GEO에 공개한 단일세포 카운트 행렬(.tar → per-sample MTX)을 내려받습니다.
#
# Source: GEO series GSE184362 — one supplementary tar, GSE184362_RAW.tar (~926 MB),
# containing per-sample 10x triplets (barcodes / features / matrix). We start
# from these RAW COUNT matrices and re-derive the whole analysis with our own
# GPU code — the authors' cell-type labels are NOT distributed on GEO, so the
# validation step (03) compares our result to the paper's PUBLISHED claims.
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked by listing the tar (tar -tf); a truncated download is
#     re-fetched, then extracted once into an unpacked/ dir for step 2.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/ptc-pu2021"
FILE="GSE184362_RAW.tar"
DEST="${DATA_DIR}/${FILE}"
UNPACK="${DATA_DIR}/unpacked"
URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE184nnn/GSE184362/suppl/${FILE}"
LOCK="${DATA_DIR}/.download.lock"

mkdir -p "${DATA_DIR}"

echo "==> [01] PTC count-matrix tar target: ${DEST}"

# A complete tar lists its members without error; use that as the integrity check.
ok_tar() { [[ -f "${DEST}" ]] && tar -tf "${DEST}" >/dev/null 2>&1; }

download() {
  echo "==> Downloading GSE184362_RAW.tar from GEO (~926 MB — a few minutes)…"
  echo "    ${URL}"
  # -C -           resume a partial file
  # --retry        ride out transient network errors
  # --speed-limit/--speed-time  abort if < 1 KB/s for 60 s (a stalled half-open
  #                connection) so the run fails fast instead of hanging forever.
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 5 --retry-delay 3 -C - \
         --speed-limit 1024 --speed-time 60 \
         -o "${DEST}" "${URL}"
  else
    wget -c -t 5 --read-timeout=60 -O "${DEST}" "${URL}"
  fi
}

# Serialize concurrent runs; the second run waits, then finds the file complete.
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting for it to finish…"
  flock 9
fi

if ! ok_tar; then
  download
  echo "==> Verifying tar integrity…"
  if ! ok_tar; then
    echo "ERROR: downloaded file failed the tar integrity check. Delete it and retry:" >&2
    echo "       rm -f '${DEST}'" >&2
    exit 1
  fi
else
  echo "==> Tar already downloaded and valid — skipping fetch."
fi
ls -lh "${DEST}"

# --- Extract once (idempotent): unpack the per-sample matrices for step 2 -----
if [[ -d "${UNPACK}" ]] && compgen -G "${UNPACK}/*.mtx*" >/dev/null 2>&1; then
  echo "==> Already extracted → ${UNPACK} (skipping)."
else
  echo "==> Extracting per-sample matrices → ${UNPACK}"
  mkdir -p "${UNPACK}"
  tar -xf "${DEST}" -C "${UNPACK}"
fi

echo "==> Extracted supplementary files:"
ls -lh "${UNPACK}" | head -20
echo "    …($(find "${UNPACK}" -type f | wc -l) files total)"

echo "==> [01] Done."
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
