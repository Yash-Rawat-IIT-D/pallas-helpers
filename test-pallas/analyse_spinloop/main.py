from .analysis import (
    print_basic_summary,
    print_duration_analysis,
    print_mpi_event_analysis,
    print_token_analysis,
)
from .common import (
    file_size_report,
    load_trace,
    parse_args,
    print_api_debug,
    resolve_trace_file,
    safe_getattr,
    select_archive,
    select_thread,
)


def main():
    args = parse_args()

    print("=== Trace Load ===")
    print(f"input_path={args.trace_path}")
    print(f"requested_thread_selector={args.thread}")

    try:
        trace_file = resolve_trace_file(args.trace_path)
        trace = load_trace(trace_file)
    except Exception as exc:
        print(f"load_succeeded=False error={exc}")
        return 1

    archive, archive_reason = select_archive(trace, args.thread)
    thread, thread_reason = select_thread(archive, args.thread) if archive is not None else (None, None)

    print(f"resolved_trace_file={trace_file}")
    print("load_succeeded=True")
    print(f"archive_selection={archive_reason}")
    print(f"thread_selection={thread_reason}")
    print(f"trace_name={safe_getattr(trace, 'trace_name')}")
    print(f"trace_dir={safe_getattr(trace, 'dir_name')}")
    print(f"trace_fullpath={safe_getattr(trace, 'fullpath')}")
    print(f"trace_starting_timestamp={safe_getattr(trace, 'starting_timestamp')}")
    print(f"trace_ending_timestamp={safe_getattr(trace, 'ending_timestamp')}")

    # print_basic_summary(trace, archive, thread)
    # print_token_analysis(thread, args.max_tokens)
    # print_mpi_event_analysis(thread)
    # print_duration_analysis(thread, trace_file)
    if not args.no_file_sizes:
        file_size_report(trace_file, archive)
    if args.debug_api:
        print_api_debug(trace, archive, thread)
    return 0
