"""插件加载器 — 扫描 PLUGINS_DIR 目录，动态加载所有合法插件并注册到 registry。

加载流程：
  1. 遍历 plugins_dir 下的子目录
  2. 读取 plugin.json 并校验 name 必填
  3. 使用 importlib 动态加载 deploy.py 模块
  4. 从模块中查找 BasePlugin 的子类并实例化
  5. 注入 name / version / manifest 属性
  6. 注册到全局 registry

容错设计：单个插件加载失败不影响其他插件继续扫描。
"""
import json
import importlib.util
import logging
import os
import re
import sys
from typing import Optional
from django.conf import settings
from .base import BasePlugin
from .registry import registry

logger = logging.getLogger(__name__)


def load_plugin_from_dir(plugin_dir: str) -> Optional[BasePlugin]:
    """从单个插件目录加载插件，返回实例或 None（加载失败时）。

    Args:
        plugin_dir: 插件目录的绝对路径，必须包含 plugin.json 和 deploy.py

    Returns:
        已实例化的 BasePlugin 子类对象，或 None 表示加载失败
    """
    manifest_path = os.path.join(plugin_dir, "plugin.json")
    deploy_path = os.path.join(plugin_dir, "deploy.py")
    logger.debug("Scanning plugin directory: %s", plugin_dir)

    if not os.path.isfile(manifest_path) or not os.path.isfile(deploy_path):
        logger.debug("Skipping %s: plugin.json or deploy.py not found", plugin_dir)
        return None

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
        logger.info(
            "Loading plugin manifest: name=%s version=%s node_types=%s",
            manifest.get("name", "?"),
            manifest.get("version", "?"),
            manifest.get("node_types", []),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read plugin manifest %s: %s", manifest_path, e)
        return None

    plugin_name = manifest.get("name", "")
    if not plugin_name:
        logger.warning("Plugin manifest %s missing 'name' key", manifest_path)
        return None

    # 清理插件名为合法 Python 模块名，避免特殊字符导致 importlib 出错
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_name)
    module_name = f"_plugin_{safe_name}"
    logger.info("Loading plugin module: %s (safe_name=%s)", plugin_name, safe_name)

    spec = importlib.util.spec_from_file_location(module_name, deploy_path)
    if spec is None or spec.loader is None:
        logger.warning("Could not create module spec for %s", deploy_path)
        return None

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        logger.debug("Module %s executed successfully", module_name)
    except Exception as e:
        logger.warning("Failed to load plugin module %s: %s", deploy_path, e)
        # 加载失败时从 sys.modules 中清理残留，避免下次导入时出现不一致
        sys.modules.pop(module_name, None)
        return None

    # 从模块中查找第一个 BasePlugin 的具体子类（排除 BasePlugin 自身）
    plugin_cls = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BasePlugin)
            and attr is not BasePlugin
        ):
            plugin_cls = attr
            break

    if plugin_cls is None:
        logger.warning("No BasePlugin subclass found in %s", deploy_path)
        return None

    logger.info("Found plugin class: %s", plugin_cls.__name__)

    try:
        instance = plugin_cls()
    except Exception as e:
        logger.warning("Failed to instantiate plugin %s (%s): %s", plugin_name, plugin_cls.__name__, e)
        return None

    # loader 负责注入元数据属性，插件类本身无需在 __init__ 中处理这些字段
    instance.name = plugin_name
    instance.version = manifest.get("version", "0.0.0")
    instance.manifest = manifest
    logger.info(
        "Plugin loaded: name=%s version=%s class=%s required_config=%s",
        instance.name,
        instance.version,
        plugin_cls.__name__,
        manifest.get("required_config", []),
    )
    return instance


def scan_and_load_plugins():
    """扫描 settings.PLUGINS_DIR 目录，加载所有合法插件并注册到全局 registry。

    每次调用会先清空 registry，确保无已卸载插件的残留。
    非目录条目和加载失败的目录会被跳过并记录 warning。
    """
    plugins_dir = settings.PLUGINS_DIR
    logger.info("Starting plugin scan: PLUGINS_DIR=%s", plugins_dir)

    if not os.path.isdir(plugins_dir):
        logger.warning("PLUGINS_DIR does not exist or is not a directory: %s", plugins_dir)
        return

    entries = sorted(os.listdir(plugins_dir))
    logger.info("Found %d entries in plugins directory: %s", len(entries), entries)

    registry.clear()
    loaded_count = 0
    for entry in entries:
        full_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(full_path):
            logger.debug("Skipping non-directory entry: %s", entry)
            continue
        plugin = load_plugin_from_dir(full_path)
        if plugin:
            registry.register(plugin)
            loaded_count += 1
        else:
            logger.warning("Failed to load plugin from: %s", full_path)

    logger.info("Plugin scan complete: %d loaded, %d total entries scanned", loaded_count, len(entries))
