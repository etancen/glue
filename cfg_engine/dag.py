import logging
import networkx as nx
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def build_dag(nodes: list[dict]) -> nx.DiGraph:
    """Build a directed acyclic graph from CFG node definitions.

    Each node dict must have: id, node_type, and optional depends_on, plugin, config.
    Returns a DiGraph where each node has attributes: node_type, plugin, config, depends_on.
    Raises ValidationError if a cycle is detected.
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

    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        cycle_strs = [" -> ".join(c) + " -> " + c[0] for c in cycles]
        logger.error("DAG cycle(s) detected: %s", cycle_strs)
        raise ValidationError(f"DAG contains cycles: {'; '.join(cycle_strs)}")

    logger.info("DAG is acyclic — valid")
    return G


def get_execution_levels(G: nx.DiGraph) -> list[list[str]]:
    """Return nodes grouped by topological level (nodes at same level can run in parallel)."""
    logger.info("Computing execution levels for DAG with %d node(s)", G.number_of_nodes())
    levels = []
    remaining = set(G.nodes())
    G_copy = G.copy()

    while remaining:
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
    """Return nodes in reverse topological order (for rollback — downstream first)."""
    order = list(reversed(list(nx.topological_sort(G))))
    logger.info("Reverse topological order: %s", order)
    return order


def get_downstream_nodes(G: nx.DiGraph, node_id: str) -> set[str]:
    """Get all nodes that depend on node_id (directly or transitively)."""
    downstream = set(nx.descendants(G, node_id))
    logger.info("Downstream nodes of '%s': %s", node_id, sorted(downstream) if downstream else "(none)")
    return downstream
