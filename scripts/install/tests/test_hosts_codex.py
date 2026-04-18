"""Tests for the Codex host install/uninstall flow."""

from __future__ import annotations

from pathlib import Path

from cq_install.content import cq_binary_name
from cq_install.context import Action, InstallContext, RunState
from cq_install.hosts.codex import CodexHost
from cq_install.runtime import runtime_root

RUNTIME_BINARY = Path("bin") / cq_binary_name()


def _ctx(tmp_path: Path, plugin_root: Path) -> InstallContext:
    target = tmp_path / "target"
    target.mkdir(exist_ok=True)
    return InstallContext(
        target=target,
        plugin_root=plugin_root,
        shared_skills_path=tmp_path / "shared",
        host_isolated_skills=False,
        dry_run=False,
        run_state=RunState(),
    )


def test_codex_global_target_default():
    assert CodexHost().global_target() == Path.home() / ".codex"


def test_codex_project_target_uses_project_dot_codex_dir(tmp_path):
    project = tmp_path / "myapp"
    assert CodexHost().project_target(project) == project / ".codex"


def test_codex_install_writes_mcp_config(tmp_path, plugin_root):
    ctx = _ctx(tmp_path, plugin_root)
    shared_runtime = runtime_root()
    CodexHost().install(ctx)

    text = (ctx.target / "config.toml").read_text()
    assert "# cq:start" in text
    assert "[mcp_servers.cq]" in text
    assert f'command = "{shared_runtime / RUNTIME_BINARY}"' in text
    assert 'args = ["mcp"]' in text


def test_codex_install_calls_ensure_cq_binary(tmp_path, plugin_root, monkeypatch):
    fetch_calls: list[Path] = []

    def _record(plugin_root_arg: Path, *, dry_run: bool = False):
        from cq_install.context import ChangeResult

        del dry_run
        fetch_calls.append(plugin_root_arg)
        return [
            ChangeResult(
                action=Action.CREATED,
                path=runtime_root() / "bin" / cq_binary_name(),
                detail="cq v0.2.0",
            )
        ]

    monkeypatch.setattr("cq_install.binary.ensure_cq_binary", _record)

    ctx = _ctx(tmp_path, plugin_root)
    results = CodexHost().install(ctx)

    assert fetch_calls == [plugin_root]
    assert any(r.detail == "cq v0.2.0" for r in results)


def test_codex_install_creates_shared_skills(tmp_path, plugin_root):
    ctx = _ctx(tmp_path, plugin_root)
    CodexHost().install(ctx)
    assert (ctx.shared_skills_path / "cq" / "SKILL.md").exists()


def test_codex_install_idempotent(tmp_path, plugin_root):
    CodexHost().install(_ctx(tmp_path, plugin_root))
    second = CodexHost().install(_ctx(tmp_path, plugin_root))
    assert any(r.action == Action.UNCHANGED for r in second)


def test_codex_install_skips_unmanaged_existing_cq_section(tmp_path, plugin_root):
    ctx = _ctx(tmp_path, plugin_root)
    config_file = ctx.target / "config.toml"
    config_file.write_text('[mcp_servers.cq]\ncommand = "custom-cq"\nargs = ["serve"]\n')

    results = CodexHost().install(ctx)

    assert any(r.action == Action.SKIPPED and "user-managed" in r.detail for r in results)
    assert "# cq:start" not in config_file.read_text()


def test_codex_uninstall_removes_managed_mcp_block(tmp_path, plugin_root):
    ctx = _ctx(tmp_path, plugin_root)
    CodexHost().install(ctx)
    CodexHost().uninstall(ctx)
    assert not (ctx.target / "config.toml").exists()
