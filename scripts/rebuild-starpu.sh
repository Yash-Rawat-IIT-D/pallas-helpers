#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export STARPU_SRC="$INRIA_ROOT/starpu"
export STARPU_BUILD="$STARPU_SRC/build"
export STARPU_ROOT="$STARPU_SRC/install-starpu"

JOBS="${JOBS:-$(nproc)}"
CONFIGURE_ARGS=(--enable-cuda "$@")

if [ ! -d "$STARPU_SRC/.git" ]; then
    echo "[rebuild-starpu] ERROR: StarPU repo not found:"
    echo "    $STARPU_SRC"
    echo "Clone or create the checkout you want to build first."
    exit 1
fi

cd "$STARPU_SRC"
echo "[rebuild-starpu] Using current StarPU checkout:"
echo "    branch=$(git branch --show-current 2>/dev/null || true)"
echo "    commit=$(git rev-parse --short HEAD 2>/dev/null || true)"

if [ ! -x "$STARPU_SRC/configure" ]; then
    echo "[rebuild-starpu] configure script missing, running autogen.sh..."
    ./autogen.sh
fi

echo "[rebuild-starpu] Removing old StarPU build/install..."
rm -rf "$STARPU_BUILD" "$STARPU_ROOT"

mkdir -p "$STARPU_BUILD" "$STARPU_ROOT"

echo "[rebuild-starpu] Configuring StarPU..."
if ((${#CONFIGURE_ARGS[@]} > 0)); then
    echo "[rebuild-starpu] Extra configure args: ${CONFIGURE_ARGS[*]}"
fi

cd "$STARPU_BUILD"
"$STARPU_SRC/configure" \
    --prefix="$STARPU_ROOT" \
    "${CONFIGURE_ARGS[@]}"

echo "[rebuild-starpu] Building StarPU..."
make -j"$JOBS"

echo "[rebuild-starpu] Installing StarPU into:"
echo "    $STARPU_ROOT"
make install

echo "[rebuild-starpu] Sanity checks:"
echo "STARPU_ROOT=$STARPU_ROOT"
find "$STARPU_ROOT" -maxdepth 3 -type f \
    \( -name 'starpu*' -o -name 'libstarpu*' -o -name 'pkgconfig' \) \
    | sort || true

echo "[rebuild-starpu] Done."
echo "[rebuild-starpu] Add it to your shell with something like:"
echo "  export PATH=\"$STARPU_ROOT/bin:\$PATH\""
echo "  export LD_LIBRARY_PATH=\"$STARPU_ROOT/lib:$STARPU_ROOT/lib64:\$LD_LIBRARY_PATH\""
echo "  export PKG_CONFIG_PATH=\"$STARPU_ROOT/lib/pkgconfig:$STARPU_ROOT/lib64/pkgconfig:\$PKG_CONFIG_PATH\""
