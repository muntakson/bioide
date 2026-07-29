#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (scBaseCount HCC — Arc Virtual Cell Atlas · INDEPENDENT GPU reanalysis)
#
# BioIDE 헌장 제1·4조: 저자/자동 라벨을 소비하지 않고, 현대 GPU·Python 스택으로
# 세포유형·악성 간세포·TLS(3차 림프 구조)를 처음부터 다시 도출합니다. 이 예제는
# 원시 FASTQ 정렬 단계가 없습니다 — Arc Institute의 scBaseCount(Virtual Cell Atlas)가
# 이미 SRA 데이터를 SRAgent(LLM 에이전트)로 발굴하고 scRecounter(STARsolo)로
# **균일하게 재정량**한 h5ad(AnnData) 파일을 제공하기 때문입니다. 우리는 여기서
# 간세포암(HCC) 시료만 골라 내려받아, 여러 연구를 하나의 아틀라스로 통합 재분석합니다.
#
# 필요 도구:
#   - 분석 스택: Scanpy + PyTorch(GPU) + Harmony + scikit-learn  (다른 예제와 공유 venv)
#   - pyarrow: scBaseCount 메타데이터 테이블(parquet) 파싱용
#   - gsutil (Google Cloud SDK): Requester-Pays 버킷에서 h5ad 시료를 내려받는 데 필요
#
# Idempotent: 이미 설치되어 있으면 건너뜁니다. FORCE=1 이면 재설치.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] scBaseCount HCC reanalysis environment: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

if python -c "import scanpy, anndata, h5py, torch, harmonypy, sklearn, leidenalg, umap, matplotlib, pyarrow" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core stack (+pyarrow) already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing scanpy + PyTorch + harmonypy + scikit-learn + pyarrow (few minutes)..."
  python -m pip install \
    scanpy anndata h5py leidenalg python-igraph umap-learn \
    matplotlib pandas numpy scipy scikit-learn harmonypy pyarrow
  if command -v nvidia-smi >/dev/null 2>&1 && ! python -c "import torch" 2>/dev/null; then
    echo "==> GPU detected — installing PyTorch..."
    python -m pip install torch || echo "==> torch install failed; GPU step will refuse to run."
  fi
fi

# --- gsutil (Google Cloud SDK) --------------------------------------------------
# The Virtual Cell Atlas lives in a Requester-Pays GCS bucket, so we need gsutil and
# a billing project. We do NOT auto-install the SDK (it needs system packaging); we
# check for it and print exact install + auth instructions if it's missing.
echo ""
if command -v gsutil >/dev/null 2>&1; then
  echo "==> gsutil found: $(command -v gsutil)"
else
  cat <<'MSG'
==> gsutil (Google Cloud SDK) NOT found — required to download from the Requester-Pays
    Virtual Cell Atlas bucket (gs://arc-institute-virtual-cell-atlas).

    Install (Debian/Ubuntu aarch64 ok):
      curl -sSL https://sdk.cloud.google.com | bash
      exec -l "$SHELL"            # reload PATH
    Then authenticate ONCE (opens a browser / device flow):
      gcloud auth login
      gcloud auth application-default login
MSG
fi

# --- GCP billing project (Requester Pays) --------------------------------------
# Downloads are billed to YOUR GCP project (2 TB/month free tier). We resolve the
# project id from, in order: $GHBIO_GCP_PROJECT, ~/.config/ghbio/gcp.json {"project":...},
# or gcloud's active config. 01_download_scbasecount_hcc.sh reads the same.
CFG="${HOME}/.config/ghbio/gcp.json"
PROJECT="${GHBIO_GCP_PROJECT:-}"
if [[ -z "${PROJECT}" && -f "${CFG}" ]]; then
  PROJECT="$(python -c "import json,sys;print(json.load(open('${CFG}')).get('project',''))" 2>/dev/null || true)"
fi
if [[ -z "${PROJECT}" ]] && command -v gcloud >/dev/null 2>&1; then
  PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
fi
HELPER="$(cd "$(dirname "$0")/../_shared" 2>/dev/null && pwd)/setup_gcp.sh"
if [[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]]; then
  echo "==> GCP billing project for Requester-Pays downloads: ${PROJECT}"
else
  cat <<MSG
==> No GCP billing project configured yet. Run the shared helper (writes ${CFG}, checks
    auth, and does a live Requester-Pays access test):
      bash "${HELPER}" <your-project-id>
    (Requester-Pays: downloads are billed to this project; 2 TB/month is free.)
MSG
fi

echo ""
echo "==> Installed versions + GPU status:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["scanpy", "anndata", "torch", "harmonypy", "scikit-learn", "pyarrow"]:
    try: print(f"  {p:<13} {md.version(p)}")
    except md.PackageNotFoundError: pass
try:
    import torch
    print(f"  CUDA available: {torch.cuda.is_available()}"
          + (f" — {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else " (CPU only — GPU step will refuse)"))
except Exception as e:
    print("  torch check failed:", e)
PY

echo ""
echo "==> [00] Done. Next: 1. Query + download HCC samples from scBaseCount."
