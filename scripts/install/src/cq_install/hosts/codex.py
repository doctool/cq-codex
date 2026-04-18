"""Codex host adapter."""

from __future__ import annotations

import json
from pathlib import Path

from cq_install.content import CQ_MCP_KEY, cq_binary_name
from cq_install.context import Action, ChangeResult, InstallContext
from cq_install.hosts.base import HostDef
from cq_install.runtime import runtime_root

CODEX_CONFIG_DIR = ".codex"
CODEX_CONFIG_FILE = "config.toml"
CODEX_MCP_BLOCK_START = "# cq:start"
CODEX_MCP_BLOCK_END = "# cq:end"
CODEX_MCP_HEADER = f"[mcp_servers.{CQ_MCP_KEY}]"


class CodexHost(HostDef):
    """Adapter for the Codex CLI and IDE extension."""

    name = "codex"
    supports_host_isolated = False

    def global_target(self) -> Path:
        """Return the global Codex config dir."""
        return Path.home() / CODEX_CONFIG_DIR

    def project_target(self, project: Path) -> Path:
        """Return the per-project Codex config dir."""
        return project / CODEX_CONFIG_DIR

    def install(self, ctx: InstallContext) -> list[ChangeResult]:
        """Install cq into the Codex target."""
        results: list[ChangeResult] = []
        results.extend(ctx.run_state.ensure_shared_skills(ctx))
        results.extend(ctx.run_state.ensure_cq_binary(ctx))
        results.append(self._install_mcp(ctx))
        return results

    def uninstall(self, ctx: InstallContext) -> list[ChangeResult]:
        """Remove cq from the Codex target."""
        return [self._uninstall_mcp(ctx)]

    def _install_mcp(self, ctx: InstallContext) -> ChangeResult:
        config_path = ctx.target / CODEX_CONFIG_FILE
        block = _mcp_block()
        existing = config_path.read_text() if config_path.exists() else ""

        managed_start = existing.find(CODEX_MCP_BLOCK_START)
        managed_end = existing.find(CODEX_MCP_BLOCK_END)
        if managed_start != -1 and managed_end != -1 and managed_end >= managed_start:
            block_end = managed_end + len(CODEX_MCP_BLOCK_END)
            updated = _normalize_toml(
                existing[:managed_start] + block + existing[block_end:]
            )
        elif _has_unmanaged_cq_table(existing):
            return ChangeResult(
                action=Action.SKIPPED,
                path=config_path,
                detail="existing user-managed [mcp_servers.cq] left in place",
            )
        else:
            updated = _append_block(existing, block)

        if updated == existing:
            return ChangeResult(action=Action.UNCHANGED, path=config_path)

        action = Action.CREATED if not config_path.exists() else Action.UPDATED
        if not ctx.dry_run:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(updated)
        return ChangeResult(action=action, path=config_path)

    def _uninstall_mcp(self, ctx: InstallContext) -> ChangeResult:
        config_path = ctx.target / CODEX_CONFIG_FILE
        if not config_path.exists():
            return ChangeResult(action=Action.UNCHANGED, path=config_path)

        existing = config_path.read_text()
        managed_start = existing.find(CODEX_MCP_BLOCK_START)
        managed_end = existing.find(CODEX_MCP_BLOCK_END)
        if managed_start == -1 or managed_end == -1 or managed_end < managed_start:
            return ChangeResult(action=Action.UNCHANGED, path=config_path)

        block_end = managed_end + len(CODEX_MCP_BLOCK_END)
        updated = _normalize_toml(existing[:managed_start] + existing[block_end:])

        if not ctx.dry_run:
            if updated.strip():
                config_path.write_text(updated)
            else:
                config_path.unlink()
        return ChangeResult(action=Action.REMOVED, path=config_path)


def _mcp_block() -> str:
    binary = runtime_root() / "bin" / cq_binary_name()
    return "\n".join(
        [
            CODEX_MCP_BLOCK_START,
            CODEX_MCP_HEADER,
            f"command = {json.dumps(str(binary))}",
            f'args = {json.dumps(["mcp"])}',
            CODEX_MCP_BLOCK_END,
        ]
    )


def _append_block(existing: str, block: str) -> str:
    if not existing.strip():
        return f"{block}\n"
    return f"{existing.rstrip()}\n\n{block}\n"


def _normalize_toml(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return f"{stripped}\n"


def _has_unmanaged_cq_table(text: str) -> bool:
    for line in text.splitlines():
        header = line.strip()
        if header == CODEX_MCP_HEADER or header.startswith(f"{CODEX_MCP_HEADER[:-1]}."):
            return True
    return False
