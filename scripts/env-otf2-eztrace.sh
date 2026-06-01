#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-otf2-eztrace.sh
#
# Activates normal OTF2 + EZTrace.
#
# Expected:
#   eztrace     -> ~/inria/eztrace/install/bin/eztrace
#   otf2-config -> ~/inria/otf2-3.0.3/install/bin/otf2-config

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"

export OTF2_VERSION="3.0.3"
export OTF2_SRC="$INRIA_ROOT/otf2-$OTF2_VERSION"
export OTF2_BUILD="$OTF2_SRC/build"
export OTF2_ROOT="$OTF2_SRC/install"

export EZTRACE_SRC="$INRIA_ROOT/eztrace"
export EZTRACE_BUILD="$EZTRACE_SRC/build"
export EZTRACE_ROOT="$EZTRACE_SRC/install"

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
#   normal eztrace first, normal otf2-config second.
_prepend_path_var PATH \
    "$EZTRACE_ROOT/bin" \
    "$OTF2_ROOT/bin"

# Runtime libs:
#   normal OTF2 lib MUST come before normal EZTrace lib,
#   because EZTrace libs depend on libotf2.
_prepend_path_var LD_LIBRARY_PATH \
    "$OTF2_ROOT/lib" \
    "$OTF2_ROOT/lib64" \
    "$EZTRACE_ROOT/lib" \
    "$EZTRACE_ROOT/lib64"

# Build discovery:
#   normal OTF2 first, then normal EZTrace.
_prepend_path_var PKG_CONFIG_PATH \
    "$OTF2_ROOT/lib/pkgconfig" \
    "$OTF2_ROOT/lib64/pkgconfig" \
    "$EZTRACE_ROOT/lib/pkgconfig" \
    "$EZTRACE_ROOT/lib64/pkgconfig"

_prepend_path_var CMAKE_PREFIX_PATH \
    "$OTF2_ROOT" \
    "$EZTRACE_ROOT"

# Clear Bash command lookup cache.
hash -r 2>/dev/null || true

echo "[env-otf2-eztrace] OTF2_ROOT=$OTF2_ROOT"
echo "[env-otf2-eztrace] EZTRACE_ROOT=$EZTRACE_ROOT"
echo "[env-otf2-eztrace] eztrace=$(command -v eztrace || true)"
echo "[env-otf2-eztrace] otf2-config=$(command -v otf2-config || true)"

if [ "$(command -v eztrace || true)" != "$EZTRACE_ROOT/bin/eztrace" ]; then
    echo "[env-otf2-eztrace] WARNING: eztrace is not from normal EZTrace."
fi

if [ "$(command -v otf2-config || true)" != "$OTF2_ROOT/bin/otf2-config" ]; then
    echo "[env-otf2-eztrace] WARNING: otf2-config is not from normal OTF2."
fi

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-otf2-eztrace] WARNING: You executed this script."
    echo "[env-otf2-eztrace] Use:"
    echo "    source ~/inria/scripts/env-otf2-eztrace.sh"
fi
