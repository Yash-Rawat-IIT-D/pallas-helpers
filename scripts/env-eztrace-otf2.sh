#!/usr/bin/env bash
# Source this file, do not execute it:
#   source ~/inria/scripts/env-eztrace-otf2.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

# Local source installs
export OTF2_ROOT="$INRIA_ROOT/otf2-3.0.3/install"
export EZTRACE_ROOT="$INRIA_ROOT/eztrace/install"

# Executables
export PATH="$OTF2_ROOT/bin:$EZTRACE_ROOT/bin:$PATH"

# Runtime libraries
export LD_LIBRARY_PATH="$OTF2_ROOT/lib:$OTF2_ROOT/lib64:$EZTRACE_ROOT/lib:$EZTRACE_ROOT/lib64:${LD_LIBRARY_PATH:-}"

# pkg-config discovery
export PKG_CONFIG_PATH="$OTF2_ROOT/lib/pkgconfig:$OTF2_ROOT/lib64/pkgconfig:$EZTRACE_ROOT/lib/pkgconfig:$EZTRACE_ROOT/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"

# CMake package discovery
export CMAKE_PREFIX_PATH="$OTF2_ROOT:$EZTRACE_ROOT:${CMAKE_PREFIX_PATH:-}"

# Optional convenience
export OTF2_BINDIR="$OTF2_ROOT/bin"
export EZTRACE_BINDIR="$EZTRACE_ROOT/bin"

echo "[env] OTF2_ROOT=$OTF2_ROOT"
echo "[env] EZTRACE_ROOT=$EZTRACE_ROOT"
echo "[env] PATH updated"
echo "[env] LD_LIBRARY_PATH updated"
echo "[env] PKG_CONFIG_PATH updated"
echo "[env] CMAKE_PREFIX_PATH updated"
