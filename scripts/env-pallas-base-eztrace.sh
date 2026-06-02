#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-pallas-base-eztrace.sh
#
# Activates EZTrace built against baseline Pallas from ~/inria/pallas-base.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_BASE_SRC="$INRIA_ROOT/pallas-base"
export PALLAS_BASE_BUILD="$PALLAS_BASE_SRC/build-pallas"
export PALLAS_BASE_ROOT="$PALLAS_BASE_SRC/install-pallas"
export PALLAS_BASE_READ_BENCHMARK="$PALLAS_BASE_ROOT/bin/pallas_read_benchmark"

export EZTRACE_SRC="$INRIA_ROOT/eztrace"
export EZTRACE_PALLAS_BASE_BUILD="$EZTRACE_SRC/build-pallas-base"
export EZTRACE_PALLAS_BASE_ROOT="$EZTRACE_SRC/install-pallas-base"

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
            "$INRIA_ROOT"/eztrace/install-pallas-base*)
                continue
                ;;
            "$INRIA_ROOT"/pallas/install*)
                continue
                ;;
            "$INRIA_ROOT"/pallas/install-pallas*)
                continue
                ;;
            "$INRIA_ROOT"/pallas-base/install*)
                continue
                ;;
            "$INRIA_ROOT"/pallas-base/install-pallas*)
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

_strip_inria_toolchain_paths PATH
_strip_inria_toolchain_paths LD_LIBRARY_PATH
_strip_inria_toolchain_paths PKG_CONFIG_PATH
_strip_inria_toolchain_paths CMAKE_PREFIX_PATH

_prepend_path_var PATH \
    "$EZTRACE_PALLAS_BASE_ROOT/bin" \
    "$PALLAS_BASE_ROOT/bin"

_prepend_path_var LD_LIBRARY_PATH \
    "$PALLAS_BASE_ROOT/lib" \
    "$PALLAS_BASE_ROOT/lib64" \
    "$EZTRACE_PALLAS_BASE_ROOT/lib" \
    "$EZTRACE_PALLAS_BASE_ROOT/lib64"

_prepend_path_var PKG_CONFIG_PATH \
    "$PALLAS_BASE_ROOT/lib/pkgconfig" \
    "$PALLAS_BASE_ROOT/lib64/pkgconfig" \
    "$EZTRACE_PALLAS_BASE_ROOT/lib/pkgconfig" \
    "$EZTRACE_PALLAS_BASE_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$PALLAS_BASE_ROOT" \
    "$EZTRACE_PALLAS_BASE_ROOT"

hash -r 2>/dev/null || true

echo "[env-pallas-base-eztrace] PALLAS_BASE_ROOT=$PALLAS_BASE_ROOT"
echo "[env-pallas-base-eztrace] EZTRACE_PALLAS_BASE_ROOT=$EZTRACE_PALLAS_BASE_ROOT"
echo "[env-pallas-base-eztrace] eztrace=$(command -v eztrace || true)"
echo "[env-pallas-base-eztrace] otf2-config=$(command -v otf2-config || true)"
echo "[env-pallas-base-eztrace] pallas_print=$(command -v pallas_print || true)"
echo "[env-pallas-base-eztrace] pallas_read_benchmark=$(command -v pallas_read_benchmark || true)"

if [ "$(command -v eztrace || true)" != "$EZTRACE_PALLAS_BASE_ROOT/bin/eztrace" ]; then
    echo "[env-pallas-base-eztrace] WARNING: eztrace is not from EZTrace-Pallas-base."
fi

if [ "$(command -v otf2-config || true)" != "$PALLAS_BASE_ROOT/bin/otf2-config" ]; then
    echo "[env-pallas-base-eztrace] WARNING: otf2-config is not from baseline Pallas."
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-pallas-base-eztrace] WARNING: You executed this script."
    echo "[env-pallas-base-eztrace] Use:"
    echo "    source ~/inria/scripts/env-pallas-base-eztrace.sh"
fi
