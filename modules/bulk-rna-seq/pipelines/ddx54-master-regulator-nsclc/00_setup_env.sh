#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 00_setup_env.sh  (DDX54 면역회피 마스터조절자 — LLC1 Ddx54-KD 독립재현)
# Reuse the shared virtual environment (~/ghbio-venv) used by the other BioIDE
# pipelines. This bulk RNA-seq reproduction starts from a public GEO count matrix
# (GSE285342), so it needs only a core stats/plotting stack — no aligner, no
# scanpy. Everything runs on CPU; only step 1 needs internet (to fetch GEO).
# 이 예제는 GEO 공개 count matrix(GSE285342)에서 시작하므로 통계·시각화 스택만 있으면 됩니다.
#
# Idempotent: if the stack already imports, we skip pip entirely. FORCE=1 reinstalls.
# =============================================================================

VENV="${HOME}/ghbio-venv"
echo "==> [00] Python stats stack for the DDX54-KD (LLC1) reproduction: ${VENV}"

if [[ ! -d "${VENV}" ]]; then
  echo "==> Creating virtualenv..."
  python3 -m venv "${VENV}"
else
  echo "==> Virtualenv already exists, reusing it."
fi

# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# openpyxl is required to read the vendor's .xlsx isoform report; the rest are the
# usual numeric/plotting stack shared with the scRNA-seq pipelines.
if python -c "import pandas, numpy, scipy, statsmodels, matplotlib, openpyxl" 2>/dev/null \
   && [[ "${FORCE:-0}" != "1" ]]; then
  echo "==> Core analysis stack already installed — skipping pip install."
  echo "    (Reinstall with:  FORCE=1 bash 00_setup_env.sh)"
else
  echo "==> Upgrading pip / setuptools / wheel..."
  python -m pip install --upgrade pip setuptools wheel
  echo "==> Installing core dependencies..."
  python -m pip install \
    pandas numpy scipy statsmodels matplotlib openpyxl
fi

echo ""
echo "==> Installed versions:"
python - <<'PY'
import importlib.metadata as md, sys
print(f"  python   {sys.version.split()[0]}")
for p in ["pandas", "numpy", "scipy", "statsmodels", "matplotlib", "openpyxl"]:
    try:
        print(f"  {p:<12} {md.version(p)}")
    except md.PackageNotFoundError:
        pass
PY

echo ""
echo "==> [00] Done. Next: 1. GEO count matrix 내려받기·준비 (GSE285342, WT vs Ddx54-KD)."
