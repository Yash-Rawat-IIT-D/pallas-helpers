#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-chameleon.sh
#
# Purpose:
#   Activate local Chameleon install for the current shell only.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export CHAMELEON_SRC="$INRIA_ROOT/chameleon"
export CHAMELEON_BUILD="$CHAMELEON_SRC/build-chameleon"
export CHAMELEON_ROOT="$CHAMELEON_SRC/install-chameleon"

if [ -f "$INRIA_SCRIPTS_DIR/env-starpu.sh" ]; then
    source "$INRIA_SCRIPTS_DIR/env-starpu.sh"
fi

if [ ! -d "$CHAMELEON_ROOT" ]; then
    echo "[env-chameleon] ERROR: Missing local Chameleon install:"
    echo "    $CHAMELEON_ROOT"
    echo "Run:"
    echo "    bash ~/inria/scripts/rebuild-chameleon.sh"
    return 1 2>/dev/null || exit 1
fi

_remove_chameleon_paths() {
    local var_name="$1"
    local old_value="${!var_name-}"
    local new_value=""
    local entry

    IFS=':' read -ra entries <<< "$old_value"

    for entry in "${entries[@]}"; do
        [ -z "$entry" ] && continue

        case "$entry" in
            "$CHAMELEON_SRC"/install*|"$CHAMELEON_SRC"/install-chameleon*)
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

_remove_chameleon_paths PATH
_remove_chameleon_paths LD_LIBRARY_PATH
_remove_chameleon_paths PKG_CONFIG_PATH
_remove_chameleon_paths CMAKE_PREFIX_PATH

_prepend_path_var PATH \
    "$CHAMELEON_ROOT/bin"

_prepend_path_var LD_LIBRARY_PATH \
    "$CHAMELEON_ROOT/lib" \
    "$CHAMELEON_ROOT/lib64"

_prepend_path_var PKG_CONFIG_PATH \
    "$CHAMELEON_ROOT/lib/pkgconfig" \
    "$CHAMELEON_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$CHAMELEON_ROOT"

hash -r 2>/dev/null || true

echo "[env-chameleon] CHAMELEON_SRC=$CHAMELEON_SRC"
echo "[env-chameleon] CHAMELEON_BUILD=$CHAMELEON_BUILD"
echo "[env-chameleon] CHAMELEON_ROOT=$CHAMELEON_ROOT"
echo "[env-chameleon] pkg-config=$(command -v pkg-config || true)"
echo "[env-chameleon] Activated Chameleon environment."

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-chameleon] WARNING: You executed this script."
    echo "[env-chameleon] Use:"
    echo "    source ~/inria/scripts/env-chameleon.sh"
fi
