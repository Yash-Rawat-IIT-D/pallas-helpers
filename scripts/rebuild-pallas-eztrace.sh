#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_SRC="$INRIA_ROOT/pallas"
export PALLAS_ROOT="$PALLAS_SRC/install-pallas"

export EZTRACE_SRC="$INRIA_ROOT/eztrace"
export EZTRACE_PALLAS_BUILD="$EZTRACE_SRC/build-pallas"
export EZTRACE_PALLAS_ROOT="$EZTRACE_SRC/install-pallas"

JOBS="${JOBS:-$(nproc)}"

if [ ! -d "$PALLAS_ROOT" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: Pallas install not found:"
    echo "    $PALLAS_ROOT"
    echo "Run first:"
    echo "    rebuild-pallas"
    exit 1
fi

if [ ! -x "$PALLAS_ROOT/bin/otf2-config" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: Pallas otf2-config not found:"
    echo "    $PALLAS_ROOT/bin/otf2-config"
    exit 1
fi

if [ ! -f "$PALLAS_ROOT/lib/libotf2.so" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: Pallas libotf2.so not found:"
    echo "    $PALLAS_ROOT/lib/libotf2.so"
    exit 1
fi

if [ ! -f "$PALLAS_ROOT/include/pallas/pallas_config.h" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: Pallas config header not found:"
    echo "    $PALLAS_ROOT/include/pallas/pallas_config.h"
    exit 1
fi

if [ ! -d "$EZTRACE_SRC/.git" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: EZTrace repo not found:"
    echo "    $EZTRACE_SRC"
    echo "Clone it first:"
    echo "    cd ~/inria"
    echo "    git clone https://gitlab.com/eztrace/eztrace.git"
    exit 1
fi

echo "[rebuild-pallas-eztrace] Using current source checkouts:"
cd "$PALLAS_SRC"
echo "    pallas-branch=$(git branch --show-current 2>/dev/null || true)"
echo "    pallas-commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

cd "$EZTRACE_SRC"
echo "    eztrace-branch=$(git branch --show-current 2>/dev/null || true)"
echo "    eztrace-commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

echo "[rebuild-pallas-eztrace] Preparing Pallas libotf2 compatibility symlinks..."
cd "$PALLAS_ROOT/lib"
ln -sf libotf2.so libotf2.so.10
ln -sf libotf2.so libotf2.so.10.0.0

echo "[rebuild-pallas-eztrace] Removing old EZTrace-Pallas build/install..."
rm -rf "$EZTRACE_PALLAS_BUILD" "$EZTRACE_PALLAS_ROOT"
mkdir -p "$EZTRACE_PALLAS_BUILD" "$EZTRACE_PALLAS_ROOT"

echo "[rebuild-pallas-eztrace] Activating Pallas-backed environment..."
source "$INRIA_SCRIPTS_DIR/env-pallas-eztrace.sh"
hash -r 2>/dev/null || true

echo "[rebuild-pallas-eztrace] Critical check:"
echo "    otf2-config=$(command -v otf2-config || true)"
echo "    expected:    $PALLAS_ROOT/bin/otf2-config"

if [ "$(command -v otf2-config || true)" != "$PALLAS_ROOT/bin/otf2-config" ]; then
    echo "[rebuild-pallas-eztrace] ERROR: wrong otf2-config selected."
    exit 1
fi

echo "[rebuild-pallas-eztrace] Pallas otf2-config:"
otf2-config --version || true
otf2-config --ldflags || true
otf2-config --libs || true

# Force compile-time and link-time discovery to Pallas.
#
# Important:
# EZTrace checks `#ifdef PALLAS_VERSION`, but eztrace_otf2.c does not include
# pallas_config.h directly. So we force-include it in every C/C++ translation unit.
#
# Also put Pallas OTF2 headers/libs before any normal OTF2 installation.
PALLAS_FORCE_INCLUDE="-include $PALLAS_ROOT/include/pallas/pallas_config.h"
PALLAS_INCLUDES="-I$PALLAS_ROOT/include"
PALLAS_RPATH="-Wl,-rpath,$PALLAS_ROOT/lib"

export PATH="$PALLAS_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$PALLAS_ROOT/lib:$PALLAS_ROOT/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="$PALLAS_ROOT/lib/pkgconfig:$PALLAS_ROOT/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export CMAKE_PREFIX_PATH="$PALLAS_ROOT:${CMAKE_PREFIX_PATH:-}"

export CC="${CC:-gcc}"
export CXX="${CXX:-g++}"

export CPPFLAGS="$PALLAS_INCLUDES ${CPPFLAGS:-}"
export CFLAGS="$PALLAS_INCLUDES $PALLAS_FORCE_INCLUDE ${CFLAGS:-}"
export CXXFLAGS="$PALLAS_INCLUDES $PALLAS_FORCE_INCLUDE ${CXXFLAGS:-}"
export LDFLAGS="-L$PALLAS_ROOT/lib $PALLAS_RPATH ${LDFLAGS:-}"

echo "[rebuild-pallas-eztrace] Configuring EZTrace against Pallas OTF2 backend..."
cmake -S "$EZTRACE_SRC" -B "$EZTRACE_PALLAS_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$EZTRACE_PALLAS_ROOT" \
    -DEZTRACE_ENABLE_MPI=ON \
    -DCMAKE_PREFIX_PATH="$PALLAS_ROOT" \
    -DCMAKE_C_FLAGS="$CFLAGS" \
    -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="$LDFLAGS" \
    -DCMAKE_SHARED_LINKER_FLAGS="$LDFLAGS" \
    -DOTF2_CONFIG="$PALLAS_ROOT/bin/otf2-config" \
    -DOTF2_ROOT="$PALLAS_ROOT" \
    -DOTF2_LIBRARY="$PALLAS_ROOT/lib/libotf2.so" \
    -DOTF2_INCLUDE_DIR="$PALLAS_ROOT/include" \
    -DOTF2_INCLUDE_DIRS="$PALLAS_ROOT/include"

echo "[rebuild-pallas-eztrace] Build-cache OTF2 references:"
grep -RniE 'OTF2|otf2|pallas|otf2-3.1.1' "$EZTRACE_PALLAS_BUILD/CMakeCache.txt" 2>/dev/null | head -120 || true

echo "[rebuild-pallas-eztrace] Building..."
cmake --build "$EZTRACE_PALLAS_BUILD" -j"$JOBS"

echo "[rebuild-pallas-eztrace] Installing..."
cmake --install "$EZTRACE_PALLAS_BUILD"

echo "[rebuild-pallas-eztrace] Final activation..."
source "$INRIA_SCRIPTS_DIR/env-pallas-eztrace.sh"
hash -r 2>/dev/null || true

echo "[rebuild-pallas-eztrace] Sanity checks:"
echo "    eztrace=$(command -v eztrace || true)"
echo "    otf2-config=$(command -v otf2-config || true)"
echo "    pallas_print=$(command -v pallas_print || true)"

eztrace --version || true
otf2-config --version || true

echo "[rebuild-pallas-eztrace] Checking whether EZTrace compiled Pallas-specific code..."
if strings "$EZTRACE_PALLAS_ROOT/lib/libeztrace-lib.so" | grep -F "Using Pallas" >/dev/null; then
    echo "    OK: Pallas-specific EZTrace code is present."
    strings "$EZTRACE_PALLAS_ROOT/lib/libeztrace-lib.so" | grep -F "Using Pallas" || true
else
    echo "    WARNING: Could not find 'Using Pallas' string in libeztrace-lib.so."
    echo "    This may mean PALLAS_VERSION code path was not compiled."
fi

echo "[rebuild-pallas-eztrace] Runtime linking checks:"
echo "--- libeztrace-lib.so"
ldd "$EZTRACE_PALLAS_ROOT/lib/libeztrace-lib.so" | grep -Ei 'otf2|pallas|eztrace' || true

echo "--- libeztrace-mpi.so"
ldd "$EZTRACE_PALLAS_ROOT/lib/libeztrace-mpi.so" | grep -Ei 'otf2|pallas|eztrace' || true

echo "[rebuild-pallas-eztrace] Done."
echo "Activate with:"
echo "    source ~/inria/scripts/env-pallas-eztrace.sh"
