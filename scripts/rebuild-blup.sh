#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_inria-layout.sh"
export BLUP_SRC="$INRIA_ROOT/blup"

# Important:
# Blup uses BLUP_CONFIG/venv internally.
# Keep this aligned with env-blup.sh.
export BLUP_CONFIG="$INRIA_ROOT/blup-config"
export BLUP_VENV="$BLUP_CONFIG/venv"

if [ ! -d "$BLUP_SRC/.git" ]; then
    echo "[rebuild-blup] ERROR: Blup repo not found at $BLUP_SRC"
    echo "[rebuild-blup] Clone it first:"
    echo "  cd ~/inria"
    echo "  git clone -b dev https://gitlab.inria.fr/blup/blup.git"
    exit 1
fi

echo "[rebuild-blup] Updating Blup dev branch..."
cd "$BLUP_SRC"
git fetch origin
git checkout dev
git pull origin dev

echo "[rebuild-blup] Removing old Blup config/venv..."
rm -rf "$BLUP_CONFIG"
mkdir -p "$BLUP_CONFIG"

echo "[rebuild-blup] Creating Blup venv at $BLUP_VENV..."
python3 -m venv "$BLUP_VENV"

source "$BLUP_VENV/bin/activate"

python -m pip install --upgrade pip setuptools wheel

echo "[rebuild-blup] Installing Blup from local dev checkout..."
cd "$BLUP_SRC"

if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
    pip install -e .
else
    echo "[rebuild-blup] No pyproject.toml/setup.py found."
    echo "[rebuild-blup] Blup may install its dependencies on first run."
fi

echo "[rebuild-blup] Installing OTF2 Python package into Blup venv..."
pip install otf2 || {
    echo "[rebuild-blup] WARNING: pip install otf2 failed."
    echo "[rebuild-blup] If Blup still says 'No module named otf2', we need another OTF2 Python binding route."
}

echo "[rebuild-blup] Sanity checks..."
echo "[rebuild-blup] python=$(which python)"
python --version

echo "[rebuild-blup] blup=$(command -v blup || true)"
blup --help || true

echo "[rebuild-blup] Testing Python import otf2..."
python -c "import otf2; print(otf2)" || true

echo "[rebuild-blup] Done."
echo "[rebuild-blup] Activate with:"
echo "  source ~/inria/scripts/env-blup.sh"
