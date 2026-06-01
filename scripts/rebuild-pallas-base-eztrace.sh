#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_BASE_SRC="$INRIA_ROOT/pallas-base"
export PALLAS_BASE_ROOT="$PALLAS_BASE_SRC/install-pallas"

export EZTRACE_SRC="$INRIA_ROOT/eztrace"
export EZTRACE_PALLAS_BASE_BUILD="$EZTRACE_SRC/build-pallas-base"
export EZTRACE_PALLAS_BASE_ROOT="$EZTRACE_SRC/install-pallas-base"

JOBS="${JOBS:-$(nproc)}"

if [ ! -d "$PALLAS_BASE_ROOT" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: baseline Pallas install not found:"
    echo "    $PALLAS_BASE_ROOT"
    echo "Run first:"
    echo "    rebuild-pallas-base"
    exit 1
fi

if [ ! -x "$PALLAS_BASE_ROOT/bin/otf2-config" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: baseline otf2-config not found:"
    echo "    $PALLAS_BASE_ROOT/bin/otf2-config"
    exit 1
fi

if [ ! -f "$PALLAS_BASE_ROOT/lib/libotf2.so" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: baseline libotf2.so not found:"
    echo "    $PALLAS_BASE_ROOT/lib/libotf2.so"
    exit 1
fi

if [ ! -f "$PALLAS_BASE_ROOT/include/pallas/pallas_config.h" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: baseline Pallas config header not found:"
    echo "    $PALLAS_BASE_ROOT/include/pallas/pallas_config.h"
    exit 1
fi

if [ ! -d "$EZTRACE_SRC/.git" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: EZTrace repo not found:"
    echo "    $EZTRACE_SRC"
    exit 1
fi

echo "[rebuild-pallas-base-eztrace] Using current source checkouts:"
cd "$PALLAS_BASE_SRC"
echo "    pallas-base-branch=$(git branch --show-current 2>/dev/null || true)"
echo "    pallas-base-commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

cd "$EZTRACE_SRC"
echo "    eztrace-branch=$(git branch --show-current 2>/dev/null || true)"
echo "    eztrace-commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

echo "[rebuild-pallas-base-eztrace] Preparing baseline libotf2 compatibility symlinks..."
cd "$PALLAS_BASE_ROOT/lib"
ln -sf libotf2.so libotf2.so.10
ln -sf libotf2.so libotf2.so.10.0.0

echo "[rebuild-pallas-base-eztrace] Removing old EZTrace-baseline build/install..."
rm -rf "$EZTRACE_PALLAS_BASE_BUILD" "$EZTRACE_PALLAS_BASE_ROOT"
mkdir -p "$EZTRACE_PALLAS_BASE_BUILD" "$EZTRACE_PALLAS_BASE_ROOT"

echo "[rebuild-pallas-base-eztrace] Activating baseline Pallas-backed environment..."
source "$INRIA_SCRIPTS_DIR/env-pallas-base-eztrace.sh"
hash -r 2>/dev/null || true

echo "[rebuild-pallas-base-eztrace] Critical check:"
echo "    otf2-config=$(command -v otf2-config || true)"
echo "    expected:    $PALLAS_BASE_ROOT/bin/otf2-config"

if [ "$(command -v otf2-config || true)" != "$PALLAS_BASE_ROOT/bin/otf2-config" ]; then
    echo "[rebuild-pallas-base-eztrace] ERROR: wrong otf2-config selected."
    exit 1
fi

echo "[rebuild-pallas-base-eztrace] Baseline otf2-config:"
otf2-config --version || true
otf2-config --ldflags || true
otf2-config --libs || true

PALLAS_FORCE_INCLUDE="-include $PALLAS_BASE_ROOT/include/pallas/pallas_config.h"
PALLAS_INCLUDES="-I$PALLAS_BASE_ROOT/include"
PALLAS_RPATH="-Wl,-rpath,$PALLAS_BASE_ROOT/lib"

export PATH="$PALLAS_BASE_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$PALLAS_BASE_ROOT/lib:$PALLAS_BASE_ROOT/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="$PALLAS_BASE_ROOT/lib/pkgconfig:$PALLAS_BASE_ROOT/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export CMAKE_PREFIX_PATH="$PALLAS_BASE_ROOT:${CMAKE_PREFIX_PATH:-}"

export CC="${CC:-gcc}"
export CXX="${CXX:-g++}"

export CPPFLAGS="$PALLAS_INCLUDES ${CPPFLAGS:-}"
export CFLAGS="$PALLAS_INCLUDES $PALLAS_FORCE_INCLUDE ${CFLAGS:-}"
export CXXFLAGS="$PALLAS_INCLUDES $PALLAS_FORCE_INCLUDE ${CXXFLAGS:-}"
export LDFLAGS="-L$PALLAS_BASE_ROOT/lib $PALLAS_RPATH ${LDFLAGS:-}"

echo "[rebuild-pallas-base-eztrace] Configuring EZTrace against baseline Pallas OTF2 backend..."
cmake -S "$EZTRACE_SRC" -B "$EZTRACE_PALLAS_BASE_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$EZTRACE_PALLAS_BASE_ROOT" \
    -DEZTRACE_ENABLE_MPI=ON \
    -DCMAKE_PREFIX_PATH="$PALLAS_BASE_ROOT" \
    -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS" \
    -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
    -DOTF2_CONFIG="$PALLAS_BASE_ROOT/bin/otf2-config" \
    -DOTF2_ROOT="$PALLAS_BASE_ROOT" \
    -DOTF2_LIBRARY="$PALLAS_BASE_ROOT/lib/libotf2.so" \
    -DOTF2_INCLUDE_DIR="$PALLAS_BASE_ROOT/include" \
    -DOTF2_INCLUDE_DIRS="$PALLAS_BASE_ROOT/include"

echo "[rebuild-pallas-base-eztrace] Build-cache OTF2 references:"
grep -RniE 'OTF2|otf2|pallas|otf2-3.1.1' "$EZTRACE_PALLAS_BASE_BUILD/CMakeCache.txt" 2>/dev/null | head -120 || true

echo "[rebuild-pallas-base-eztrace] Building..."
cmake --build "$EZTRACE_PALLAS_BASE_BUILD" -j"$JOBS"

echo "[rebuild-pallas-base-eztrace] Installing..."
cmake --install "$EZTRACE_PALLAS_BASE_BUILD"

echo "[rebuild-pallas-base-eztrace] Final activation..."
source "$INRIA_SCRIPTS_DIR/env-pallas-base-eztrace.sh"
hash -r 2>/dev/null || true

echo "[rebuild-pallas-base-eztrace] Sanity checks:"
echo "    eztrace=$(command -v eztrace || true)"
echo "    otf2-config=$(command -v otf2-config || true)"
echo "    pallas_print=$(command -v pallas_print || true)"

eztrace --version || true
otf2-config --version || true

echo "[rebuild-pallas-base-eztrace] Checking whether EZTrace compiled Pallas-specific code..."
if strings "$EZTRACE_PALLAS_BASE_ROOT/lib/libeztrace-lib.so" | grep -F "Using Pallas" >/dev/null; then
    echo "    OK: Pallas-specific EZTrace code is present."
    strings "$EZTRACE_PALLAS_BASE_ROOT/lib/libeztrace-lib.so" | grep -F "Using Pallas" || true
else
    echo "    WARNING: Could not find 'Using Pallas' string in libeztrace-lib.so."
fi

echo "[rebuild-pallas-base-eztrace] Runtime linking checks:"
echo "--- libeztrace-lib.so"
ldd "$EZTRACE_PALLAS_BASE_ROOT/lib/libeztrace-lib.so" | grep -Ei 'otf2|pallas|eztrace' || true

echo "--- libeztrace-mpi.so"
ldd "$EZTRACE_PALLAS_BASE_ROOT/lib/libeztrace-mpi.so" | grep -Ei 'otf2|pallas|eztrace' || true

echo "[rebuild-pallas-base-eztrace] Done."
echo "Activate with:"
echo "    source ~/inria/scripts/env-pallas-base-eztrace.sh"
