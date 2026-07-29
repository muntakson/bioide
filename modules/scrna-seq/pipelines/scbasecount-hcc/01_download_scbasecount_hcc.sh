#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_scbasecount_hcc.sh  (Arc Virtual Cell Atlas · scBaseCount → HCC)
#
# NO FASTQ ALIGNMENT. scBaseCount already re-quantified every SRA sample uniformly
# with STARsolo (scRecounter), so this step just SELECTS the human hepatocellular
# carcinoma (HCC) samples and downloads their per-sample h5ad files:
#   1. 01_query_metadata.py downloads the scBaseCount metadata table, filters to
#      human HCC (disease_ontology_term_id MONDO:0007256 / "hepatocellular"), and
#      writes hcc_samples.csv (srx, gs_path, tissue, disease, confidence).
#   2. we gsutil-cp each selected sample's h5ad into the data dir.
#
# Requester Pays: the atlas is in gs://arc-institute-virtual-cell-atlas, billed to
# YOUR GCP project (2 TB/month free). Project resolved from $GHBIO_GCP_PROJECT,
# ~/.config/ghbio/gcp.json, or gcloud (see 00_setup_env.sh).
#
# Resilient + idempotent:
#   - flock guards against a second parallel run,
#   - gsutil cp is skipped for h5ads already present with matching size,
#   - MAX_SAMPLES caps the draft download; raise it (or 0) for the full set.
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/scbasecount-hcc"
H5AD_DIR="${DATA_DIR}/h5ad"
LOCK="${DATA_DIR}/.download.lock"
PY="${HOME}/ghbio-venv/bin/python"
HERE="$(cd "$(dirname "$0")" && pwd)"
MAX_SAMPLES="${MAX_SAMPLES:-40}"
MIN_CONF="${MIN_CONF:-medium}"

mkdir -p "${H5AD_DIR}"
echo "==> [01] scBaseCount HCC download → ${DATA_DIR}  (max ${MAX_SAMPLES} samples, conf ≥ ${MIN_CONF})"
[[ -x "$PY" ]] || { echo "ERROR: venv python missing at $PY (run 00_setup_env.sh)." >&2; exit 1; }
command -v gsutil >/dev/null 2>&1 || { echo "ERROR: gsutil not on PATH (run 00_setup_env.sh for install steps)." >&2; exit 1; }

# Resolve billing project for the Requester-Pays gsutil cp calls.
PROJECT="${GHBIO_GCP_PROJECT:-}"
if [[ -z "${PROJECT}" && -f "${HOME}/.config/ghbio/gcp.json" ]]; then
  PROJECT="$("$PY" -c "import json;print(json.load(open('${HOME}/.config/ghbio/gcp.json')).get('project',''))" 2>/dev/null || true)"
fi
[[ -z "${PROJECT}" ]] && PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no GCP billing project. export GHBIO_GCP_PROJECT=... (see 00_setup_env.sh)." >&2
  exit 2
fi
echo "==> billing project: ${PROJECT}"

# Serialize concurrent runs.
exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting…"
  flock 9
fi

# 1) select HCC samples (writes hcc_samples.csv) --------------------------------
SAMPLES="${DATA_DIR}/hcc_samples.csv"
if [[ -s "${SAMPLES}" && "${FORCE:-0}" != "1" ]]; then
  echo "==> Reusing existing sample list ${SAMPLES} (FORCE=1 to re-query)."
else
  "$PY" "${HERE}/01_query_metadata.py" \
    --data-dir "${DATA_DIR}" --min-confidence "${MIN_CONF}" --max-samples "${MAX_SAMPLES}"
fi
[[ -s "${SAMPLES}" ]] || { echo "ERROR: ${SAMPLES} not produced." >&2; exit 3; }

# 2) download each selected sample's h5ad ---------------------------------------
# hcc_samples.csv columns: srx,gs_path,organism,tissue,disease,confidence
n_ok=0 n_skip=0 n_fail=0
while IFS=, read -r srx gs_path _rest; do
  [[ "${srx}" == "srx" ]] && continue          # header
  [[ -z "${gs_path}" ]] && continue
  dest="${H5AD_DIR}/${srx}.h5ad"
  if [[ -s "${dest}" ]]; then
    echo "==> ${srx}.h5ad present — skipping."
    n_skip=$((n_skip+1)); continue
  fi
  echo "==> gsutil cp ${gs_path}"
  if gsutil -u "${PROJECT}" cp "${gs_path}" "${dest}"; then
    n_ok=$((n_ok+1))
  else
    echo "    WARNING: failed to fetch ${srx} (${gs_path}); continuing." >&2
    rm -f "${dest}"
    n_fail=$((n_fail+1))
  fi
done < "${SAMPLES}"

echo "==> [01] Done. downloaded=${n_ok} skipped=${n_skip} failed=${n_fail}"
echo "    h5ads in: ${H5AD_DIR}"
ls -lh "${H5AD_DIR}" | head -n 20
[[ $((n_ok + n_skip)) -gt 0 ]] || { echo "ERROR: no h5ads available — check bucket paths/auth." >&2; exit 4; }
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
