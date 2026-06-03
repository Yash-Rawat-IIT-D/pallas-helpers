#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
DEFAULT_RUNNER_CONFIG = TEST_ROOT / "tc_runner.json"
DEFAULT_ENV_SCRIPT = ROOT / "scripts" / "env-pallas-eztrace.sh"
DEFAULT_KILL_SCRIPT = ROOT / "scripts" / "kill-trace-procs.sh"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


class RunStatus(IntEnum):
    OK = 0
    FAILED = 1
    TIMEOUT = 2
    TRACE_MISSING = 3
    READ_BENCHMARK_FAILED = 4

    @property
    def label(self) -> str:
        return {
            RunStatus.OK: "ok",
            RunStatus.FAILED: "failed",
            RunStatus.TIMEOUT: "timeout",
            RunStatus.TRACE_MISSING: "trace_missing",
            RunStatus.READ_BENCHMARK_FAILED: "read_benchmark_failed",
        }[self]


@dataclass(frozen=True)
class RunConfig:
    runner_config_path: Path
    config_path: Path
    matrix_path: Path
    output_root: Path
    executable_path: Path
    executable_command: str
    jobs: int
    timeout_seconds: int

    @property
    def trace_dir_name(self) -> str:
        return self.executable_path.name + "_trace"

    @property
    def resolved_command(self) -> str:
        executable = shlex.quote(str(self.executable_path))
        executable_name = shlex.quote(self.executable_path.name)
        return self.executable_command.format(executable=executable, executable_name=executable_name)

    @classmethod
    def load(cls, path: Path) -> "RunConfig":
        runner_config_path = path.resolve()
        config_dir = runner_config_path.parent
        data = json.loads(runner_config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Runner config JSON must be an object.")

        required_keys = {
            "default_config",
            "default_matrix",
            "default_output",
            "executable_path",
            "executable_command",
            "jobs",
            "timeout_seconds",
        }
        missing = sorted(required_keys - data.keys())
        if missing:
            raise ValueError(f"Runner config is missing required keys: {', '.join(missing)}")

        config = cls(
            runner_config_path=runner_config_path,
            config_path=(config_dir / str(data["default_config"])).resolve(),
            matrix_path=(config_dir / str(data["default_matrix"])).resolve(),
            output_root=(config_dir / str(data["default_output"])).resolve(),
            executable_path=(config_dir / str(data["executable_path"])).resolve(),
            executable_command=str(data["executable_command"]),
            jobs=int(data["jobs"]),
            timeout_seconds=int(data["timeout_seconds"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.jobs <= 0:
            raise ValueError("jobs must be strictly positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be strictly positive.")
        if "{executable" in self.executable_command:
            self.executable_command.format(
                executable=shlex.quote(str(self.executable_path)),
                executable_name=shlex.quote(self.executable_path.name),
            )
        for path_value, label in (
            (self.config_path, "default_config"),
            (self.matrix_path, "default_matrix"),
            (self.executable_path, "executable_path"),
            (DEFAULT_ENV_SCRIPT, "env_script"),
            (DEFAULT_KILL_SCRIPT, "kill_script"),
        ):
            if not path_value.exists():
                raise FileNotFoundError(f"{label} does not exist: {path_value}")


def load_matrix(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Matrix JSON must be a list.")

    matrix: list[dict[str, str]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Matrix entry {index} must be an object.")
        matrix.append({str(key): str(value) for key, value in item.items()})
    return matrix


def load_config_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def apply_overrides(lines: list[str], overrides: dict[str, str]) -> str:
    rendered = []
    remaining = dict(overrides)

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


def run_kill_trace(log_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(DEFAULT_KILL_SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    append_log(log_path, "$ bash " + str(DEFAULT_KILL_SCRIPT))
    if result.stdout:
        append_log(log_path, result.stdout)
    if result.stderr:
        append_log(log_path, result.stderr)
    append_log(log_path, f"kill_trace_returncode={result.returncode}\n")


def print_case_status(index: int, status: RunStatus, elapsed_seconds: int, case_dir: Path) -> None:
    color = GREEN if status == RunStatus.OK else RED
    print(f"{color}test_{index}: {status.label} [{elapsed_seconds} sec]{RESET} ({case_dir})")


def build_run_command(run: RunConfig, config_path: Path) -> str:
    return (
        f"source {shlex.quote(str(DEFAULT_ENV_SCRIPT))} && "
        f"export PALLAS_CONFIG_PATH={shlex.quote(str(config_path))} && "
        f"mpirun -np {run.jobs} {run.resolved_command}"
    )


def build_read_benchmark_command(trace_file: Path) -> str:
    return (
        f"source {shlex.quote(str(DEFAULT_ENV_SCRIPT))} && "
        f"pallas_read_benchmark {shlex.quote(str(trace_file))}"
    )


def write_run_metadata(output_dir: Path, run: RunConfig) -> None:
    (output_dir / "run_metadata.txt").write_text(
        "\n".join(
            [
                f"runner_config={run.runner_config_path}",
                f"pallas_config={run.config_path}",
                f"matrix={run.matrix_path}",
                f"output_root={run.output_root}",
                f"executable_path={run.executable_path}",
                f"executable_name={run.executable_path.name}",
                f"executable_command={run.executable_command}",
                f"resolved_command={run.resolved_command}",
                f"jobs={run.jobs}",
                f"timeout_seconds={run.timeout_seconds}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def run_test_case(
    index: int,overrides: dict[str, str],
    output_dir: Path, base_lines: list[str],run: RunConfig) -> tuple[RunStatus, int]:
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

    run_kill_trace(run_log)

    command = build_run_command(run, config_path)
    append_log(run_log, "$ bash -lc " + command + "\n")

    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=case_dir,
                text=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout=run.timeout_seconds,
                check=False,
            )
            append_log(run_log, f"status=completed\nreturncode={result.returncode}\n")
        except subprocess.TimeoutExpired:
            elapsed_seconds = int(time.perf_counter() - start_time)
            append_log(run_log, f"status=timeout\ntimeout_seconds={run.timeout_seconds}\nelapsed_seconds={elapsed_seconds}\n")
            run_kill_trace(run_log)
            return RunStatus.TIMEOUT, elapsed_seconds

    run_kill_trace(run_log)

    trace_dir = case_dir / run.trace_dir_name
    if trace_dir.exists():
        append_log(run_log, f"trace_dir={trace_dir}\n")
    else:
        elapsed_seconds = int(time.perf_counter() - start_time)
        append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
        append_log(run_log, f"trace_dir_missing={run.trace_dir_name}\n")
        return RunStatus.TRACE_MISSING, elapsed_seconds

    trace_file = trace_dir / "eztrace_log.pallas"
    if not trace_file.exists():
        elapsed_seconds = int(time.perf_counter() - start_time)
        append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
        append_log(run_log, f"trace_file_missing={trace_file}\n")
        return RunStatus.TRACE_MISSING, elapsed_seconds

    benchmark_command = build_read_benchmark_command(trace_file)
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
        return RunStatus.READ_BENCHMARK_FAILED, elapsed_seconds

    elapsed_seconds = int(time.perf_counter() - start_time)
    append_log(run_log, f"elapsed_seconds={elapsed_seconds}\n")
    if result.returncode != 0:
        return RunStatus.FAILED, elapsed_seconds
    return RunStatus.OK, elapsed_seconds


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Pallas test-case matrix from a tc_runner.json config.")
    parser.add_argument("runner_config", nargs="?", type=Path, default=DEFAULT_RUNNER_CONFIG)
    args = parser.parse_args()

    run = RunConfig.load(args.runner_config)
    matrix = load_matrix(run.matrix_path)
    base_lines = load_config_lines(run.config_path)

    output_dir = run.output_root / ("test-run-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run.runner_config_path, output_dir / run.runner_config_path.name)
    shutil.copy2(run.matrix_path, output_dir / run.matrix_path.name)
    write_run_metadata(output_dir, run)

    overall_status = RunStatus.OK
    for index, overrides in enumerate(matrix):
        status, elapsed_seconds = run_test_case(
            index=index,
            overrides=overrides,
            output_dir=output_dir,
            base_lines=base_lines,
            run=run,
        )
        print_case_status(index, status, elapsed_seconds, output_dir / f"test_{index}")
        if status != RunStatus.OK:
            overall_status = status

    return 0 if overall_status == RunStatus.OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
