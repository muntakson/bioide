#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# 02a_build_starsolo.sh
# Build the STAR aligner (which includes STARsolo) FROM SOURCE on aarch64/ARM64.
# aarch64(ARM64)에서 STAR 정렬기를 소스로부터 빌드합니다 (STARsolo 포함).
#
# WHY from source?  /  왜 소스 빌드인가?
#   - The precompiled STAR Linux binaries and Cell Ranger are x86-64 only.
#   - On ARM64 we must compile, AND override the x86 SIMD flags.
#   - x86 전용 바이너리는 ARM에서 동작하지 않으므로 소스에서 빌드하고
#     x86 SIMD 플래그를 ARM용으로 교체합니다.
#
# KEY ARM64 DETAIL  /  ARM64 핵심 포인트:
#   STAR's Makefile bundles the "opal" SIMD library and defaults to:
#       CXXFLAGS_SIMD ?= -mavx2      <-- x86-only, FAILS on ARM64
#   We override it with an ARM-safe value:
#       make STAR CXXFLAGS_SIMD="-march=armv8-a"
#   (Set CXXFLAGS_SIMD="" to disable SIMD entirely if -march causes trouble.)
#
# Idempotent: skips the build if ~/bin/STAR already reports the right version.
# =============================================================================

STAR_VERSION="2.7.11b"                 # latest 2.7.x release (verified)
BUILD_ROOT="${HOME}/ghbio-tutorial/build"
INSTALL_DIR="${HOME}/bin"
STAR_BIN="${INSTALL_DIR}/STAR"

mkdir -p "${BUILD_ROOT}" "${INSTALL_DIR}"

echo "==> [02a] Building STAR ${STAR_VERSION} from source (aarch64)"

# --- 0. Fast path: already installed? ----------------------------------------
if [[ -x "${STAR_BIN}" ]] && "${STAR_BIN}" --version 2>/dev/null | grep -q "${STAR_VERSION}"; then
  echo "==> STAR ${STAR_VERSION} already installed at ${STAR_BIN}, skipping build."
  "${STAR_BIN}" --version
  exit 0
fi

# --- 1. Basic toolchain check ------------------------------------------------
# 컴파일러 확인.
for tool in g++ make curl tar; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "ERROR: '${tool}' not found. Install build tools, e.g.:" >&2
    echo "       sudo apt-get install -y build-essential zlib1g-dev curl" >&2
    exit 1
  fi
done

ARCH="$(uname -m)"
echo "==> Detected architecture: ${ARCH}"

# --- 2. Download STAR source tarball (resumable) -----------------------------
SRC_TARBALL="${BUILD_ROOT}/STAR-${STAR_VERSION}.tar.gz"
SRC_URL="https://github.com/alexdobin/STAR/archive/refs/tags/${STAR_VERSION}.tar.gz"
SRC_DIR="${BUILD_ROOT}/STAR-${STAR_VERSION}"

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "==> Downloading STAR source from ${SRC_URL}"
  curl -L -C - -o "${SRC_TARBALL}" "${SRC_URL}"
  echo "==> Extracting..."
  tar -xzf "${SRC_TARBALL}" -C "${BUILD_ROOT}"
else
  echo "==> Source directory already present: ${SRC_DIR}"
fi

# --- 3. Choose SIMD flags per architecture -----------------------------------
# ARM64 must NOT use -mavx2 / -msse4.1 (x86-only). Use a generic ARMv8 flag.
# ARM64에서는 x86 SIMD 플래그 대신 ARMv8 플래그를 사용합니다.
if [[ "${ARCH}" == "aarch64" || "${ARCH}" == "arm64" ]]; then
  SIMD_FLAG="-march=armv8-a"
  echo "==> ARM64 detected: overriding CXXFLAGS_SIMD='${SIMD_FLAG}' (no x86 AVX/SSE)."
else
  SIMD_FLAG="-mavx2"
  echo "==> Non-ARM architecture: using default CXXFLAGS_SIMD='${SIMD_FLAG}'."
fi

# --- 4. Compile ---------------------------------------------------------------
# We build only the 'STAR' target (the plain aligner incl. STARsolo).
# 'make STAR' 타깃만 빌드합니다 (STARsolo 포함).
echo "==> Compiling STAR (this can take several minutes)..."
(
  cd "${SRC_DIR}/source"
  # Clean any partial x86 objects from a previous failed attempt.
  make clean >/dev/null 2>&1 || true
  make STAR CXXFLAGS_SIMD="${SIMD_FLAG}" -j "$(nproc)"
)

# --- 5. Install the binary ----------------------------------------------------
echo "==> Installing STAR binary to ${STAR_BIN}"
cp "${SRC_DIR}/source/STAR" "${STAR_BIN}"
chmod +x "${STAR_BIN}"

# --- 6. Verify ----------------------------------------------------------------
echo ""
echo "==> Verifying installation:"
"${STAR_BIN}" --version

echo ""
echo "==> [02a] Done. STAR installed at: ${STAR_BIN}"
echo "    Add ~/bin to your PATH if it isn't already:"
echo '        export PATH="$HOME/bin:$PATH"'
