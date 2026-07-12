#!/usr/bin/env bash
# Download and verify the public LuCA archives published by Salcher et al.
set -euo pipefail

MODE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUCA_DIR="${LUCA_DIR:-${ROOT}/../../third_party/luca}"
RECORD="7227571"
BASE_URL="https://zenodo.org/records/${RECORD}/files"

usage() {
  cat <<'EOF'
Usage: bash fetch_luca.sh {full|downstream|published-results|model}

  full               containers + processed input data for rebuilding the atlas
  downstream         containers + processed input data + published build results
  published-results  publication's downstream result archive (no execution)
  model              published core-atlas scANVI model
EOF
}

[[ -d "${LUCA_DIR}/.git" ]] || {
  echo "ERROR: Author workflow clone not found: ${LUCA_DIR}" >&2
  echo "Clone https://github.com/icbi-lab/luca there, or set LUCA_DIR." >&2
  exit 1
}

declare -a FILES=()
case "${MODE}" in
  full) FILES=("containers.tar.xz:1603e7fc78a194729256d4bc62903073" "input_data.tar.xz:e0ae48e02595cad4bda6fe42ae0518ea") ;;
  downstream) FILES=("containers.tar.xz:1603e7fc78a194729256d4bc62903073" "input_data.tar.xz:e0ae48e02595cad4bda6fe42ae0518ea" "build_atlas_results.tar.xz:bb3147b82715fb6be32f868cceee5ac6") ;;
  published-results) FILES=("downstream_analyses_results.tar.xz:6d6e76d7f5b71f8c5f507d0561e94786") ;;
  model) FILES=("core_atlas_scanvi_model.tar.gz:da8f1f93a984f700a2a21c1233d68310") ;;
  *) usage >&2; exit 2 ;;
esac

download_dir="${LUCA_DIR}/.downloads"
mkdir -p "${download_dir}"
for item in "${FILES[@]}"; do
  filename="${item%%:*}"
  md5="${item##*:}"
  archive="${download_dir}/${filename}"
  if [[ -f "${archive}" ]] && echo "${md5}  ${archive}" | md5sum -c - >/dev/null; then
    echo "==> Verified existing ${filename}"
  else
    echo "==> Downloading ${filename} (resumable; this can be large)"
    curl --fail --location --continue-at - --output "${archive}" "${BASE_URL}/${filename}?download=1"
    echo "${md5}  ${archive}" | md5sum -c -
  fi
  echo "==> Extracting ${filename} into ${LUCA_DIR}"
  case "${filename}" in
    *.tar.xz) tar -xJf "${archive}" -C "${LUCA_DIR}" ;;
    *.tar.gz) tar -xzf "${archive}" -C "${LUCA_DIR}" ;;
  esac
done
echo "==> Done. See ${ROOT}/README.md for the matching execution command."
