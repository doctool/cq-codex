#!/usr/bin/env python3
"""Codex stdio bridge for the cq MCP server.

The published cq CLI currently speaks newline-delimited JSON on stdio,
while Codex sends and expects Content-Length framed MCP messages. This
bridge keeps the portable plugin bootstrap flow, launches `cq mcp`, and
translates between the two wire formats.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
from pathlib import Path
from typing import BinaryIO

import cq_binary


def _load_binary() -> Path:
    """Ensure the required cq CLI is present and return its path."""
    metadata_path = Path(__file__).resolve().with_name("bootstrap.json")
    min_version = cq_binary.load_min_version(metadata_path)
    if not min_version:
        print("Error: minimum CLI version not set in bootstrap metadata", file=sys.stderr)
        raise SystemExit(1)

    bin_dir = cq_binary.shared_bin_dir()
    binary = bin_dir / cq_binary.cq_binary_name()
    cq_binary.ensure_binary(binary, min_version, bin_dir)
    return binary


def _read_framed_message(stream: BinaryIO) -> bytes | None:
    """Read one Content-Length framed message body from stream."""
    content_length: int | None = None

    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in (b"\n", b"\r\n"):
            break

        name, sep, value = line.partition(b":")
        if sep != b":":
            raise ValueError(f"invalid MCP header line: {line!r}")
        if name.strip().lower() == b"content-length":
            content_length = int(value.strip())

    if content_length is None:
        raise ValueError("missing Content-Length header")

    body = stream.read(content_length)
    if len(body) != content_length:
        raise EOFError("unexpected EOF while reading MCP body")
    return body


def _write_framed_message(stream: BinaryIO, body: bytes) -> None:
    """Write one Content-Length framed message body to stream."""
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    stream.write(header)
    stream.write(body)
    stream.flush()


def _forward_host_to_child(host_in: BinaryIO, child_in: BinaryIO) -> None:
    """Translate host-framed MCP input into newline-delimited child input."""
    try:
        while True:
            body = _read_framed_message(host_in)
            if body is None:
                break
            child_in.write(body)
            child_in.write(b"\n")
            child_in.flush()
    except (BrokenPipeError, EOFError, ValueError):
        pass
    finally:
        with contextlib.suppress(BrokenPipeError, OSError):
            child_in.close()


def _forward_child_to_host(child_out: BinaryIO, host_out: BinaryIO) -> None:
    """Translate newline-delimited child output into host-framed MCP output."""
    for line in child_out:
        body = line.rstrip(b"\r\n")
        if not body:
            continue
        _write_framed_message(host_out, body)


def _forward_stderr(child_err: BinaryIO, host_err: BinaryIO) -> None:
    """Mirror child stderr without polluting stdout."""
    for chunk in iter(lambda: child_err.read(8192), b""):
        host_err.write(chunk)
        host_err.flush()


def main() -> None:
    """Launch cq mcp and bridge Codex framing to the released CLI transport."""
    binary = _load_binary()
    proc = subprocess.Popen(
        [str(binary), "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    threads = [
        threading.Thread(
            target=_forward_host_to_child,
            args=(sys.stdin.buffer, proc.stdin),
            daemon=True,
        ),
        threading.Thread(
            target=_forward_child_to_host,
            args=(proc.stdout, sys.stdout.buffer),
            daemon=True,
        ),
        threading.Thread(
            target=_forward_stderr,
            args=(proc.stderr, sys.stderr.buffer),
            daemon=True,
        ),
    ]

    for thread in threads:
        thread.start()

    try:
        exit_code = proc.wait()
    finally:
        for thread in threads:
            thread.join(timeout=1)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
