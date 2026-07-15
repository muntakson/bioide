#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_neftel.sh
# Download the authors' published Smart-seq2 expression matrix for Neftel et al.,
# Cell 2019 — "An Integrative Model of Cellular States, Plasticity, and Genetics
# for Glioblastoma" (GEO GSE131928). The Smart-seq2 cohort (7,930 cells, 28 IDH-wt
# GBM tumors) is where the four malignant states (AC/MES/NPC/OPC-like) were defined.
# 저자가 공개한 Smart-seq2 발현행렬(TPM)과 세포별 종양 라벨을 내려받습니다.
#
# GEO ships processed dense TPM .tsv.gz matrices (NOT 10x mtx). Author cell-STATE
# labels are NOT on GEO (they live on Broad SCP behind a login), so per the BioIDE
# constitution we re-derive the states ourselves and validate against the paper's
# published claims.
#
# Resilient + idempotent: flock lock, curl -C - resume + stall timeout + retry,
# gzip integrity check.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/gbm-neftel2019"
TPM="GSM3828672_Smartseq2_GBM_IDHwt_processed_TPM.tsv.gz"
META="GSE131928_single_cells_tumor_name_and_adult_or_peidatric.xlsx"
TPM_DEST="${DATA_DIR}/${TPM}"
META_DEST="${DATA_DIR}/${META}"
TPM_URL="https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM3828nnn/GSM3828672/suppl/${TPM}"
META_URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE131nnn/GSE131928/suppl/${META}"
LOCK="${DATA_DIR}/.download.lock"

mkdir -p "${DATA_DIR}"
echo "==> [01] Neftel 2019 Smart-seq2 TPM target: ${TPM_DEST}"

ok_gz() { [[ -f "$1" ]] && gzip -t "$1" 2>/dev/null; }

fetch() {  # url dest
  echo "==> Downloading $(basename "$2") …"
  echo "    $1"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 5 --retry-delay 3 -C - --speed-limit 1024 --speed-time 60 -o "$2" "$1"
  else
    wget -c -t 5 --read-timeout=60 -O "$2" "$1"
  fi
}

exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting…"; flock 9
fi

if ! ok_gz "${TPM_DEST}"; then
  fetch "${TPM_URL}" "${TPM_DEST}"
  ok_gz "${TPM_DEST}" || { echo "ERROR: ${TPM} failed gzip check; delete and retry." >&2; exit 1; }
else
  echo "==> Smart-seq2 TPM already downloaded and valid — skipping."
fi
ls -lh "${TPM_DEST}"

# per-cell tumor-of-origin + adult/pediatric label (used as batch key; NOT a state label)
if [[ ! -f "${META_DEST}" ]]; then
  fetch "${META_URL}" "${META_DEST}" || echo "==> WARNING: metadata xlsx fetch failed (tumor batch key optional)."
else
  echo "==> Tumor-label metadata already present."
fi
[[ -f "${META_DEST}" ]] && ls -lh "${META_DEST}" || true

echo "==> [01] Done. Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
