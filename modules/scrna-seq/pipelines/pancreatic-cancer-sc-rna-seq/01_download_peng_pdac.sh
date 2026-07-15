#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_peng_pdac.sh
# Download the authors' published, already annotated single-cell expression
# object for Peng et al., Cell Research 2019 (pancreatic ductal adenocarcinoma,
# PDAC) — 57,530 cells from 24 primary PDAC tumors + 11 control pancreases.
# 저자가 공개한 주석 완료 단일세포 발현 객체(.h5ad)를 내려받습니다.
#
# Source: Zenodo record 3969339 (BioProject PRJCA001063 / GSA CRA001160),
# reprocessed with the BESCA workflow; the .annotated.h5ad carries the authors'
# cell-type labels (ductal type 1/2, acinar, endocrine, endothelial, fibroblast,
# stellate, macrophage, T cell, B cell) — this is what lets us reproduce the
# paper's cell atlas and the malignant-ductal analysis without raw FASTQ.
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked by actually opening the HDF5 file (h5py), so a truncated
#     download is re-fetched instead of silently breaking step 2.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/pdac-peng2019"
FILE="StdWf1_PRJCA001063_CRC_besca2.annotated.h5ad"
DEST="${DATA_DIR}/${FILE}"
URL="https://zenodo.org/records/3969339/files/${FILE}?download=1"
LOCK="${DATA_DIR}/.download.lock"
PY="${HOME}/ghbio-venv/bin/python"

mkdir -p "${DATA_DIR}"

echo "==> [01] PDAC annotated matrix target: ${DEST}"

# A complete .h5ad opens cleanly with h5py; use that as the integrity check.
ok_h5ad() {
  [[ -f "${DEST}" ]] && [[ -x "${PY}" ]] && \
    "${PY}" - "$1" <<'PY' 2>/dev/null
import sys, h5py
with h5py.File(sys.argv[1], "r") as f:
    assert "X" in f or "raw" in f or "obs" in f
PY
}

if ok_h5ad "${DEST}"; then
  echo "==> Already downloaded and valid — skipping."
  ls -lh "${DEST}"
  exit 0
fi

# Serialize concurrent runs; the second run waits, then finds the file complete.
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting for it to finish…"
  flock 9
  if ok_h5ad "${DEST}"; then
    echo "==> Other run completed the download — skipping."
    ls -lh "${DEST}"; exit 0
  fi
fi

echo "==> Downloading from Zenodo (about 1.7 GB — this can take several minutes)…"
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

echo "==> Verifying HDF5 (.h5ad) integrity…"
if ! ok_h5ad "${DEST}"; then
  echo "ERROR: downloaded file failed the .h5ad integrity check. Delete it and retry:" >&2
  echo "       rm -f '${DEST}'" >&2
  exit 1
fi

echo "==> [01] Done."
ls -lh "${DEST}"
echo "    Next: 2. Figure 1 — cell atlas (02_figure1_atlas.py)."
