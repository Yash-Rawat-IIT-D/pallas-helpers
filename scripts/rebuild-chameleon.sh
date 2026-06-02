#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export CHAMELEON_SRC="$INRIA_ROOT/chameleon"
export CHAMELEON_BUILD="$CHAMELEON_SRC/build-chameleon"
export CHAMELEON_ROOT="$CHAMELEON_SRC/install-chameleon"

JOBS="${JOBS:-$(nproc)}"
CMAKE_ARGS=("$@")

if [ ! -d "$CHAMELEON_SRC/.git" ]; then
    echo "[rebuild-chameleon] ERROR: Chameleon repo not found:"
    echo "    $CHAMELEON_SRC"
    echo "Clone it first with submodules:"
    echo "    cd ~/inria"
    echo "    git clone --recurse-submodules https://gitlab.inria.fr/solverstack/chameleon.git"
    exit 1
fi

source "$INRIA_SCRIPTS_DIR/env-starpu.sh"

cd "$CHAMELEON_SRC"
echo "[rebuild-chameleon] Using current Chameleon checkout:"
echo "    branch=$(git branch --show-current 2>/dev/null || true)"
echo "    commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

if [ -f "$CHAMELEON_SRC/.gitmodules" ]; then
    echo "[rebuild-chameleon] Syncing submodules..."
    git submodule update --init --recursive
fi

echo "[rebuild-chameleon] Removing old Chameleon build/install..."
rm -rf "$CHAMELEON_BUILD" "$CHAMELEON_ROOT"

mkdir -p "$CHAMELEON_BUILD" "$CHAMELEON_ROOT"

echo "[rebuild-chameleon] Configuring Chameleon..."
if ((${#CMAKE_ARGS[@]} > 0)); then
    echo "[rebuild-chameleon] Extra CMake args: ${CMAKE_ARGS[*]}"
fi

cmake -S "$CHAMELEON_SRC" -B "$CHAMELEON_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$CHAMELEON_ROOT" \
    -DCHAMELEON_SCHED=STARPU \
    -DCHAMELEON_USE_MPI=ON \
    -DCHAMELEON_ENABLE_EXAMPLE=ON \
    -DCHAMELEON_ENABLE_TESTING=ON \
    -DBUILD_SHARED_LIBS=ON \
    -DBLA_PREFER_PKGCONFIG=ON \
    "${CMAKE_ARGS[@]}"

echo "[rebuild-chameleon] Building Chameleon..."
cmake --build "$CHAMELEON_BUILD" -j"$JOBS"

echo "[rebuild-chameleon] Installing Chameleon..."
cmake --install "$CHAMELEON_BUILD"

echo "[rebuild-chameleon] Activating Chameleon environment..."
source "$INRIA_SCRIPTS_DIR/env-chameleon.sh"

echo "[rebuild-chameleon] Sanity checks:"
echo "CHAMELEON_ROOT=$CHAMELEON_ROOT"
echo "pkg-config chameleon=$({ pkg-config --modversion chameleon 2>/dev/null || true; })"
echo "pkg-config starpu=$({ pkg-config --modversion starpu-1.4 2>/dev/null || true; })"

echo "[rebuild-chameleon] Installed files:"
find "$CHAMELEON_ROOT" -maxdepth 4 -type f \
    \( -name 'libchameleon*' -o -name 'chameleon*.pc' -o -name 'CHAMELEONConfig.cmake' \) \
    | sort || true

echo "[rebuild-chameleon] Done."
echo "[rebuild-chameleon] Activate in current shell with:"
echo "  source ~/inria/scripts/env-chameleon.sh"
