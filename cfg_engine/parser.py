"""CFG 配置解析器 — 负责 JSON 格式的拓扑配置文件解析、schema 校验和多层级配置合并。

校验规则：
  - 根对象必须是 dict，含 plan_name(str) 和 nodes(非空 list)
  - 每个 node 必须有 id(str，计划内唯一) 和 node_type(str)
  - depends_on 引用的节点必须存在于 nodes 中（引用完整性）

配置合并优先级：节点 config > 全局 global_config > 插件 default_config
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _validate_schema(cfg: dict) -> list[str]:
    """对 CFG 字典执行结构性校验，返回错误消息列表。

    校验两阶段：
      1. 根结构：plan_name 必填，nodes 非空
      2. 节点：id 唯一性、node_type 必填、depends_on 引用完整性
    所有校验错误均收集后统一返回，而非遇到第一个错误即退出。
    """
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

    # 第一遍：收集所有节点 ID 并校验 id 唯一性和 node_type 必填
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

    # 第二遍：校验 depends_on 引用的节点存在（需等 node_ids 收集完毕）
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
    """解析并校验 CFG 输入，返回 (解析结果, 错误列表)。

    支持三种输入类型：JSON 字符串、bytes、已解析的 dict。
    校验通过时 errors 为空列表，失败时 parsed_cfg 为 None。
    """
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
    """合并三层配置，优先级：节点配置 > 全局配置 > 插件默认值。

    使用 dict.update() 逐层覆盖：先打底 plugin_defaults，再覆盖 global_config，
    最后覆盖 node_config，确保最具体的配置生效。
    """
    # 从低到高逐层覆盖：先打底插件默认值，再覆盖全局配置，最后覆盖节点独有配置
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
