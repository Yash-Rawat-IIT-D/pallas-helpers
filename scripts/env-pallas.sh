#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-pallas.sh
#
# Purpose:
#   Activate local Pallas install for current shell only.
#   Pallas paths are prepended after loading normal OTF2/EZTrace env,
#   so Pallas's OTF2-compatible tools/libs win.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export PALLAS_SRC="$INRIA_ROOT/pallas"
export PALLAS_BUILD="$PALLAS_SRC/build-pallas"
export PALLAS_ROOT="$PALLAS_SRC/install-pallas"

# Load normal OTF2/EZTrace env first.
# Then we prepend Pallas below, so Pallas wins.
if [ -f "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh" ]; then
    source "$INRIA_SCRIPTS_DIR/env-otf2-eztrace.sh"
fi

_remove_pallas_paths() {
    local var_name="$1"
    local old_value="${!var_name-}"
    local new_value=""
    local entry

    IFS=':' read -ra entries <<< "$old_value"

    for entry in "${entries[@]}"; do
        [ -z "$entry" ] && continue

        case "$entry" in
            "$PALLAS_SRC"/install*|"$PALLAS_SRC"/install-pallas*)
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

_remove_pallas_paths PATH
_remove_pallas_paths LD_LIBRARY_PATH
_remove_pallas_paths PKG_CONFIG_PATH
_remove_pallas_paths CMAKE_PREFIX_PATH

_prepend_path_var PATH \
    "$PALLAS_ROOT/bin"

_prepend_path_var LD_LIBRARY_PATH \
    "$PALLAS_ROOT/lib" \
    "$PALLAS_ROOT/lib64"

_prepend_path_var PKG_CONFIG_PATH \
    "$PALLAS_ROOT/lib/pkgconfig" \
    "$PALLAS_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$PALLAS_ROOT"

echo "[env-pallas] PALLAS_SRC=$PALLAS_SRC"
echo "[env-pallas] PALLAS_BUILD=$PALLAS_BUILD"
echo "[env-pallas] PALLAS_ROOT=$PALLAS_ROOT"
echo "[env-pallas] Activated Pallas environment."
echo "[env-pallas] otf2-config=$(command -v otf2-config || true)"
echo "[env-pallas] pallas_print=$(command -v pallas_print || true)"

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-pallas] WARNING: You executed this script."
    echo "[env-pallas] Use:"
    echo "    source ~/inria/scripts/env-pallas.sh"
fi
