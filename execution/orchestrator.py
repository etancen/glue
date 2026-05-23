"""计划编排器 — 将部署计划按 6 步流程拆分为可执行的节点级作业。

流程：
  1. 解析并校验 CFG（parse_and_validate）
  2. 匹配插件（_match_plugin：显式 plugin > node_type 查找）
  3. 校验节点配置（merge_config + plugin.validate_config）
  4. 构建 DAG 拓扑图（build_dag + get_execution_levels）
  5. 创建 DeploymentNode / DeploymentJob 数据库记录
  6. 入队所有 Celery 任务到 Redis 队列

编排器是 API 执行端点与 Celery 异步任务的桥梁。任一步骤失败均记录 AuditLog 并终止。
"""
import json
import logging
from django.utils import timezone as dj_timezone
from core.models import DeploymentPlan, DeploymentNode, DeploymentJob, Plugin as PluginModel, AuditLog
from plugin_framework.registry import registry
from plugin_framework.loader import scan_and_load_plugins
from plugin_framework.base import ConfigValidationError
from cfg_engine.parser import parse_and_validate, merge_config
from cfg_engine.dag import build_dag, get_execution_levels
from execution.tasks import execute_job_task

logger = logging.getLogger(__name__)


def orchestrate_plan(plan_id: str, user_id: str):
    """编排计划执行的完整 6 步流程 — 将计划从 DRAFT 推进到 QUEUED 状态。

    副作用：修改 Plan 状态、创建 DeploymentNode/DeploymentJob 记录、
    创建 AuditLog、向 Celery 投递异步任务。

    Args:
        plan_id: 部署计划 UUID
        user_id: 触发执行的用户 UUID（记录在 AuditLog 中）
    """
    logger.info("Orchestrate plan start: plan_id=%s user_id=%s", plan_id, user_id)
    plan = DeploymentPlan.objects.get(id=plan_id)

    # Step 1: Validate CFG
    logger.info("Step 1/6: Parsing and validating CFG for plan %s", plan_id)
    cfg, errors = parse_and_validate(plan.cfg_content)
    if errors:
        logger.error("CFG validation failed for plan %s: %d error(s) — %s", plan_id, len(errors), errors)
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        AuditLog.objects.create(
            user_id=user_id,
            action="plan_validation_failed",
            target_plan=plan,
            detail={"errors": errors},
        )
        return
    logger.info("Step 1/6 OK: CFG valid, plan_name=%s node_count=%d", cfg.get("plan_name", "?"), len(cfg.get("nodes", [])))

    # 重新扫描插件注册表，确保获取最新插件（如启动后新增的插件目录）
    scan_and_load_plugins()

    # Step 2 & 3: Match plugins and validate configs
    logger.info("Step 2-3/6: Matching plugins and validating configs for %d node(s)", len(cfg["nodes"]))
    validation_errors = []
    for node_cfg in cfg["nodes"]:
        matched = _match_plugin(node_cfg)
        if matched is None:
            err = (
                f"Node '{node_cfg['id']}': no plugin found for node_type '{node_cfg['node_type']}'"
                + (f" (explicit: {node_cfg.get('plugin')})" if node_cfg.get("plugin") else "")
            )
            logger.warning("Plugin match failed: %s", err)
            validation_errors.append(err)
            continue

        # 合并三层配置（节点 > 全局 > 插件默认）后校验
        merged = merge_config(
            node_cfg.get("config", {}),
            cfg.get("global_config", {}),
            matched.manifest.get("default_config", {}),
        )
        logger.info("Validating config for node '%s': plugin=%s config_keys=%s", node_cfg["id"], matched.name, sorted(merged.keys()))
        try:
            if not matched.validate_config(merged):
                err_msg = f"Node '{node_cfg['id']}': plugin '{matched.name}' validation failed"
                logger.warning("Config validation failed: %s", err_msg)
                validation_errors.append(err_msg)
        except ConfigValidationError as e:
            err_msg = f"Node '{node_cfg['id']}': {e}"
            logger.warning("Config validation error: %s", err_msg)
            validation_errors.append(err_msg)

    if validation_errors:
        logger.error("Config validation failed for plan %s: %d error(s)", plan_id, len(validation_errors))
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        AuditLog.objects.create(
            user_id=user_id,
            action="config_validation_failed",
            target_plan=plan,
            detail={"errors": validation_errors},
        )
        return
    logger.info("Step 2-3/6 OK: all %d node(s) matched and validated", len(cfg["nodes"]))

    # Step 4: Build DAG
    logger.info("Step 4/6: Building DAG from %d node(s)", len(cfg["nodes"]))
    dag = build_dag(cfg["nodes"])
    levels = get_execution_levels(dag)
    plan.topology_graph = {
        "levels": levels,
        "edges": [[u, v] for u, v in dag.edges()],
    }
    plan.status = DeploymentPlan.Status.VALIDATED
    plan.save(update_fields=["topology_graph", "status"])
    logger.info("Step 4/6 OK: DAG built with %d node(s), %d edge(s), %d level(s) — levels=%s", dag.number_of_nodes(), dag.number_of_edges(), len(levels), levels)

    # Step 5: Create Nodes and Jobs
    logger.info("Step 5/6: Creating DeploymentNode and DeploymentJob records")
    for node_cfg in cfg["nodes"]:
        plugin = _match_plugin(node_cfg)
        # get_or_create 确保 Plugin 模型与内存 registry 同步
        plugin_model, _ = PluginModel.objects.get_or_create(
            name=plugin.name,
            defaults={
                "version": plugin.version,
                "plugin_dir_path": "",
                "manifest": plugin.manifest,
            },
        )

        merged = merge_config(
            node_cfg.get("config", {}),
            cfg.get("global_config", {}),
            plugin.manifest.get("default_config", {}),
        )
        node_obj = DeploymentNode.objects.create(
            plan=plan,
            node_type=node_cfg["node_type"],
            target_id=node_cfg["id"],
            dependencies=node_cfg.get("depends_on", []),
            config_params=merged,
        )
        job = DeploymentJob.objects.create(
            plan=plan,
            node=node_obj,
            plugin=plugin_model,
            parameters=merged,
        )
        logger.info("Created node/job: target_id=%s node_type=%s plugin=%s job_id=%s", node_cfg["id"], node_cfg["node_type"], plugin.name, job.id)

    logger.info("Step 5/6 OK: %d node(s) and %d job(s) created", DeploymentNode.objects.filter(plan=plan).count(), DeploymentJob.objects.filter(plan=plan).count())

    # Step 6: Enqueue all Celery tasks — 所有任务同一时间入队，DAG 层级由 Celery 并发度自然保证
    logger.info("Step 6/6: Enqueuing Celery tasks for %d node(s)", len(cfg["nodes"]))
    plan.status = DeploymentPlan.Status.QUEUED
    plan.started_at = dj_timezone.now()
    plan.save(update_fields=["status", "started_at"])

    for node_cfg in cfg["nodes"]:
        node_obj = DeploymentNode.objects.get(plan=plan, target_id=node_cfg["id"])
        job = DeploymentJob.objects.get(node=node_obj)
        execute_job_task.apply_async(
            kwargs={"job_id": str(job.id)},
            countdown=0,
        )
        logger.info("Enqueued job: job_id=%s target_id=%s node_type=%s", job.id, node_cfg["id"], node_cfg["node_type"])

    AuditLog.objects.create(
        user_id=user_id,
        action="plan_execution_started",
        target_plan=plan,
        detail={"node_count": len(cfg["nodes"])},
    )
    logger.info("Orchestrate plan complete: plan_id=%s status=%s node_count=%d", plan_id, plan.status, len(cfg["nodes"]))


def _match_plugin(node_cfg: dict):
    """为节点匹配部署插件 — 显式 plugin 字段优先，其次按 node_type 模糊匹配。

    匹配策略：
      1. 若节点指定了 plugin：按名称精确查找，未找到返回 None
      2. 若未指定：按 node_type 在 registry 中匹配，仅在唯一匹配时返回结果
      3. 零匹配或多匹配均返回 None，由上层收集校验错误

    Returns:
        BasePlugin 实例或 None
    """
    explicit = node_cfg.get("plugin")
    if explicit:
        logger.info("Matching plugin by explicit name: '%s' for node '%s'", explicit, node_cfg["id"])
        result = registry.get(explicit)
        logger.info("Explicit plugin match result: %s", result.name if result else "NOT FOUND")
        return result
    node_type = node_cfg["node_type"]
    logger.info("Matching plugin by node_type: '%s' for node '%s'", node_type, node_cfg["id"])
    candidates = registry.find_by_node_type(node_type)
    logger.info("Plugin match by node_type: %d candidate(s) — %s", len(candidates), [p.name for p in candidates])
    # 仅在唯一匹配时返回，避免歧义
    if len(candidates) == 1:
        return candidates[0]
    return None
