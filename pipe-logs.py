#!/usr/bin/env python3
import fcntl
import os
import sys
from datetime import datetime


ERROR_MARKERS = (
    "address already in use",
    "command failed",
    "command not found",
    "cannot",
    "could not",
    "denied",
    "does not exist",
    "error",
    "exception",
    "exited early",
    "exited with status",
    "failed",
    "invalid",
    "missing executable",
    "missing dependency",
    "missing selection",
    "no such file",
    "no protocol",
    "not found",
    "permission denied",
    "refused",
    "returned no",
    "runtimeerror",
    "traceback",
    "unable",
    "unavailable",
    "warning",
)


def trim_if_needed(handle, max_bytes: int, keep_bytes: int):
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    if size <= max_bytes:
        return

    keep = min(keep_bytes, size)
    handle.seek(size - keep)
    data = handle.read()
    if keep < size:
        newline = data.find(b"\n")
        if newline != -1:
            data = data[newline + 1 :]
    handle.seek(0)
    handle.truncate()
    handle.write(data)
    handle.flush()


def should_echo(mode: str, raw_line: bytes) -> bool:
    if mode == "all":
        return True
    if mode != "errors":
        return False

    text = raw_line.decode("utf-8", errors="replace").lower()
    return any(marker in text for marker in ERROR_MARKERS)


def main():
    component = os.environ.get("LOGPIPE_COMPONENT", "")
    log_file = os.environ.get("LOGPIPE_FILE", "")
    max_bytes_raw = os.environ.get("LOGPIPE_MAX_BYTES", "")
    keep_bytes_raw = os.environ.get("LOGPIPE_KEEP_BYTES", "")
    echo_mode = os.environ.get("LOGPIPE_ECHO_MODE", "")
    if not echo_mode:
        echo_mode = "all" if os.environ.get("LOGPIPE_ECHO_STDERR", "") == "1" else "none"

    if not component or not log_file or not max_bytes_raw or not keep_bytes_raw:
        raise SystemExit("missing LOGPIPE_* environment")

    max_bytes = int(max_bytes_raw)
    keep_bytes = int(keep_bytes_raw)

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)

    with open(log_file, "ab+") as handle:
        for raw_line in sys.stdin.buffer:
            if raw_line.endswith(b"\n"):
                raw_line = raw_line[:-1]
            stamp = datetime.now().isoformat(timespec="seconds")
            line = f"{stamp} [{component}] ".encode("utf-8") + raw_line + b"\n"

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                trim_if_needed(handle, max_bytes, keep_bytes)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

            if should_echo(echo_mode, raw_line):
                sys.stderr.buffer.write(line)
                sys.stderr.buffer.flush()


if __name__ == "__main__":
    main()
