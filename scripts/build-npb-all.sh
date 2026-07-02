#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INRIA_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MPI_ROOT_DEFAULT="${INRIA_ROOT}/NPB/NPB3.4/NPB3.4-MPI"
MZ_ROOT_DEFAULT="${INRIA_ROOT}/NPB/NPB3.4-MZ/NPB3.4-MZ-MPI"

MPI_BENCHMARKS=(bt cg dt ep ft is lu mg sp)
MZ_BENCHMARKS=(bt-mz lu-mz sp-mz)

usage() {
  cat <<'EOF'
Usage: build-npb-all.sh [options]

Build every supported NAS Parallel Benchmark MPI binary across all classes.

Options:
  --root <path>        Override the base NPB3.4-MPI source tree.
  --with-mz            Also build the NPB3.4-MZ MPI+OpenMP benchmarks.
  --mz-root <path>     Override the NPB3.4-MZ-MPI source tree.
  --classes <list>     Comma-separated class list, for example S,W,A,B,C.
  --benchmarks <list>  Comma-separated MPI benchmark list.
  --help               Show this help text.

Examples:
  build-npb-all.sh
  build-npb-all.sh --classes S,W,A,B,C
  build-npb-all.sh --with-mz
EOF
}

split_csv() {
  local input="$1"
  local -n output_ref="$2"
  local old_ifs="${IFS}"
  IFS=',' read -r -a output_ref <<<"${input}"
  IFS="${old_ifs}"
}

extract_make_var() {
  local make_def="$1"
  local var_name="$2"

  awk -F= -v var_name="${var_name}" '
    $0 !~ /^[[:space:]]*#/ && $0 ~ "^[[:space:]]*" var_name "[[:space:]]*=" {
      value = $0
      sub("^[[:space:]]*" var_name "[[:space:]]*=[[:space:]]*", "", value)
      print value
      exit
    }
  ' "${make_def}"
}

append_flag_to_make_var() {
  local make_def="$1"
  local var_name="$2"
  local flag="$3"
  local tmp_file

  if ! grep -Eq "^[[:space:]]*${var_name}[[:space:]]*=" "${make_def}"; then
    return 0
  fi

  if grep -Eq "^[[:space:]]*${var_name}[[:space:]]*=.*(^|[[:space:]])${flag}([[:space:]]|$)" "${make_def}"; then
    return 0
  fi

  tmp_file="$(mktemp)"
  awk -v var_name="${var_name}" -v flag="${flag}" '
    BEGIN {
      updated = 0
    }
    $0 ~ "^[[:space:]]*" var_name "[[:space:]]*=" && updated == 0 {
      print $0 " " flag
      updated = 1
      next
    }
    {
      print
    }
  ' "${make_def}" > "${tmp_file}"
  mv "${tmp_file}" "${make_def}"
}

make_var_references_fflags() {
  local make_def="$1"
  local value

  value="$(extract_make_var "${make_def}" FLINKFLAGS)"
  [[ "${value}" == *'$(FFLAGS)'* || "${value}" == *'${FFLAGS}'* ]]
}

uses_gnu_fortran() {
  local compiler_cmd="$1"
  local version_output=""
  local show_output=""

  if [[ -z "${compiler_cmd}" ]] || ! command -v "${compiler_cmd}" >/dev/null 2>&1; then
    return 1
  fi

  version_output="$("${compiler_cmd}" --version 2>/dev/null | head -n 1 || true)"
  show_output="$("${compiler_cmd}" -show 2>/dev/null || true)"

  [[ "${version_output}" == *"GNU Fortran"* || "${show_output}" == *"gfortran"* ]]
}

