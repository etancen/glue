import json
import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional
from django.conf import settings
from .base import BasePlugin
from .registry import registry


def load_plugin_from_dir(plugin_dir: str) -> Optional[BasePlugin]:
    """Load a single plugin from a directory containing plugin.json + deploy.py."""
    manifest_path = os.path.join(plugin_dir, "plugin.json")
    deploy_path = os.path.join(plugin_dir, "deploy.py")
    if not os.path.isfile(manifest_path) or not os.path.isfile(deploy_path):
        return None

    with open(manifest_path) as f:
        manifest = json.load(f)

    plugin_name = manifest["name"]
    module_name = f"_plugin_{plugin_name}"

    spec = importlib.util.spec_from_file_location(module_name, deploy_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

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
        return None

    instance = plugin_cls()
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
