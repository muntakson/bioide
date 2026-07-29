#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# setup_gcp.sh  — SHARED helper: configure GCP billing for Requester-Pays GCS buckets
#
# Lives in modules/scrna-seq/pipelines/_shared/ (the "_"-prefix makes the pipeline
# loader ignore it — it is NOT a pipeline). Shared by every pipeline that pulls from a
# Requester-Pays bucket (the Arc Virtual Cell Atlas: scBaseCount, Tahoe-100M, …), so
# there is one copy, not one per pipeline.
#
# The atlas lives in a Requester-Pays GCS bucket, so every download is billed to YOUR
# Google Cloud project (2 TB/month free tier). This helper writes the project id to
# ~/.config/ghbio/gcp.json (chmod 600, alongside providers.json — OUTSIDE the repo),
# checks that gsutil + auth are in place, and does a cheap live access test.
#
# Usage (from any pipeline dir, or anywhere with the full path):
#   bash ../_shared/setup_gcp.sh                 # prompts for the project id
#   bash ../_shared/setup_gcp.sh my-project-id   # non-interactive
#   GHBIO_GCP_PROJECT=my-project bash ../_shared/setup_gcp.sh
#
# Override the bucket tested at the end with --bucket <gs://…> or $GHBIO_ATLAS_BUCKET.
# Re-run any time; it shows the current value and asks before overwriting.
# =============================================================================

CFG_DIR="${HOME}/.config/ghbio"
CFG="${CFG_DIR}/gcp.json"
BUCKET="${GHBIO_ATLAS_BUCKET:-gs://arc-institute-virtual-cell-atlas}"

say() { printf '%s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# collect positional project id + optional --bucket override
POS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bucket) BUCKET="$2"; shift 2;;
    *) POS+=("$1"); shift;;
  esac
done
set -- "${POS[@]+"${POS[@]}"}"

# --- 1. resolve the project id (arg > env > existing file > gcloud > prompt) ----
PROJECT="${1:-${GHBIO_GCP_PROJECT:-}}"
EXISTING=""
if [[ -f "${CFG}" ]]; then
  EXISTING="$(python3 -c "import json;print(json.load(open('${CFG}')).get('project',''))" 2>/dev/null || true)"
  [[ -n "${EXISTING}" ]] && say "==> Current ${CFG}: project=${EXISTING}"
fi
if [[ -z "${PROJECT}" ]]; then
  DEFAULT="${EXISTING}"
  if [[ -z "${DEFAULT}" ]] && have gcloud; then
    DEFAULT="$(gcloud config get-value project 2>/dev/null || true)"
    [[ "${DEFAULT}" == "(unset)" ]] && DEFAULT=""
  fi
  if [[ -t 0 ]]; then
    read -r -p "Enter your GCP project id${DEFAULT:+ [${DEFAULT}]}: " PROJECT
    PROJECT="${PROJECT:-${DEFAULT}}"
  else
    PROJECT="${DEFAULT}"
  fi
fi
if [[ -z "${PROJECT}" ]]; then
  say "ERROR: no project id given. Re-run:  bash ../_shared/setup_gcp.sh <project-id>" >&2
  exit 1
fi

# --- 2. write the config (chmod 600), confirm before clobbering a different value --
if [[ -n "${EXISTING}" && "${EXISTING}" != "${PROJECT}" && -t 0 ]]; then
  read -r -p "Overwrite project '${EXISTING}' with '${PROJECT}'? [y/N] " ok
  [[ "${ok}" =~ ^[Yy]$ ]] || { say "Aborted; ${CFG} unchanged."; exit 0; }
fi
mkdir -p "${CFG_DIR}"
umask 177   # new file = 600
python3 - "$CFG" "$PROJECT" <<'PY'
import json, sys
path, project = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except Exception:
    data = {}
data["project"] = project
json.dump(data, open(path, "w"), indent=2)
open(path, "a").write("\n")
PY
chmod 600 "${CFG}"
say "==> Wrote ${CFG} (chmod 600): project=${PROJECT}"

# --- 3. environment / auth checks ---------------------------------------------
say ""
say "==> Checks:"
if have gsutil; then
  say "  ✓ gsutil: $(command -v gsutil)"
else
  say "  ✗ gsutil NOT found. Install the Google Cloud SDK:"
  say "      curl -sSL https://sdk.cloud.google.com | bash && exec -l \"\$SHELL\""
fi
if have gcloud; then
  ACCT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1 || true)"
  if [[ -n "${ACCT}" ]]; then
    say "  ✓ gcloud auth: ${ACCT}"
  else
    say "  ✗ not authenticated. Run once:"
    say "      gcloud auth login && gcloud auth application-default login"
  fi
  # keep gcloud's own default project in sync so ad-hoc gsutil calls also work
  gcloud config set project "${PROJECT}" >/dev/null 2>&1 || true
else
  say "  ✗ gcloud NOT found (needed for auth). Install the Cloud SDK (see above)."
fi

# --- 4. live Requester-Pays access test (cheap: list bucket root) --------------
if have gsutil; then
  say ""
  say "==> Testing Requester-Pays access (billed to ${PROJECT}) — listing bucket root:"
  if gsutil -u "${PROJECT}" ls "${BUCKET}/" >/dev/null 2>&1; then
    say "  ✓ can list ${BUCKET} — billing + auth OK."
  else
    say "  ✗ could not list ${BUCKET}."
    say "    Fix: authenticate (step 3), confirm the project has billing enabled, and that"
    say "    the Cloud Storage API is on. Then re-run this test:"
    say "      gsutil -u ${PROJECT} ls ${BUCKET}/"
  fi
fi

say ""
say "==> Done. Next: run your pipeline's download step (e.g. scbasecount-hcc:"
say "    bash 01_download_scbasecount_hcc.sh)."
