#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_hcc.sh
# Download the authors' published single-cell data for Lu et al., Nature
# Communications 2022 — "A single-cell atlas of the multicellular ecosystem of
# primary and metastatic hepatocellular carcinoma". 71,915 cells from 10 HCC
# patients / 21 specimens across four tissue sites:
#   Normal liver → Tumor (primary HCC) → PVTT (portal-vein tumour thrombus)
#   → Lymph (metastatic lymph node).
# 저자가 GEO에 공개한 dense UMI 발현 행렬 + 세포 주석(annotation)을 내려받습니다.
#
# Source: GEO series GSE149614 — two supplementary files we use:
#   GSE149614_HCC.scRNAseq.S71915.count.txt.gz    (~158 MB) dense TSV UMI matrix
#                                                  (genes × cells; header = cell barcodes)
#   GSE149614_HCC.metadata.updated.txt.gz          (~0.5 MB) per-cell metadata
#     (Cell, sample, res.3, site = tissue class, patient, stage, virus, celltype)
# We start from the RAW UMI counts and re-derive the whole analysis with our own
# GPU code. The authors' `celltype` labels ship in the metadata but are consumed
# ONLY by the validation step (03) — never as an analysis input (헌장 제1·2조).
# The tissue site (Tumor/Normal/PVTT/Lymph) is experimental design, kept as a
# covariate to test the paper's claims about intratumoral TLS and the
# normal→tumour→metastasis axis. (The 1.2 GB normalized matrix is NOT needed —
# we normalise the raw counts ourselves.)
#
# Resilient + idempotent:
#   - flock guards against a second run downloading the same file in parallel,
#   - curl gets -C - (resume) plus --speed-limit/--speed-time (stall timeout) and
#     --retry, so a half-open connection can't hang forever and block the pipeline,
#   - integrity is checked with `gzip -t`; a truncated download is re-fetched.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/hcc-lu2022"
BASE_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE149nnn/GSE149614/suppl"
LOCK="${DATA_DIR}/.download.lock"

FILES=(
  "GSE149614_HCC.scRNAseq.S71915.count.txt.gz"
  "GSE149614_HCC.metadata.updated.txt.gz"
)

mkdir -p "${DATA_DIR}"
echo "==> [01] HCC ecosystem (Lu 2022, GSE149614) data target: ${DATA_DIR}"

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
