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
    """Load a single plugin from a directory containing plugin.json + deploy.py."""
    manifest_path = os.path.join(plugin_dir, "plugin.json")
    deploy_path = os.path.join(plugin_dir, "deploy.py")
    if not os.path.isfile(manifest_path) or not os.path.isfile(deploy_path):
        return None

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read plugin manifest %s: %s", manifest_path, e)
        return None

    plugin_name = manifest.get("name", "")
    if not plugin_name:
        logger.warning("Plugin manifest %s missing 'name' key", manifest_path)
        return None

    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", plugin_name)
    module_name = f"_plugin_{safe_name}"

    spec = importlib.util.spec_from_file_location(module_name, deploy_path)
    if spec is None or spec.loader is None:
        return None

    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        logger.warning("Failed to load plugin module %s: %s", deploy_path, e)
        sys.modules.pop(module_name, None)
        return None

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

    try:
        instance = plugin_cls()
    except Exception as e:
        logger.warning("Failed to instantiate plugin %s: %s", plugin_name, e)
        return None

    instance.name = plugin_name
    instance.version = manifest.get("version", "0.0.0")
    instance.manifest = manifest
    return instance


def scan_and_load_plugins():
    """Scan PLUGINS_DIR and load all valid plugins into the registry."""
    plugins_dir = settings.PLUGINS_DIR
    if not os.path.isdir(plugins_dir):
        return

    registry.clear()
    for entry in sorted(os.listdir(plugins_dir)):
        full_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(full_path):
            continue
        plugin = load_plugin_from_dir(full_path)
        if plugin:
            registry.register(plugin)
