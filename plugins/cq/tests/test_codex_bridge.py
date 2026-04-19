"""Tests for the Codex stdio framing bridge."""

from __future__ import annotations

import io
import sys
from importlib import util
from pathlib import Path
from types import ModuleType

import pytest

BRIDGE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "codex_bridge.py"
SCRIPTS_DIR = BRIDGE_PATH.parent


def _load_bridge() -> ModuleType:
    """Load codex_bridge.py with the scripts dir on sys.path."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = util.spec_from_file_location("cq_codex_bridge_under_test", BRIDGE_PATH)
        assert spec is not None and spec.loader is not None
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def test_read_framed_message_reads_body():
    bridge = _load_bridge()
    payload = b'{"jsonrpc":"2.0","id":1}'
    stream = io.BytesIO(
        f"Content-Length: {len(payload)}\r\nX-Test: 1\r\n\r\n".encode("ascii") + payload
    )
    assert bridge._read_framed_message(stream) == payload


def test_write_framed_message_wraps_body():
    bridge = _load_bridge()
    stream = io.BytesIO()
    bridge._write_framed_message(stream, b'{"ok":true}')
    assert stream.getvalue() == b'Content-Length: 11\r\n\r\n{"ok":true}'


def test_forward_host_to_child_translates_to_newline_delimited():
    bridge = _load_bridge()
    payload = b'{"jsonrpc":"2.0","id":1}'
    host_in = io.BytesIO(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
    class _Writable(io.BytesIO):
        def close(self):
            pass

    child_in = _Writable()
    bridge._forward_host_to_child(host_in, child_in)
    assert child_in.getvalue() == payload + b"\n"


def test_forward_child_to_host_translates_to_framed():
    bridge = _load_bridge()
    child_out = io.BytesIO(b'{"jsonrpc":"2.0","id":1}\n')
    host_out = io.BytesIO()
    bridge._forward_child_to_host(child_out, host_out)
    assert host_out.getvalue() == (
        b'Content-Length: 24\r\n\r\n{"jsonrpc":"2.0","id":1}'
    )


def test_main_loads_binary_launches_child_and_exits(monkeypatch, tmp_path):
    bridge = _load_bridge()
    metadata = tmp_path / "bootstrap.json"
    metadata.write_text('{"cli_min_version": "0.5.0"}\n')

    calls: list[tuple[str, tuple]] = []
    fake_binary = tmp_path / "bin" / "cq"

    monkeypatch.setattr(bridge, "__file__", str(metadata.parent / "codex_bridge.py"))
    monkeypatch.setattr(bridge.cq_binary, "shared_bin_dir", lambda: tmp_path / "bin")
    monkeypatch.setattr(bridge.cq_binary, "cq_binary_name", lambda: "cq")

    def _fake_ensure(binary, required, bin_dir):
        calls.append(("ensure", (binary, required, bin_dir)))

    class _FakeProc:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()

        def wait(self):
            return 0

    def _fake_popen(argv, **kwargs):
        calls.append(("popen", (tuple(argv), kwargs["bufsize"])))
        return _FakeProc()

    class _FakeThread:
        def __init__(self, *, target, args, daemon):
            calls.append(("thread", (target.__name__, daemon, len(args))))

        def start(self):
            calls.append(("start", ()))

        def join(self, timeout=None):
            calls.append(("join", (timeout,)))

    monkeypatch.setattr(bridge.cq_binary, "ensure_binary", _fake_ensure)
    monkeypatch.setattr(bridge.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(bridge.threading, "Thread", _FakeThread)

    with pytest.raises(SystemExit) as exc_info:
        bridge.main()

    assert exc_info.value.code == 0
    assert calls[:2] == [
        ("ensure", (fake_binary, "0.5.0", tmp_path / "bin")),
        ("popen", ((str(fake_binary), "mcp"), 0)),
    ]
