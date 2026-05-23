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
    """Called from the API 'execute' endpoint. Orchestrates the entire plan execution.

    1. Parse & validate CFG
    2. Match plugins
    3. Validate configs
    4. Build DAG
    5. Create DeploymentNode and DeploymentJob records
    6. Enqueue level-0 tasks
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

    # Reload plugin registry to ensure freshness
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

    # Step 6: Enqueue tasks for all nodes
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
    """Match a plugin to a node config. Explicit 'plugin' field takes priority."""
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
    if len(candidates) == 1:
        return candidates[0]
    return None
