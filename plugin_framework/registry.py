from typing import Optional
from .base import BasePlugin


class PluginRegistry:
    """Thread-safe in-memory plugin registry."""

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin):
        self._plugins[plugin.name] = plugin

    def get(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)

    def find_by_node_type(self, node_type: str) -> list[BasePlugin]:
        results = []
        for p in self._plugins.values():
            manifest_types = p.manifest.get("node_types", [])
            if node_type in manifest_types:
                results.append(p)
        return results

    def list_all(self) -> list[BasePlugin]:
        return list(self._plugins.values())

    def clear(self):
        self._plugins.clear()


registry = PluginRegistry()
