import json
from typing import Any


def _validate_schema(cfg: dict) -> list[str]:
    """Basic structural validation. Returns list of error messages."""
    errors = []
    if not isinstance(cfg, dict):
        return ["CFG root must be a JSON object"]

    if "plan_name" not in cfg or not isinstance(cfg["plan_name"], str):
        errors.append("Missing or invalid 'plan_name' (must be string)")

    if "nodes" not in cfg or not isinstance(cfg["nodes"], list) or len(cfg["nodes"]) == 0:
        errors.append("Missing or empty 'nodes' array")
        return errors

    node_ids = set()
    for i, node in enumerate(cfg["nodes"]):
        node_id = node.get("id")
        if not node_id or not isinstance(node_id, str):
            errors.append(f"Node[{i}]: missing or invalid 'id'")
            continue
        if node_id in node_ids:
            errors.append(f"Node[{i}]: duplicate id '{node_id}'")
        node_ids.add(node_id)
        if "node_type" not in node or not isinstance(node["node_type"], str):
            errors.append(f"Node '{node_id}': missing or invalid 'node_type'")

    for i, node in enumerate(cfg["nodes"]):
        node_id = node.get("id", f"index-{i}")
        deps = node.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(f"Node '{node_id}': 'depends_on' must be an array")
            continue
        for dep in deps:
            if dep not in node_ids:
                errors.append(f"Node '{node_id}': depends on unknown node '{dep}'")

    return errors


def parse_and_validate(cfg_json: str | bytes | dict) -> tuple[dict | None, list[str]]:
    """Parse CFG JSON and validate. Returns (parsed_cfg, errors)."""
    if isinstance(cfg_json, (str, bytes)):
        try:
            cfg = json.loads(cfg_json)
        except json.JSONDecodeError as e:
            return None, [f"Invalid JSON: {e}"]
    else:
        cfg = cfg_json

    errors = _validate_schema(cfg)
    if errors:
        return None, errors

    return cfg, []


def merge_config(
    node_config: dict,
    global_config: dict,
    plugin_defaults: dict,
) -> dict:
    """Merge config with priority: node > global > plugin defaults."""
    merged = dict(plugin_defaults)
    merged.update(global_config)
    merged.update(node_config)
    return merged
