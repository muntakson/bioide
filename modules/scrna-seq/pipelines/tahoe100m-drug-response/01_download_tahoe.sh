#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 01_download_tahoe.sh  (Tahoe-100M → one drug + DMSO controls, stream-subset)
#
# NO full download. Tahoe-100M is ~1.69 TB sharded across ~14 plate h5ads. We:
#   1. 01_query_metadata.py  — read the small metadata parquet tables, pick the target
#      drug (+ DMSO controls) across a few cell lines, write the selected cells + which
#      plate holds each (selected_cells.csv, plate_h5ads.csv, drug_targets.csv).
#   2. 01_subset_download.py — open each plate h5ad in BACKED mode over gcsfs and pull
#      ONLY the selected rows into a small local tahoe_subset.h5ad.
#
# Requester Pays: billed to your GCP project (2 TB/mo free). A single-drug subset is a
# few thousand cells → well within the free tier. Pick the drug with $TAHOE_DRUG.
#
# flock guards against a parallel run; both steps are idempotent (skip when outputs exist).
# =============================================================================

DATA_DIR="${HOME}/ghbio-tutorial/data/tahoe100m"
LOCK="${DATA_DIR}/.download.lock"
PY="${HOME}/ghbio-venv/bin/python"
HERE="$(cd "$(dirname "$0")" && pwd)"
DRUG="${TAHOE_DRUG:-Vorinostat}"
MAX_CELL_LINES="${MAX_CELL_LINES:-6}"

mkdir -p "${DATA_DIR}"
echo "==> [01] Tahoe-100M subset → ${DATA_DIR}  (drug='${DRUG}', ≤${MAX_CELL_LINES} cell lines)"
[[ -x "$PY" ]] || { echo "ERROR: venv python missing at $PY (run 00_setup_env.sh)." >&2; exit 1; }
command -v gsutil >/dev/null 2>&1 || { echo "ERROR: gsutil not on PATH (run 00_setup_env.sh)." >&2; exit 1; }

# Billing project must be set (Requester Pays).
PROJECT="${GHBIO_GCP_PROJECT:-}"
if [[ -z "${PROJECT}" && -f "${HOME}/.config/ghbio/gcp.json" ]]; then
  PROJECT="$("$PY" -c "import json;print(json.load(open('${HOME}/.config/ghbio/gcp.json')).get('project',''))" 2>/dev/null || true)"
fi
[[ -z "${PROJECT}" ]] && PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no GCP billing project. Run ../_shared/setup_gcp.sh <project-id>." >&2
  exit 2
fi
echo "==> billing project: ${PROJECT}"

exec 9>"${LOCK}"
if ! flock -n 9; then
  echo "==> Another download is already running (lock held). Waiting…"
  flock 9
fi

# 1) select cells
if [[ -s "${DATA_DIR}/selected_cells.csv" && "${FORCE:-0}" != "1" ]]; then
  echo "==> Reusing existing selection (FORCE=1 to re-query)."
else
  "$PY" "${HERE}/01_query_metadata.py" --data-dir "${DATA_DIR}" \
    --drug "${DRUG}" --max-cell-lines "${MAX_CELL_LINES}"
fi
[[ -s "${DATA_DIR}/selected_cells.csv" ]] || { echo "ERROR: selection not produced." >&2; exit 3; }

# 2) stream-subset the cells out of the plate h5ads
"$PY" "${HERE}/01_subset_download.py" --data-dir "${DATA_DIR}"
[[ -s "${DATA_DIR}/tahoe_subset.h5ad" ]] || { echo "ERROR: tahoe_subset.h5ad not produced." >&2; exit 4; }

echo "==> [01] Done. Subset: ${DATA_DIR}/tahoe_subset.h5ad"
echo "    Next: 2. GPU 독립 재분석 (run_gpu_reanalysis.sh)."
