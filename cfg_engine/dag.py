"""DAG 构建器 — 基于 networkx 实现拓扑排序、执行层级分组、环检测和逆序回滚顺序计算。

核心概念：
  - 执行层级（execution levels）：同一层级的节点入度为 0，可并行执行
  - 逆拓扑排序：用于回滚，先回滚下游消费者，再回滚上游生产者
  - 环检测：DAG 一旦存在环，无法确定安全执行顺序，直接拒绝执行
"""
import logging
import networkx as nx
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def build_dag(nodes: list[dict]) -> nx.DiGraph:
    """从 CFG 节点定义构建有向无环图，检测到环时抛出 ValidationError。

    Args:
        nodes: CFG nodes 列表，每项含 id、node_type，可选 depends_on、plugin、config

    Returns:
        DiGraph 对象，每个节点的属性含 node_type、plugin、config、depends_on

    Raises:
        ValidationError: 检测到环时拒绝执行，因为无法确定安全的执行顺序
    """
    logger.info("Building DAG from %d node(s)", len(nodes))
    G = nx.DiGraph()

    for node in nodes:
        node_id = node["id"]
        node_type = node["node_type"]
        plugin = node.get("plugin")
        deps = node.get("depends_on", [])
        logger.info(
            "Adding node to DAG: id=%s type=%s plugin=%s depends_on=%s",
            node_id, node_type, plugin or "(auto)", deps,
        )
        G.add_node(
            node_id,
            node_type=node_type,
            plugin=plugin,
            config=node.get("config", {}),
            depends_on=deps,
        )

    edge_count = 0
    for node in nodes:
        for dep in node.get("depends_on", []):
            G.add_edge(dep, node["id"])
            edge_count += 1
            logger.debug("DAG edge: %s → %s", dep, node["id"])

    logger.info("DAG built: %d node(s), %d edge(s)", G.number_of_nodes(), edge_count)

    # 环检测：一旦发现环，部署不可继续 — 无法确定安全的执行顺序，需修改 CFG 后重试
    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        cycle_strs = [" -> ".join(c) + " -> " + c[0] for c in cycles]
        logger.error("DAG cycle(s) detected: %s", cycle_strs)
        raise ValidationError(f"DAG contains cycles: {'; '.join(cycle_strs)}")

    logger.info("DAG is acyclic — valid")
    return G


def get_execution_levels(G: nx.DiGraph) -> list[list[str]]:
    """将节点按拓扑层级分组 — 同一层级的节点无相互依赖，可并行执行。

    算法：BFS 式逐层剥离 — 每轮取所有入度为 0 的节点作为新层级，
    移除后继续下一轮，直到所有节点分配完毕。
    """
    logger.info("Computing execution levels for DAG with %d node(s)", G.number_of_nodes())
    levels = []
    remaining = set(G.nodes())
    G_copy = G.copy()

    while remaining:
        # 每轮取出所有入度为 0 的节点（无前置依赖），它们可以并行执行
        sources = [n for n in remaining if G_copy.in_degree(n) == 0]
        if not sources:
            break
        levels.append(sorted(sources))
        logger.info("Level %d: %d node(s) — %s", len(levels), len(sources), sorted(sources))
        remaining -= set(sources)
        G_copy.remove_nodes_from(sources)

    logger.info("Execution levels computed: %d level(s) total", len(levels))
    return levels


def reverse_topological_order(G: nx.DiGraph) -> list[str]:
    """返回逆拓扑排序 — 先下游后上游，用于回滚时保证依赖顺序不被破坏。

    先回滚消费者（下游），再回滚生产者（上游），确保被依赖者最后撤销。
    """
    order = list(reversed(list(nx.topological_sort(G))))
    logger.info("Reverse topological order: %s", order)
    return order


def get_downstream_nodes(G: nx.DiGraph, node_id: str) -> set[str]:
    """获取 node_id 的所有下游节点（直接或间接依赖它的节点）。

    用于评估某个节点的失败影响范围，辅助回滚决策。
    """
    downstream = set(nx.descendants(G, node_id))
    logger.info("Downstream nodes of '%s': %s", node_id, sorted(downstream) if downstream else "(none)")
    return downstream
