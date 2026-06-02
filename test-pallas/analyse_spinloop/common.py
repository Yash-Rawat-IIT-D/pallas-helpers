import argparse
import ctypes
import importlib
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PALLAS_LIB_CANDIDATES = (
    ROOT / "pallas" / "install-pallas" / "lib" / "libpallas.so",
    ROOT / "pallas" / "install-pallas" / "lib64" / "libpallas.so",
    ROOT / "pallas" / "build-pallas" / "libraries" / "pallas" / "libpallas.so",
)
PALLAS_TRACE_PATH_CANDIDATES = (
    ROOT / "pallas" / "libraries" / "pallas_python",
)


def preload_pallas_library():
    for candidate in PALLAS_LIB_CANDIDATES:
        if not candidate.exists():
            continue
        lib_dir = str(candidate.parent)
        current = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_dir not in current.split(":"):
            os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{current}" if current else lib_dir
        ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
        return candidate
    return None


def add_local_pallas_trace_path():
    for candidate in PALLAS_TRACE_PATH_CANDIDATES:
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return candidate
    return None


def import_pallas_trace():
    global local_pallas_trace_path
    try:
        return importlib.import_module("pallas_trace")
    except ModuleNotFoundError as exc:
        if exc.name != "pallas_trace":
            raise
        local_pallas_trace_path = add_local_pallas_trace_path()
        return importlib.import_module("pallas_trace")


preloaded_lib = None
local_pallas_trace_path = None
try:
    pallas_trace = importlib.import_module("pallas_trace")
except ImportError as exc:
    try:
        preloaded_lib = preload_pallas_library()
        pallas_trace = import_pallas_trace()
    except ImportError as retry_exc:
        print(f"Failed to import pallas_trace: {retry_exc}", file=sys.stderr)
        if preloaded_lib is None:
            print("Tried to preload libpallas.so from:", file=sys.stderr)
            for candidate in PALLAS_LIB_CANDIDATES:
                print(f"  - {candidate}", file=sys.stderr)
        if local_pallas_trace_path is None:
            print("Tried to add pallas_trace from:", file=sys.stderr)
            for candidate in PALLAS_TRACE_PATH_CANDIDATES:
                print(f"  - {candidate}", file=sys.stderr)
        if "pallas_trace._core" in str(retry_exc):
            print(
                "Hint: the Python bindings are not built/installed for this interpreter. "
                "Use the venv where pallas_trace was installed, or build/install the Pallas Python module.",
                file=sys.stderr,
            )
        else:
            print(
                "Hint: activate the venv and ensure libpallas.so is reachable via LD_LIBRARY_PATH.",
                file=sys.stderr,
            )
        sys.exit(1)
    except OSError as retry_exc:
        print(f"Failed to preload libpallas.so: {retry_exc}", file=sys.stderr)
        print("Tried these libpallas.so locations:", file=sys.stderr)
        for candidate in PALLAS_LIB_CANDIDATES:
            print(f"  - {candidate}", file=sys.stderr)
        sys.exit(1)


MPI_NAME_FILTERS = ("MPI_Test", "MPI_Irecv", "MPI_Isend", "MPI_Wait", "MPI_Barrier")
RELEVANT_FILE_PARTS = ("duration", "sequence", "event", "token", "timestamp")
DEBUG_ATTR_PARTS = ("token", "event", "sequence", "duration", "timestamp", "archive", "thread")
DEFAULT_SUBARRAY_BATCH_SIZE = 1000


def parse_args():
    parser = argparse.ArgumentParser(
        description="Explore a Pallas trace produced by the MPI spin-loop benchmark."
    )
    parser.add_argument("trace_path", help="Path to a trace root, archive directory, or .pallas file.")
    parser.add_argument(
        "--thread",
        type=int,
        default=1,
        help="Preferred archive/thread selector. Defaults to archive id 1 for the spin-loop case.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=30,
        help="How many high-level tokens to print from the selected thread.",
    )
    parser.add_argument(
        "--debug-api",
        action="store_true",
        help="Print compact API surface details for pallas_trace objects.",
    )
    parser.add_argument(
        "--no-file-sizes",
        action="store_true",
        help="Skip direct archive file-size inspection.",
    )
    return parser.parse_args()


def safe_getattr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def vector_to_list(vec):
    if vec is None:
        return []
    try:
        return list(vec)
    except Exception:
        return []


