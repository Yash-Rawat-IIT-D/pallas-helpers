#!/usr/bin/env bash
set -euo pipefail

# Purpose:
#   Fully rebuild local OTF2 + EZTrace from source.
#
# Usage:
#   bash ~/inria/scripts/rebuild-otf2-eztrace.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"
source "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh"

JOBS="${JOBS:-$(nproc)}"

echo "[rebuild] INRIA_ROOT=$INRIA_ROOT"
echo "[rebuild] OTF2_SRC=$OTF2_SRC"
echo "[rebuild] EZTRACE_SRC=$EZTRACE_SRC"
echo "[rebuild] jobs=$JOBS"

if [ ! -d "$OTF2_SRC" ]; then
    echo "[rebuild] ERROR: OTF2 source directory not found:"
    echo "          $OTF2_SRC"
    echo "          Download/extract otf2-$OTF2_VERSION first."
    exit 1
fi

if [ ! -d "$EZTRACE_SRC" ]; then
    echo "[rebuild] ERROR: EZTrace source directory not found:"
    echo "          $EZTRACE_SRC"
    echo "          Clone EZTrace first:"
    echo "          git clone https://gitlab.com/eztrace/eztrace.git $EZTRACE_SRC"
    exit 1
fi

echo "[rebuild] Removing old build/install directories..."
rm -rf "$OTF2_BUILD" "$OTF2_ROOT" "$EZTRACE_BUILD" "$EZTRACE_ROOT"

mkdir -p "$OTF2_BUILD" "$OTF2_ROOT"
mkdir -p "$EZTRACE_BUILD" "$EZTRACE_ROOT"

echo "[rebuild] Building OTF2..."
cd "$OTF2_BUILD"
# PYTHON="$(command -v python3)" ../configure --prefix="$OTF2_ROOT"
../configure --prefix="$OTF2_ROOT" PYTHON=:
make -j"$JOBS"
make install

echo "[rebuild] Re-activating environment after OTF2 install..."
source "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh"

echo "[rebuild] OTF2 sanity:"
which otf2-config || true
otf2-config --version || true

echo "[rebuild] Building EZTrace..."
cmake -S "$EZTRACE_SRC" -B "$EZTRACE_BUILD" \
    -DCMAKE_INSTALL_PREFIX="$EZTRACE_ROOT" \
    -DEZTRACE_ENABLE_MPI=ON \
    -DCMAKE_PREFIX_PATH="$OTF2_ROOT"

cmake --build "$EZTRACE_BUILD" -j"$JOBS"
cmake --install "$EZTRACE_BUILD"

echo "[rebuild] Re-activating final environment..."
source "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh"

echo "[rebuild] Final sanity checks:"
echo "PATH otf2-config: $(command -v otf2-config || true)"
echo "PATH otf2-print:  $(command -v otf2-print || true)"
echo "PATH eztrace:     $(command -v eztrace || true)"
echo "PATH eztrace_avail: $(command -v eztrace_avail || true)"

otf2-config --version || true
eztrace --version || true
eztrace_avail || true

echo "[rebuild] Done."
