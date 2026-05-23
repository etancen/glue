import json
from django.utils import timezone as dj_timezone
from core.models import DeploymentPlan, DeploymentNode, DeploymentJob, Plugin as PluginModel, AuditLog
from plugin_framework.registry import registry
from plugin_framework.loader import scan_and_load_plugins
from plugin_framework.base import ConfigValidationError
from cfg_engine.parser import parse_and_validate, merge_config
from cfg_engine.dag import build_dag, get_execution_levels
from execution.tasks import execute_job_task


def orchestrate_plan(plan_id: str, user_id: str):
    """Called from the API 'execute' endpoint. Orchestrates the entire plan execution.

    1. Parse & validate CFG
    2. Match plugins
    3. Validate configs
    4. Build DAG
    5. Create DeploymentNode and DeploymentJob records
    6. Enqueue level-0 tasks
    """
    plan = DeploymentPlan.objects.get(id=plan_id)

    # Step 1: Validate CFG
    cfg, errors = parse_and_validate(plan.cfg_content)
    if errors:
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        AuditLog.objects.create(
            user_id=user_id,
            action="plan_validation_failed",
            target_plan=plan,
            detail={"errors": errors},
        )
        return

    # Reload plugin registry to ensure freshness
    scan_and_load_plugins()

    # Step 2 & 3: Match plugins and validate configs
    validation_errors = []
    for node_cfg in cfg["nodes"]:
        matched = _match_plugin(node_cfg)
        if matched is None:
            validation_errors.append(
                f"Node '{node_cfg['id']}': no plugin found for node_type '{node_cfg['node_type']}'"
                + (f" (explicit: {node_cfg.get('plugin')})" if node_cfg.get("plugin") else "")
            )
            continue

        merged = merge_config(
            node_cfg.get("config", {}),
            cfg.get("global_config", {}),
            matched.manifest.get("default_config", {}),
        )
        try:
            if not matched.validate_config(merged):
                validation_errors.append(
                    f"Node '{node_cfg['id']}': plugin '{matched.name}' validation failed"
                )
        except ConfigValidationError as e:
            validation_errors.append(f"Node '{node_cfg['id']}': {e}")

    if validation_errors:
        plan.status = DeploymentPlan.Status.FAILED
        plan.save(update_fields=["status"])
        AuditLog.objects.create(
            user_id=user_id,
            action="config_validation_failed",
            target_plan=plan,
            detail={"errors": validation_errors},
        )
        return

    # Step 4: Build DAG
    dag = build_dag(cfg["nodes"])
    levels = get_execution_levels(dag)
    plan.topology_graph = {
        "levels": levels,
        "edges": [[u, v] for u, v in dag.edges()],
    }
    plan.status = DeploymentPlan.Status.VALIDATED
    plan.save(update_fields=["topology_graph", "status"])

    # Step 5: Create Nodes and Jobs
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
        DeploymentJob.objects.create(
            plan=plan,
            node=node_obj,
            plugin=plugin_model,
            parameters=merged,
        )

    # Step 6: Enqueue tasks for all nodes
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

    AuditLog.objects.create(
        user_id=user_id,
        action="plan_execution_started",
        target_plan=plan,
        detail={"node_count": len(cfg["nodes"])},
    )


def _match_plugin(node_cfg: dict):
    """Match a plugin to a node config. Explicit 'plugin' field takes priority."""
    explicit = node_cfg.get("plugin")
    if explicit:
        return registry.get(explicit)
    candidates = registry.find_by_node_type(node_cfg["node_type"])
    if len(candidates) == 1:
        return candidates[0]
    return None
