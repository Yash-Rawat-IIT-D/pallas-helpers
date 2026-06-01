#!/usr/bin/env bash

if [[ -n "${_INRIA_LAYOUT_LOADED:-}" ]]; then
    return 0 2>/dev/null || exit 0
fi

readonly _INRIA_LAYOUT_LOADED=1

INRIA_SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INRIA_ROOT="$(cd -- "${INRIA_SCRIPTS_DIR}/.." && pwd)"

export INRIA_ROOT
export INRIA_SCRIPTS_DIR
