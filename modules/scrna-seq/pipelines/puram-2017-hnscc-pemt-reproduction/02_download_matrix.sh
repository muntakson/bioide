#!/usr/bin/env bash
set -euo pipefail

# 02_download_matrix.sh
# [download] Download processed matrix (GSE103322_HNSCC_all_data.txt.gz)
# 기본 경로: 처리 완료 TPM 행렬에서 시작.

RESULTS="${GHBIO_RESULTS:-${HOME}/ghbio-tutorial/results}"
RAW_DIR="${RESULTS}/raw"
mkdir -p "${RAW_DIR}"

# 공유 캐시 (heavy inputs are reused under ~/ghbio-tutorial)
CACHE_DIR="${HOME}/ghbio-tutorial/downloads"
mkdir -p "${CACHE_DIR}"

GZ_NAME="GSE103322_HNSCC_all_data.txt.gz"
TXT_NAME="GSE103322_HNSCC_all_data.txt"
GZ_CACHE="${CACHE_DIR}/${GZ_NAME}"
TXT_OUT="${RAW_DIR}/${TXT_NAME}"
MD5_OUT="${RESULTS}/download_md5.txt"

# GEO supplementary URL
URL="https://ftp.ncbi.nlm.nih.gov/geo/series/GSE103nnn/GSE103322/suppl/${GZ_NAME}"  # TODO: 확인 필요

LOCK="${CACHE_DIR}/${GZ_NAME}.lock"

# md5 helper (linux: md5sum)
md5_of() {
    md5sum "$1" | awk '{print $1}'
}

# 산출물이 이미 존재하면 스킵 (idempotent)
if [[ -s "${TXT_OUT}" && -s "${MD5_OUT}" ]]; then
    echo "[download] outputs already present, skipping: ${TXT_OUT}"
    exit 0
fi

# flock으로 다운로드 중복 방지
exec 9>"${LOCK}"
flock 9

# 다운로드 (재시도/stall 타임아웃, 이어받기)
if [[ ! -s "${GZ_CACHE}" ]]; then
    echo "[download] fetching ${URL}"
    curl -C - --retry 5 --speed-limit 1024 --speed-time 60 \
        -fSL -o "${GZ_CACHE}" "${URL}"
else
    echo "[download] cached archive found: ${GZ_CACHE}"
fi

# 압축 해제 (원본 gz 보존)
if [[ ! -s "${TXT_OUT}" ]]; then
    echo "[download] decompressing to ${TXT_OUT}"
    gunzip -c "${GZ_CACHE}" > "${TXT_OUT}.tmp"
    mv -f "${TXT_OUT}.tmp" "${TXT_OUT}"
fi

# md5 기록 (gz 및 해제된 txt 모두)
echo "[download] recording md5 -> ${MD5_OUT}"
{
    echo "$(md5_of "${GZ_CACHE}")  ${GZ_NAME}"
    echo "$(md5_of "${TXT_OUT}")  ${TXT_NAME}"
} > "${MD5_OUT}.tmp"
mv -f "${MD5_OUT}.tmp" "${MD5_OUT}"

echo "[download] done."
echo "  matrix: ${TXT_OUT}"
echo "  md5:    ${MD5_OUT}"
