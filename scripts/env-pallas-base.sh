#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-pallas-base.sh
#
# Purpose:
#   Activate baseline Pallas install from ~/inria/pallas-base for current shell only.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_BASE_SRC="$INRIA_ROOT/pallas-base"
export PALLAS_BASE_BUILD="$PALLAS_BASE_SRC/build-pallas"
export PALLAS_BASE_ROOT="$PALLAS_BASE_SRC/install-pallas"

if [ -f "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh" ]; then
    source "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh"
fi

_remove_pallas_base_paths() {
    local var_name="$1"
    local old_value="${!var_name-}"
    local new_value=""
    local entry

    IFS=':' read -ra entries <<< "$old_value"

    for entry in "${entries[@]}"; do
        [ -z "$entry" ] && continue

        case "$entry" in
            "$PALLAS_BASE_SRC"/install*|"$PALLAS_BASE_SRC"/install-pallas*)
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

_remove_pallas_base_paths PATH
_remove_pallas_base_paths LD_LIBRARY_PATH
_remove_pallas_base_paths PKG_CONFIG_PATH
_remove_pallas_base_paths CMAKE_PREFIX_PATH

_prepend_path_var PATH \
    "$PALLAS_BASE_ROOT/bin"

_prepend_path_var LD_LIBRARY_PATH \
    "$PALLAS_BASE_ROOT/lib" \
    "$PALLAS_BASE_ROOT/lib64"

_prepend_path_var PKG_CONFIG_PATH \
    "$PALLAS_BASE_ROOT/lib/pkgconfig" \
    "$PALLAS_BASE_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$PALLAS_BASE_ROOT"

echo "[env-pallas-base] PALLAS_BASE_SRC=$PALLAS_BASE_SRC"
echo "[env-pallas-base] PALLAS_BASE_BUILD=$PALLAS_BASE_BUILD"
echo "[env-pallas-base] PALLAS_BASE_ROOT=$PALLAS_BASE_ROOT"
echo "[env-pallas-base] Activated baseline Pallas environment."
echo "[env-pallas-base] otf2-config=$(command -v otf2-config || true)"
echo "[env-pallas-base] pallas_print=$(command -v pallas_print || true)"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-pallas-base] WARNING: You executed this script."
    echo "[env-pallas-base] Use:"
    echo "    source ~/inria/scripts/env-pallas-base.sh"
fi
