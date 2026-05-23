import logging
from typing import Optional
from .base import BasePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """In-memory plugin registry."""

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}
        logger.debug("PluginRegistry initialized (empty)")

    def register(self, plugin: BasePlugin):
        self._plugins[plugin.name] = plugin
        logger.info(
            "Plugin registered: name=%s version=%s node_types=%s connectors=%s",
            plugin.name,
            plugin.version,
            plugin.manifest.get("node_types", []),
            plugin.manifest.get("connectors", []),
        )

    def get(self, name: str) -> Optional[BasePlugin]:
        plugin = self._plugins.get(name)
        if plugin:
            logger.debug("PluginRegistry.get(name=%s) → found (version=%s)", name, plugin.version)
        else:
            logger.debug("PluginRegistry.get(name=%s) → not found", name)
        return plugin

    def find_by_node_type(self, node_type: str) -> list[BasePlugin]:
        results = []
        for p in self._plugins.values():
            manifest_types = p.manifest.get("node_types", [])
            if node_type in manifest_types:
                results.append(p)
        logger.info(
            "PluginRegistry.find_by_node_type(node_type=%s) → matched %d plugin(s): %s",
            node_type,
            len(results),
            [p.name for p in results],
        )
        return results

    def list_all(self) -> list[BasePlugin]:
        plugins = list(self._plugins.values())
        logger.debug("PluginRegistry.list_all() → %d plugin(s)", len(plugins))
        return plugins

    def clear(self):
        count = len(self._plugins)
        self._plugins.clear()
        logger.info("PluginRegistry cleared (%d plugin(s) removed)", count)


registry = PluginRegistry()
