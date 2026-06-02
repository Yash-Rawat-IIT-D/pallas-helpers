#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-pallas-eztrace.sh
#
# Activates EZTrace built against Pallas's OTF2-compatible backend.
#
# Expected:
#   eztrace     -> ~/inria/eztrace/install-pallas/bin/eztrace
#   otf2-config -> ~/inria/pallas/install-pallas/bin/otf2-config
#   pallas_print-> ~/inria/pallas/install-pallas/bin/pallas_print

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_SRC="$INRIA_ROOT/pallas"
export PALLAS_BUILD="$PALLAS_SRC/build-pallas"
export PALLAS_ROOT="$PALLAS_SRC/install-pallas"
export PALLAS_READ_BENCHMARK="$PALLAS_ROOT/bin/pallas_read_benchmark"

export EZTRACE_SRC="$INRIA_ROOT/eztrace"
export EZTRACE_PALLAS_BUILD="$EZTRACE_SRC/build-pallas"
export EZTRACE_PALLAS_ROOT="$EZTRACE_SRC/install-pallas"

_strip_inria_toolchain_paths() {
    local var_name="$1"
    local old_value="${!var_name-}"
    local new_value=""
    local entry

    IFS=':' read -ra entries <<< "$old_value"

    for entry in "${entries[@]}"; do
        [ -z "$entry" ] && continue

        case "$entry" in
            "$INRIA_ROOT"/otf2-*/install*)
                continue
                ;;
            "$INRIA_ROOT"/eztrace/install*)
                continue
                ;;
            "$INRIA_ROOT"/eztrace/install-pallas*)
                continue
                ;;
            "$INRIA_ROOT"/pallas/install*)
                continue
                ;;
            "$INRIA_ROOT"/pallas/install-pallas*)
                continue
                ;;
        esac

        if [ -z "$new_value" ]; then
            new_value="$entry"
        else
            new_value="$new_value:$entry"
        fi
    done

    export "$var_name=$new_value"
}

_prepend_path_var() {
    local var_name="$1"
    shift

    local old_value="${!var_name-}"
    local prefix=""
    local entry

    for entry in "$@"; do
        [ -z "$entry" ] && continue

        if [ -z "$prefix" ]; then
            prefix="$entry"
        else
            prefix="$prefix:$entry"
        fi
    done

    if [ -z "$old_value" ]; then
        export "$var_name=$prefix"
    else
        export "$var_name=$prefix:$old_value"
    fi
}

# Remove all old local OTF2/EZTrace/Pallas paths first.
_strip_inria_toolchain_paths PATH
_strip_inria_toolchain_paths LD_LIBRARY_PATH
_strip_inria_toolchain_paths PKG_CONFIG_PATH
_strip_inria_toolchain_paths CMAKE_PREFIX_PATH

# PATH:
#   eztrace from install-pallas should win.
#   otf2-config/pallas_print from Pallas should win.
_prepend_path_var PATH \
    "$EZTRACE_PALLAS_ROOT/bin" \
    "$PALLAS_ROOT/bin"

# Runtime libs:
#   Pallas lib MUST come before EZTrace-Pallas lib,
#   because EZTrace libs depend on libotf2.
_prepend_path_var LD_LIBRARY_PATH \
    "$PALLAS_ROOT/lib" \
    "$PALLAS_ROOT/lib64" \
    "$EZTRACE_PALLAS_ROOT/lib" \
    "$EZTRACE_PALLAS_ROOT/lib64"

# Build discovery:
#   Pallas first, then EZTrace-Pallas.
_prepend_path_var PKG_CONFIG_PATH \
    "$PALLAS_ROOT/lib/pkgconfig" \
    "$PALLAS_ROOT/lib64/pkgconfig" \
    "$EZTRACE_PALLAS_ROOT/lib/pkgconfig" \
    "$EZTRACE_PALLAS_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$PALLAS_ROOT" \
    "$EZTRACE_PALLAS_ROOT"

# Clear Bash command lookup cache.
hash -r 2>/dev/null || true

echo "[env-pallas-eztrace] PALLAS_ROOT=$PALLAS_ROOT"
echo "[env-pallas-eztrace] EZTRACE_PALLAS_ROOT=$EZTRACE_PALLAS_ROOT"
echo "[env-pallas-eztrace] eztrace=$(command -v eztrace || true)"
echo "[env-pallas-eztrace] otf2-config=$(command -v otf2-config || true)"
echo "[env-pallas-eztrace] pallas_print=$(command -v pallas_print || true)"
echo "[env-pallas-eztrace] pallas_read_benchmark=$(command -v pallas_read_benchmark || true)"

if [ "$(command -v eztrace || true)" != "$EZTRACE_PALLAS_ROOT/bin/eztrace" ]; then
    echo "[env-pallas-eztrace] WARNING: eztrace is not from EZTrace-Pallas."
fi

if [ "$(command -v otf2-config || true)" != "$PALLAS_ROOT/bin/otf2-config" ]; then
    echo "[env-pallas-eztrace] WARNING: otf2-config is not from Pallas."
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-pallas-eztrace] WARNING: You executed this script."
    echo "[env-pallas-eztrace] Use:"
    echo "    source ~/inria/scripts/env-pallas-eztrace.sh"
fi
