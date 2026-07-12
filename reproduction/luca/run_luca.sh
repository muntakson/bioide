#!/usr/bin/env bash
# Launch the authors' pinned LuCA Nextflow workflows.
set -euo pipefail

MODE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUCA_DIR="${LUCA_DIR:-${ROOT}/../../third_party/luca}"
NXF_VER="${NXF_VER:-22.04.5}"
LUCA_PROFILE="${LUCA_PROFILE:-standard}"

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    echo "ERROR: LuCA's supplied Singularity containers target the authors' x86_64 HPC environment." >&2
    echo "       Current architecture: $(uname -m). Run this launcher on x86_64 Linux." >&2
    exit 1
    ;;
esac
command -v nextflow >/dev/null || { echo "ERROR: nextflow is not installed." >&2; exit 1; }
command -v apptainer >/dev/null || command -v singularity >/dev/null || {
  echo "ERROR: Apptainer or Singularity is required by the authors' workflow." >&2; exit 1;
}
[[ -d "${LUCA_DIR}/containers" ]] || { echo "ERROR: containers missing; run fetch_luca.sh first." >&2; exit 1; }

export NXF_VER
cd "${LUCA_DIR}"
case "${MODE}" in
  build)
    nextflow run main.nf --workflow build_atlas -resume -profile "${LUCA_PROFILE}" --outdir "./data/20_build_atlas"
    ;;
  downstream)
    [[ -d ./data/20_build_atlas ]] || {
      echo "ERROR: published build results missing; run: bash ${ROOT}/fetch_luca.sh downstream" >&2
      exit 1
    }
    nextflow run main.nf --workflow downstream_analyses -resume -profile "${LUCA_PROFILE}" --build_atlas_dir "./data/20_build_atlas" --outdir "./data/30_downstream_analyses"
    ;;
  *) echo "Usage: bash run_luca.sh {build|downstream}" >&2; exit 2 ;;
esac
