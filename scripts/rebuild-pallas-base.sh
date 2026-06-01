#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_BASE_SRC="$INRIA_ROOT/pallas-base"
export PALLAS_BASE_BUILD="$PALLAS_BASE_SRC/build-pallas"
export PALLAS_BASE_ROOT="$PALLAS_BASE_SRC/install-pallas"

JOBS="${JOBS:-$(nproc)}"
CMAKE_ARGS=("$@")

if [ ! -d "$PALLAS_BASE_SRC/.git" ]; then
    echo "[rebuild-pallas-base] ERROR: Pallas-base repo not found:"
    echo "    $PALLAS_BASE_SRC"
    exit 1
fi

cd "$PALLAS_BASE_SRC"
echo "[rebuild-pallas-base] Using current Pallas-base checkout:"
echo "    branch=$(git branch --show-current 2>/dev/null || true)"
echo "    commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

echo "[rebuild-pallas-base] Removing old baseline Pallas build/install..."
rm -rf "$PALLAS_BASE_BUILD" "$PALLAS_BASE_ROOT"

mkdir -p "$PALLAS_BASE_BUILD" "$PALLAS_BASE_ROOT"

echo "[rebuild-pallas-base] Configuring baseline Pallas..."
if ((${#CMAKE_ARGS[@]} > 0)); then
    echo "[rebuild-pallas-base] Extra CMake args: ${CMAKE_ARGS[*]}"
fi

cmake -S "$PALLAS_BASE_SRC" -B "$PALLAS_BASE_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PALLAS_BASE_ROOT" \
    "${CMAKE_ARGS[@]}"

echo "[rebuild-pallas-base] Building baseline Pallas..."
cmake --build "$PALLAS_BASE_BUILD" -j"$JOBS"

echo "[rebuild-pallas-base] Installing baseline Pallas..."
cmake --install "$PALLAS_BASE_BUILD"

echo "[rebuild-pallas-base] Activating baseline Pallas environment..."
source "$INRIA_SCRIPTS_DIR/env-pallas-base.sh"

echo "[rebuild-pallas-base] Sanity checks:"
echo "PALLAS_BASE_ROOT=$PALLAS_BASE_ROOT"
echo "pallas_print=$(command -v pallas_print || true)"
echo "pallas_info=$(command -v pallas_info || true)"
echo "otf2-config=$(command -v otf2-config || true)"
echo "otf2-print=$(command -v otf2-print || true)"

echo "[rebuild-pallas-base] Installed files:"
find "$PALLAS_BASE_ROOT" -maxdepth 3 -type f \
    \( -name 'pallas_*' -o -name 'libpallas*' -o -name 'libotf2*' -o -name 'otf2-config' \) \
    | sort || true

echo "[rebuild-pallas-base] Done."
echo "[rebuild-pallas-base] Activate in current shell with:"
echo "  source ~/inria/scripts/env-pallas-base.sh"
