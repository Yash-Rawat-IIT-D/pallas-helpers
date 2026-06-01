#!/usr/bin/env bash
# Usage:
#   source ~/inria/scripts/env-blup.sh
#
# This only activates Blup's Python environment.
# It intentionally does NOT source env-otf2-eztrace.sh or env-pallas-eztrace.sh.
#
# Correct usage:
#   source ~/inria/scripts/env-pallas-eztrace.sh   # for .pallas traces
#   source ~/inria/scripts/env-blup.sh
#
# or:
#   source ~/inria/scripts/env-otf2-eztrace.sh     # for .otf2 traces
#   source ~/inria/scripts/env-blup.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"
export BLUP_SRC="$INRIA_ROOT/blup"

export BLUP_CONFIG="$INRIA_ROOT/blup-config"
export BLUP_VENV="$BLUP_CONFIG/venv"

if [ ! -d "$BLUP_VENV" ]; then
    echo "[env-blup] ERROR: Missing Blup venv:"
    echo "    $BLUP_VENV"
    echo "Run:"
    echo "    rebuild-blup"
    return 1 2>/dev/null || exit 1
fi

source "$BLUP_VENV/bin/activate"

# Prefer local Blup checkout.
export PATH="$BLUP_SRC:$PATH"

hash -r 2>/dev/null || true

echo "[env-blup] BLUP_SRC=$BLUP_SRC"
echo "[env-blup] BLUP_CONFIG=$BLUP_CONFIG"
echo "[env-blup] BLUP_VENV=$BLUP_VENV"
echo "[env-blup] python=$(command -v python || true)"
echo "[env-blup] blup=$(command -v blup || true)"
echo "[env-blup] Activated Blup environment."

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[env-blup] WARNING: You executed this script."
    echo "[env-blup] Use:"
    echo "    source ~/inria/scripts/env-blup.sh"
fi