prepare_make_def() {
  local root="$1"
  local make_def="${root}/config/make.def"
  local compiler_value=""
  local compiler_cmd=""
  local patched=0
  local flag
  local compat_flags=(
    -std=legacy
    -fallow-argument-mismatch
    -fallow-invalid-boz
  )

  mkdir -p "${root}/bin"

  compiler_value="$(extract_make_var "${make_def}" MPIFC)"
  if [[ -z "${compiler_value}" ]]; then
    compiler_value="$(extract_make_var "${make_def}" FC)"
  fi
  compiler_cmd="${compiler_value%% *}"

  if ! uses_gnu_fortran "${compiler_cmd}"; then
    return 0
  fi

  for flag in "${compat_flags[@]}"; do
    if ! grep -Eq "^[[:space:]]*FFLAGS[[:space:]]*=.*(^|[[:space:]])${flag}([[:space:]]|$)" "${make_def}"; then
      append_flag_to_make_var "${make_def}" FFLAGS "${flag}"
      patched=1
    fi

    if ! make_var_references_fflags "${make_def}" && \
      ! grep -Eq "^[[:space:]]*FLINKFLAGS[[:space:]]*=.*(^|[[:space:]])${flag}([[:space:]]|$)" "${make_def}"; then
      append_flag_to_make_var "${make_def}" FLINKFLAGS "${flag}"
      patched=1
    fi
  done

  if [[ ${patched} -eq 1 ]]; then
    echo "Enabled GNU Fortran compatibility flags in ${make_def}"
  fi
}

ensure_make_def() {
  local root="$1"
  local template="${root}/config/make.def.template"
  local target="${root}/config/make.def"

  if [[ -f "${target}" ]]; then
    return 0
  fi

  if [[ ! -f "${template}" ]]; then
    echo "Missing template: ${template}" >&2
    return 1
  fi

  cp "${template}" "${target}"
  echo "Created ${target} from template"
}

class_supported_for_benchmark() {
  local benchmark="$1"
  local class="$2"

  case "${benchmark}" in
    is)
      [[ "${class}" != "F" ]]
      ;;
    dt)
      [[ "${class}" != "E" && "${class}" != "F" ]]
      ;;
    *)
      return 0
      ;;
  esac
}

build_tree() {
  local root="$1"
  local tree_name="$2"
  local -n benchmarks_ref="$3"
  local -n classes_ref="$4"

  local benchmark
  local class
  local -a failures=()
  local attempted=0

  if [[ ! -d "${root}" ]]; then
    echo "Missing ${tree_name} tree: ${root}" >&2
    return 1
  fi

  ensure_make_def "${root}" || return 1
  prepare_make_def "${root}" || return 1

  echo
  echo "== Building ${tree_name} in ${root} =="

  for benchmark in "${benchmarks_ref[@]}"; do
    for class in "${classes_ref[@]}"; do
      if ! class_supported_for_benchmark "${benchmark}" "${class}"; then
        continue
      fi

      attempted=$((attempted + 1))
      echo "[${tree_name}] make ${benchmark} CLASS=${class}"
      if ! make -C "${root}" "${benchmark}" "CLASS=${class}"; then
        failures+=("${benchmark}:${class}")
      fi
    done
  done

  echo
  echo "== ${tree_name} summary =="
  echo "Attempted builds: ${attempted}"
  echo "Output directory: ${root}/bin"

  if [[ ${#failures[@]} -eq 0 ]]; then
    echo "Status: success"
    return 0
  fi

  echo "Status: failures (${#failures[@]})" >&2
  printf '  %s\n' "${failures[@]}" >&2
  return 1
}

MPI_ROOT="${MPI_ROOT_DEFAULT}"
MZ_ROOT="${MZ_ROOT_DEFAULT}"
WITH_MZ=0
CLASSES=(S W A B C D E F)
SELECTED_MPI_BENCHMARKS=("${MPI_BENCHMARKS[@]}")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      MPI_ROOT="$2"
      shift 2
      ;;
    --with-mz)
      WITH_MZ=1
      shift
      ;;
    --mz-root)
      MZ_ROOT="$2"
      shift 2
      ;;
    --classes)
      split_csv "$2" CLASSES
      shift 2
      ;;
    --benchmarks)
      split_csv "$2" SELECTED_MPI_BENCHMARKS
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

build_tree "${MPI_ROOT}" "NPB MPI" SELECTED_MPI_BENCHMARKS CLASSES
mpi_status=$?

mz_status=0
if [[ ${WITH_MZ} -eq 1 ]]; then
  build_tree "${MZ_ROOT}" "NPB MZ MPI" MZ_BENCHMARKS CLASSES
  mz_status=$?
fi

if [[ ${mpi_status} -ne 0 || ${mz_status} -ne 0 ]]; then
  exit 1
fi
