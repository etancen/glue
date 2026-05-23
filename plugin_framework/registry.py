"""插件注册表 — 内存级单例，存储所有已加载的插件实例并提供按名称/节点类型的查找。

模块级 registry 变量为全局共享的单例，loader 扫描后将插件逐一注册到此。
"""
import logging
from typing import Optional
from .base import BasePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """插件注册表 — 以插件名为 key 存储插件实例，支持按名称精确查找和按 node_type 模糊匹配。

    所有操作均为 O(1) 或 O(n)，适合中小规模插件集合（通常 < 100 个）。
    """

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}
        logger.debug("PluginRegistry initialized (empty)")

    def register(self, plugin: BasePlugin):
        """注册一个插件实例，以 plugin.name 为 key。同名插件后注册的会覆盖先注册的。"""
        self._plugins[plugin.name] = plugin
        logger.info(
            "Plugin registered: name=%s version=%s node_types=%s connectors=%s",
            plugin.name,
            plugin.version,
            plugin.manifest.get("node_types", []),
            plugin.manifest.get("connectors", []),
        )

    def get(self, name: str) -> Optional[BasePlugin]:
        """按插件名精确查找，用于显式 plugin 字段匹配。未找到返回 None。"""
        plugin = self._plugins.get(name)
        if plugin:
            logger.debug("PluginRegistry.get(name=%s) → found (version=%s)", name, plugin.version)
        else:
            logger.debug("PluginRegistry.get(name=%s) → not found", name)
        return plugin

    def find_by_node_type(self, node_type: str) -> list[BasePlugin]:
        """按 node_type 模糊匹配 — 遍历所有插件，返回 manifest.node_types 中包含该类型的插件列表。

        若返回多个匹配项（模糊匹配），调用方应通过其他方式消歧。
        若无匹配返回空列表。
        """
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
        """返回所有已注册插件的列表。"""
        plugins = list(self._plugins.values())
        logger.debug("PluginRegistry.list_all() → %d plugin(s)", len(plugins))
        return plugins

    def clear(self):
        """清空注册表 — 通常在重新扫描插件目录前调用，确保无残留。"""
        count = len(self._plugins)
        self._plugins.clear()
        logger.info("PluginRegistry cleared (%d plugin(s) removed)", count)


# 全局单例 — 由 loader 在启动和扫描时填充
registry = PluginRegistry()
