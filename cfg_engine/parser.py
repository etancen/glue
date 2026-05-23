import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _validate_schema(cfg: dict) -> list[str]:
    """Basic structural validation. Returns list of error messages."""
    errors = []
    if not isinstance(cfg, dict):
        logger.error("CFG validation failed: root is not a dict (type=%s)", type(cfg).__name__)
        return ["CFG root must be a JSON object"]

    if "plan_name" not in cfg or not isinstance(cfg["plan_name"], str):
        errors.append("Missing or invalid 'plan_name' (must be string)")

    if "nodes" not in cfg or not isinstance(cfg["nodes"], list) or len(cfg["nodes"]) == 0:
        errors.append("Missing or empty 'nodes' array")
        logger.error("CFG validation failed: %s", errors)
        return errors

    logger.info(
        "Validating CFG: plan_name=%s nodes_count=%d has_global_config=%s",
        cfg.get("plan_name"),
        len(cfg["nodes"]),
        "global_config" in cfg,
    )

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

    if errors:
        logger.warning("CFG validation found %d error(s): %s", len(errors), errors)
    else:
        logger.info("CFG validation passed: %d node(s), node_ids=%s", len(cfg["nodes"]), sorted(node_ids))

    return errors


def parse_and_validate(cfg_json: str | bytes | dict) -> tuple[dict | None, list[str]]:
    """Parse CFG JSON and validate. Returns (parsed_cfg, errors)."""
    logger.info("parse_and_validate called: input_type=%s", type(cfg_json).__name__)

    if isinstance(cfg_json, (str, bytes)):
        input_len = len(cfg_json) if isinstance(cfg_json, (str, bytes)) else 0
        logger.debug("Parsing JSON string: length=%d", input_len)
        try:
            cfg = json.loads(cfg_json)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in CFG: %s", e)
            return None, [f"Invalid JSON: {e}"]
    else:
        cfg = cfg_json

    errors = _validate_schema(cfg)
    if errors:
        return None, errors

    logger.info("parse_and_validate succeeded: plan=%s nodes=%d", cfg["plan_name"], len(cfg["nodes"]))
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
    logger.info(
        "Config merged: plugin_defaults_keys=%s global_keys=%s node_keys=%s → merged_keys=%s",
        sorted(plugin_defaults.keys()),
        sorted(global_config.keys()),
        sorted(node_config.keys()),
        sorted(merged.keys()),
    )
    return merged
