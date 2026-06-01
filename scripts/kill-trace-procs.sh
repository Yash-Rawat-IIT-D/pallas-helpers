#!/usr/bin/env bash
set -u

# Kills local MPI/EZTrace test processes owned by the current user.
# Edit this pattern if your test binary has a different name.
PATTERN='(mpirun|mpiexec|eztrace|hello_mpi|orted|prte|pmix)'

show_matches() {
    pgrep -a -u "$USER" -f "$PATTERN" || true
}

has_matches() {
    pgrep -u "$USER" -f "$PATTERN" >/dev/null 2>&1
}

echo "[kill-trace] Searching for processes matching:"
echo "    $PATTERN"
echo

if ! has_matches; then
    echo "[kill-trace] No matching processes found."
    exit 0
fi

echo "[kill-trace] Found:"
show_matches
echo

echo "[kill-trace] Sending SIGTERM..."
pkill -TERM -u "$USER" -f "$PATTERN" || true

for i in 1 2 3 4 5; do
    sleep 1
    if ! has_matches; then
        echo "[kill-trace] All processes exited after SIGTERM."
        exit 0
    fi
    echo "[kill-trace] Still waiting... ${i}s"
done

echo
echo "[kill-trace] Still alive after SIGTERM:"
show_matches
echo

echo "[kill-trace] Sending SIGKILL..."
pkill -KILL -u "$USER" -f "$PATTERN" || true

sleep 1

if has_matches; then
    echo "[kill-trace] WARNING: some processes are still alive:"
    show_matches
    exit 1
fi

echo "[kill-trace] All matching processes killed."
