#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_SRC="$INRIA_ROOT/pallas"
export PALLAS_BUILD="$PALLAS_SRC/build-pallas"
export PALLAS_ROOT="$PALLAS_SRC/install-pallas"
export BLUP_CONFIG="$INRIA_ROOT/blup-config"
export BLUP_VENV="$BLUP_CONFIG/venv"

JOBS="${JOBS:-$(nproc)}"
CMAKE_ARGS=("$@")

if [ ! -d "$PALLAS_SRC/.git" ]; then
    echo "[rebuild-pallas] ERROR: Pallas repo not found:"
    echo "    $PALLAS_SRC"
    echo "Clone or create the checkout you want to build first."
    exit 1
fi

cd "$PALLAS_SRC"
echo "[rebuild-pallas] Using current Pallas checkout:"
echo "    branch=$(git branch --show-current 2>/dev/null || true)"
echo "    commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

echo "[rebuild-pallas] Removing old Pallas build/install..."
rm -rf "$PALLAS_BUILD" "$PALLAS_ROOT"

mkdir -p "$PALLAS_BUILD" "$PALLAS_ROOT"

echo "[rebuild-pallas] Configuring Pallas..."
if ((${#CMAKE_ARGS[@]} > 0)); then
    echo "[rebuild-pallas] Extra CMake args: ${CMAKE_ARGS[*]}"
fi

cmake -S "$PALLAS_SRC" -B "$PALLAS_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PALLAS_ROOT" \
    "${CMAKE_ARGS[@]}"

echo "[rebuild-pallas] Building Pallas..."
cmake --build "$PALLAS_BUILD" -j"$JOBS"

echo "[rebuild-pallas] Installing Pallas..."
cmake --install "$PALLAS_BUILD"

if [ -d "$BLUP_VENV" ]; then
    echo "[rebuild-pallas] Installing pallas_python into Blup venv..."
    source "$BLUP_VENV/bin/activate"
    python -m pip install -e "$PALLAS_SRC"
    echo "[rebuild-pallas] Blup venv python=$(command -v python || true)"
else
    echo "[rebuild-pallas] Blup venv not found at $BLUP_VENV; skipping Python package install."
fi

echo "[rebuild-pallas] Activating Pallas environment..."
source "$INRIA_SCRIPTS_DIR/env-pallas.sh"

echo "[rebuild-pallas] Sanity checks:"
echo "PALLAS_ROOT=$PALLAS_ROOT"
echo "pallas_print=$(command -v pallas_print || true)"
echo "pallas_read_benchmark=$(command -v pallas_read_benchmark || true)"
echo "pallas_info=$(command -v pallas_info || true)"
echo "otf2-config=$(command -v otf2-config || true)"
echo "otf2-print=$(command -v otf2-print || true)"

echo "[rebuild-pallas] Installed files:"
find "$PALLAS_ROOT" -maxdepth 3 -type f \
    \( -name 'pallas_*' -o -name 'libpallas*' -o -name 'libotf2*' -o -name 'otf2-config' \) \
    | sort || true

echo "[rebuild-pallas] Done."
echo "[rebuild-pallas] Activate in current shell with:"
echo "  source ~/inria/scripts/env-pallas.sh"
