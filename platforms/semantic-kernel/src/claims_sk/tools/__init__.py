"""Claims tool plugins registered with the Semantic Kernel runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from semantic_kernel import Kernel

from .plugins import build_tool_plugins
from .repository import SharedDataRepository


def register_tool_plugins(kernel: Kernel, shared_root: Path | None = None) -> Dict[str, object]:
	"""Register all claims-specific tool plugins with the provided kernel."""

	repository = SharedDataRepository(shared_root=shared_root)
	plugins = build_tool_plugins(repository)

	for name, plugin in plugins.items():
		kernel.add_plugin(plugin, plugin_name=name)

	return plugins


__all__ = ["register_tool_plugins", "SharedDataRepository", "build_tool_plugins"]
