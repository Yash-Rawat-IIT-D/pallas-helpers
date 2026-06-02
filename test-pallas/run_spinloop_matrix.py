#!/usr/bin/env python3

import argparse
from datetime import datetime
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "pallas" / "install-pallas" / "etc" / "pallas.config"
DEFAULT_ENV_SCRIPT = ROOT / "scripts" / "env-pallas-eztrace.sh"
DEFAULT_KILL_SCRIPT = ROOT / "scripts" / "kill-trace-procs.sh"
DEFAULT_MATRIX = TEST_ROOT / "spinloop_matrix.json"
DEFAULT_OUTPUT = TEST_ROOT
DEFAULT_EXECUTABLE = TEST_ROOT / "mpi_test_spinloop"
DEFAULT_SOURCE = TEST_ROOT / "mpi_test_spinloop.c"
TIMEOUT_SECONDS = 30 * 60
STATUS_OK = 0
STATUS_FAILED = 1
STATUS_TIMEOUT = 2
STATUS_TRACE_MISSING = 3
STATUS_BUILD_FAILED = 4
STATUS_READ_BENCHMARK_FAILED = 5
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def load_matrix(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Matrix JSON must be a list.")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Matrix entry {index} must be an object.")
    return data


def load_config_lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def extract_benchmark_constants(path: Path) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    patterns = {
        "iterations": r"const\s+int\s+iterations\s*=\s*([^;]+);",
        "delay_us": r"const\s+long\s+delay_us\s*=\s*([^;]+);",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, source)
        result[key] = match.group(1).strip() if match else "UNKNOWN"
    return result


def apply_overrides(lines: list[str], overrides: dict[str, object]) -> str:
    rendered = []
    remaining = {str(key): str(value) for key, value in overrides.items()}

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rendered.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in remaining:
            rendered.append(f"{key}={remaining.pop(key)}")
        else:
            rendered.append(line)

    for key, value in remaining.items():
        rendered.append(f"{key}={value}")

    return "\n".join(rendered) + "\n"


def append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message)
        if not message.endswith("\n"):
            handle.write("\n")


def run_kill_trace(log_path: Path, kill_script: Path) -> None:
    result = subprocess.run(
        ["bash", str(kill_script)],
        text=True,
        capture_output=True,
        check=False,
    )
    append_log(log_path, "$ bash " + str(kill_script))
    if result.stdout:
        append_log(log_path, result.stdout)
    if result.stderr:
        append_log(log_path, result.stderr)
    append_log(log_path, f"kill_trace_returncode={result.returncode}\n")


def status_name(status: int) -> str:
    return {
        STATUS_OK: "ok",
        STATUS_FAILED: "failed",
        STATUS_TIMEOUT: "timeout",
        STATUS_TRACE_MISSING: "trace_missing",
        STATUS_BUILD_FAILED: "build_failed",
        STATUS_READ_BENCHMARK_FAILED: "read_benchmark_failed",
    }.get(status, "unknown")


def print_case_status(index: int, status: int, elapsed_seconds: int, case_dir: Path) -> None:
    color = GREEN if status == STATUS_OK else RED
    print(f"{color}test_{index}: {status_name(status)} [{elapsed_seconds} sec]{RESET} ({case_dir})")


def print_build_status(status: int, log_path: Path) -> None:
    color = GREEN if status == STATUS_OK else RED
    print(f"{color}build: {status_name(status)}{RESET} ({log_path})")