def summarize_numeric_series(values, label, preview_count=8):
    if not values:
        print(f"{label}: no data")
        return
    print(f"{label}: count={len(values)}")
    print(
        f"  min={min(values)} max={max(values)} mean={statistics.fmean(values):.3f} "
        f"median={statistics.median(values):.3f} total={sum(values)}"
    )
    print(f"  first_values={values[:preview_count]}")


def print_unavailable(field):
    print(f"Unavailable through current pallas_trace API: {field}")


def resolve_trace_file(input_path):
    path = Path(input_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"path does not exist: {path}")

    if path.is_file():
        if path.name == "archive.pallas":
            parent_trace = path.parent.parent / "eztrace_log.pallas"
            if parent_trace.exists():
                return parent_trace.resolve()
        return path.resolve()

    candidates = []
    preferred = path / "eztrace_log.pallas"
    if preferred.exists():
        return preferred.resolve()

    if path.name.startswith("archive_") or path.name.startswith("archive-"):
        parent_trace = path.parent / "eztrace_log.pallas"
        if parent_trace.exists():
            return parent_trace.resolve()
        archive_file = path / "archive.pallas"
        if archive_file.exists():
            return archive_file.resolve()

    candidates.extend(sorted(path.glob("*.pallas")))
    if len(candidates) == 1:
        return candidates[0].resolve()
    if candidates:
        for candidate in candidates:
            if candidate.name == "eztrace_log.pallas":
                return candidate.resolve()
        return candidates[0].resolve()

    raise FileNotFoundError(f"could not resolve a .pallas trace file from: {path}")


def load_trace(trace_file):
    return pallas_trace.open_trace(str(trace_file))


def select_archive(trace, selector):
    archives = list(safe_getattr(trace, "archives", []) or [])
    if not archives:
        return None, None

    for archive in archives:
        if safe_getattr(archive, "id") == selector:
            return archive, f"matched archive id {selector}"

    if 0 <= selector < len(archives):
        return archives[selector], f"matched archive list index {selector}"

    return archives[0], f"fell back to first archive id {safe_getattr(archives[0], 'id')}"


def select_thread(archive, selector):
    threads = list(safe_getattr(archive, "threads", []) or [])
    if not threads:
        return None, None

    for thread in threads:
        if safe_getattr(thread, "id") == selector:
            return thread, f"matched thread id {selector}"

    return threads[0], f"fell back to first thread id {safe_getattr(threads[0], 'id')}"


def find_archive_directory(trace_file, archive):
    archive_dir_name = f"archive_{safe_getattr(archive, 'id')}"
    trace_root = trace_file.parent
    candidate = trace_root / archive_dir_name
    if candidate.is_dir():
        return candidate

    for child in trace_root.iterdir():
        if child.is_dir() and child.name in {
            archive_dir_name,
            archive_dir_name.replace("_", "-"),
            f"thread_{safe_getattr(archive, 'id')}",
        }:
            return child

    return trace_root


def file_size_report(trace_file, archive):
    print("=== Archive File Sizes ===")
    if archive is None:
        print_unavailable("archive file sizes")
        return

    archive_dir = find_archive_directory(trace_file, archive)
    print(f"archive_directory={archive_dir}")

    rows = []
    for file_path in archive_dir.rglob("*"):
        if not file_path.is_file():
            continue
        lower_name = file_path.name.lower()
        if not any(part in lower_name for part in RELEVANT_FILE_PARTS):
            continue
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        rows.append((size, file_path))

    if not rows:
        print("No matching duration/sequence/event/token/timestamp files found.")
        return

    for size, file_path in sorted(rows, key=lambda item: item[0], reverse=True):
        rel = file_path.relative_to(trace_file.parent)
        print(f"{size:12d}  {rel}")


def print_relevant_attrs(name, obj):
    attrs = [attr for attr in dir(obj) if not attr.startswith("_")]
    relevant = [attr for attr in attrs if any(part in attr.lower() for part in DEBUG_ATTR_PARTS)]
    print(f"{name}_dir={attrs}")
    print(f"{name}_relevant_attrs={relevant}")


def print_api_debug(trace, archive, thread):
    print("=== API Debug ===")
    print_relevant_attrs("pallas_trace", pallas_trace)
    if trace is not None:
        print_relevant_attrs("trace", trace)
    if archive is not None:
        print_relevant_attrs("archive", archive)
    if thread is not None:
        print_relevant_attrs("thread", thread)
