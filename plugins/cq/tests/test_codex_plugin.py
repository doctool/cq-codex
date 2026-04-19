"""Tests for Codex-native plugin packaging files."""

from __future__ import annotations

import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_codex_plugin_manifest_matches_core_package_metadata():
    codex_manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    claude_manifest = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())

    for field in ("name", "version", "description", "repository", "license", "keywords"):
        assert codex_manifest[field] == claude_manifest[field]

    assert codex_manifest["skills"] == "./skills/"
    assert codex_manifest["mcpServers"] == "./.mcp.json"
    assert "interface" in codex_manifest


def test_codex_plugin_manifest_exposes_required_interface_fields():
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    interface = manifest["interface"]

    assert interface["displayName"] == "cq"
    assert interface["category"] == "Productivity"
    assert interface["capabilities"] == ["Read", "Write"]
    assert interface["defaultPrompt"]
    assert interface["websiteURL"] == "https://github.com/mozilla-ai/cq"


def test_codex_plugin_mcp_config_uses_bootstrap_script():
    config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())

    assert config == {
        "mcpServers": {
            "cq": {
                "command": "uv",
                "args": ["run", "python", "./scripts/bootstrap.py"],
                "cwd": ".",
            }
        }
    }


def test_repo_marketplace_exposes_local_cq_plugin():
    marketplace = json.loads(
        (PLUGIN_ROOT.parent.parent / ".agents" / "plugins" / "marketplace.json").read_text()
    )

    assert marketplace["name"] == "mozilla-ai-local"
    assert marketplace["interface"]["displayName"] == "Mozilla AI Local Plugins"
    assert marketplace["plugins"] == [
        {
            "name": "cq",
            "source": {"source": "local", "path": "./plugins/cq"},
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Productivity",
        }
    ]