def run_build(output_dir: Path) -> int:
    build_log = output_dir / "build.log"
    with build_log.open("w", encoding="utf-8") as handle:
        for command in (["make", "clean"], ["make"]):
            handle.write("$ " + " ".join(command) + "\n")
            handle.flush()
            result = subprocess.run(
                command,
                cwd=TEST_ROOT,
                text=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
            handle.write(f"returncode={result.returncode}\n\n")
            handle.flush()
            if result.returncode != 0:
                return STATUS_BUILD_FAILED
    return STATUS_OK


def run_test_case(
    index: int,
    overrides: dict[str, str],
    output_dir: Path,
    base_lines: list[str],
    env_script: Path,
    kill_script: Path,
    executable: Path,
    trace_dir_name: str,
) -> int:
    start_time = time.perf_counter()
    case_dir = output_dir / f"test_{index}"
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)

    run_log = case_dir / "run.log"
    config_path = case_dir / "pallas.config"
    stdout_path = case_dir / "stdout.txt"
    stderr_path = case_dir / "stderr.txt"
    read_benchmark_stdout_path = case_dir / "read_benchmark_stdout.txt"
    read_benchmark_stderr_path = case_dir / "read_benchmark_stderr.txt"

    config_path.write_text(apply_overrides(base_lines, overrides), encoding="utf-8")
    append_log(run_log, f"test_index={index}")
    append_log(run_log, f"config_path={config_path}")
    append_log(run_log, f"overrides={json.dumps(overrides, sort_keys=True)}\n")

    run_kill_trace(run_log, kill_script)

    command = (
        f"source {shlex.quote(str(env_script))} && "
        f"export PALLAS_CONFIG_PATH={shlex.quote(str(config_path))} && "
        f"mpirun -np 2 eztrace -m -t mpi {shlex.quote(str(executable))}"
    )
    append_log(run_log, "$ bash -lc " + command + "\n")

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=case_dir,
                text=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            append_log(run_log, f"status=completed\nreturncode={result.returncode}\n")
        except subprocess.TimeoutExpired:
            elapsed_seconds = int(time.perf_counter() - start_time)
            append_log(run_log, f"status=timeout\ntimeout_seconds={TIMEOUT_SECONDS}\nelapsed_seconds={elapsed_seconds}\n")
            run_kill_trace(run_log, kill_script)
            return STATUS_TIMEOUT, elapsed_seconds

    run_kill_trace(run_log, kill_script)

    trace_dir = case_dir / trace_dir_name
    if trace_dir.exists():
        append_log(run_log, f"trace_dir={trace_dir}\n")
    else:
        elapsed_seconds = int(time.perf_counter() - start_time)
        append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
        append_log(run_log, f"trace_dir_missing={trace_dir_name}\n")
        return STATUS_TRACE_MISSING, elapsed_seconds

    trace_file = trace_dir / "eztrace_log.pallas"
    if not trace_file.exists():
        elapsed_seconds = int(time.perf_counter() - start_time)
        append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
        append_log(run_log, f"trace_file_missing={trace_file}\n")
        return STATUS_TRACE_MISSING, elapsed_seconds

    benchmark_command = (
        f"source {shlex.quote(str(env_script))} && "
        f"pallas_read_benchmark {shlex.quote(str(trace_file))}"
    )
    append_log(run_log, "$ bash -lc " + benchmark_command + "\n")

    with read_benchmark_stdout_path.open("w", encoding="utf-8") as stdout_handle, read_benchmark_stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        benchmark_result = subprocess.run(
            ["bash", "-lc", benchmark_command],
            cwd=case_dir,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )

    benchmark_report_path = trace_file.with_suffix(".read_benchmark.txt")
    append_log(
        run_log,
        "\n".join(
            [
                "read_benchmark_status=completed",
                f"read_benchmark_returncode={benchmark_result.returncode}",
                f"read_benchmark_trace_file={trace_file}",
                f"read_benchmark_report={benchmark_report_path}",
                "",
            ]
        ),
    )

    if benchmark_result.returncode != 0:
        elapsed_seconds = int(time.perf_counter() - start_time)
        append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
        return STATUS_READ_BENCHMARK_FAILED, elapsed_seconds

    elapsed_seconds = int(time.perf_counter() - start_time)
    append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
    if result.returncode != 0:
        return STATUS_FAILED, elapsed_seconds
    return STATUS_OK, elapsed_seconds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-script", type=Path, default=DEFAULT_ENV_SCRIPT)
    parser.add_argument("--kill-script", type=Path, default=DEFAULT_KILL_SCRIPT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()

    executable = args.executable.resolve()
    source_path = args.source.resolve()
    matrix_path = args.matrix.resolve()
    matrix = load_matrix(matrix_path)
    benchmark_constants = extract_benchmark_constants(source_path)
    base_lines = load_config_lines(args.config.resolve())
    output_root = args.output_dir.resolve()
    output_dir = output_root / ("test-run-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(matrix_path, output_dir / matrix_path.name)
    (output_dir / "benchmark_build.txt").write_text(
        "\n".join(
            [
                f"source={source_path}",
                f"executable={executable}",
                f"iterations={benchmark_constants['iterations']}",
                f"delay_us={benchmark_constants['delay_us']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    build_status = run_build(output_dir)
    print_build_status(build_status, output_dir / "build.log")
    if build_status != STATUS_OK:
        return 1

    trace_dir_name = executable.name + "_trace"
    overall_status = STATUS_OK

    for index, overrides in enumerate(matrix):
        status, elapsed_seconds = run_test_case(
            index=index,
            overrides=overrides,
            output_dir=output_dir,
            base_lines=base_lines,
            env_script=args.env_script.resolve(),
            kill_script=args.kill_script.resolve(),
            executable=executable,
            trace_dir_name=trace_dir_name,
        )
        print_case_status(index, status, elapsed_seconds, output_dir / f"test_{index}")
        if status != STATUS_OK:
            overall_status = status

    return 0 if overall_status == STATUS_OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
