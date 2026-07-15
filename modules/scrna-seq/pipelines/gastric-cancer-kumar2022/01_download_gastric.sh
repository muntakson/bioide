#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_gastric.sh
# Download the authors' published single-cell count matrices for Kumar et al.,
# Cancer Discovery 2022 — "Single-Cell Atlas of Lineage States, Tumor
# Microenvironment, and Subtype-Specific Expression Programs in Gastric Cancer".
# >200,000 cells from 48 samples across 31 patients (multiple stages/subtypes).
# 저자가 GEO에 공개한 단일세포 카운트 행렬(.tar → per-sample CSV)을 내려받습니다.
#
# Source: GEO series GSE183904 — one supplementary tar, GSE183904_RAW.tar (~329 MB),
# a TAR of per-sample CSV count matrices (genes × cells). We start from these RAW
# COUNT matrices and re-derive the whole analysis with our own GPU code — the
# authors' cell-type labels are NOT distributed on GEO (raw sequencing was withheld
# for patient privacy; only processed count CSVs are shared), so the validation step
# (03) compares our result to the paper's PUBLISHED claims.
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked by listing the tar (tar -tf); a truncated download is
#     re-fetched, then extracted once into an unpacked/ dir for step 2.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/gastric-kumar2022"
FILE="GSE183904_RAW.tar"
DEST="${DATA_DIR}/${FILE}"
UNPACK="${DATA_DIR}/unpacked"
URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE183nnn/GSE183904/suppl/${FILE}"
LOCK="${DATA_DIR}/.download.lock"

mkdir -p "${DATA_DIR}"

echo "==> [01] Gastric count-matrix tar target: ${DEST}"

# A complete tar lists its members without error; use that as the integrity check.
ok_tar() { [[ -f "${DEST}" ]] && tar -tf "${DEST}" >/dev/null 2>&1; }

download() {
  echo "==> Downloading GSE183904_RAW.tar from GEO (~329 MB — a few minutes)…"
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

# --- Extract once (idempotent): unpack the per-sample CSV matrices for step 2 --
if [[ -d "${UNPACK}" ]] && compgen -G "${UNPACK}/*.csv*" >/dev/null 2>&1; then
  echo "==> Already extracted → ${UNPACK} (skipping)."
else
  echo "==> Extracting per-sample CSV matrices → ${UNPACK}"
  mkdir -p "${UNPACK}"
  tar -xf "${DEST}" -C "${UNPACK}"
fi

echo "==> Extracted supplementary files:"
ls -lh "${UNPACK}" | head -20
echo "    …($(find "${UNPACK}" -type f | wc -l) files total)"

echo "==> [01] Done."
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
