#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-starpu.sh
#
# Purpose:
#   Activate local StarPU install for current shell only.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export STARPU_SRC="$INRIA_ROOT/starpu"
export STARPU_BUILD="$STARPU_SRC/build-local"
export STARPU_ROOT="$STARPU_SRC/install-starpu"

if [ ! -d "$STARPU_ROOT" ]; then
    echo "[env-starpu] ERROR: Missing local StarPU install:"
    echo "    $STARPU_ROOT"
    echo "Run:"
    echo "    bash ~/inria/scripts/rebuild-starpu.sh"
    return 1 2>/dev/null || exit 1
fi

_remove_starpu_paths() {
    local var_name="$1"
    local old_value="${!var_name-}"
    local new_value=""
    local entry

    IFS=':' read -ra entries <<< "$old_value"

    for entry in "${entries[@]}"; do
        [ -z "$entry" ] && continue

        case "$entry" in
            "$STARPU_SRC"/install*|"$STARPU_SRC"/install-starpu*)
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

_remove_starpu_paths PATH
_remove_starpu_paths LD_LIBRARY_PATH
_remove_starpu_paths PKG_CONFIG_PATH
_remove_starpu_paths CMAKE_PREFIX_PATH

_prepend_path_var PATH \
    "$STARPU_ROOT/bin"

_prepend_path_var LD_LIBRARY_PATH \
    "$STARPU_ROOT/lib" \
    "$STARPU_ROOT/lib64"

_prepend_path_var PKG_CONFIG_PATH \
    "$STARPU_ROOT/lib/pkgconfig" \
    "$STARPU_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$STARPU_ROOT"

hash -r 2>/dev/null || true

echo "[env-starpu] STARPU_SRC=$STARPU_SRC"
echo "[env-starpu] STARPU_BUILD=$STARPU_BUILD"
echo "[env-starpu] STARPU_ROOT=$STARPU_ROOT"
echo "[env-starpu] starpu_sched_display=$(command -v starpu_sched_display || true)"
echo "[env-starpu] pkg-config=$(command -v pkg-config || true)"
echo "[env-starpu] Activated StarPU environment."

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-starpu] WARNING: You executed this script."
    echo "[env-starpu] Use:"
    echo "    source ~/inria/scripts/env-starpu.sh"
fi
