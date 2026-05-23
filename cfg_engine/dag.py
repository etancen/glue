import networkx as nx
from django.core.exceptions import ValidationError


def build_dag(nodes: list[dict]) -> nx.DiGraph:
    """Build a directed acyclic graph from CFG node definitions.

    Each node dict must have: id, node_type, and optional depends_on, plugin, config.
    Returns a DiGraph where each node has attributes: node_type, plugin, config, depends_on.
    Raises ValidationError if a cycle is detected.
    """
    G = nx.DiGraph()

    for node in nodes:
        G.add_node(
            node["id"],
            node_type=node["node_type"],
            plugin=node.get("plugin"),
            config=node.get("config", {}),
            depends_on=node.get("depends_on", []),
        )

    for node in nodes:
        for dep in node.get("depends_on", []):
            G.add_edge(dep, node["id"])  # Edge from dependency to dependent

    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        cycle_strs = [" -> ".join(c) + " -> " + c[0] for c in cycles]
        raise ValidationError(f"DAG contains cycles: {'; '.join(cycle_strs)}")

    return G


def get_execution_levels(G: nx.DiGraph) -> list[list[str]]:
    """Return nodes grouped by topological level (nodes at same level can run in parallel)."""
    levels = []
    remaining = set(G.nodes())
    G_copy = G.copy()

    while remaining:
        sources = [n for n in remaining if G_copy.in_degree(n) == 0]
        if not sources:
            break
        levels.append(sorted(sources))
        remaining -= set(sources)
        G_copy.remove_nodes_from(sources)

    return levels


def reverse_topological_order(G: nx.DiGraph) -> list[str]:
    """Return nodes in reverse topological order (for rollback — downstream first)."""
    return list(reversed(list(nx.topological_sort(G))))


def get_downstream_nodes(G: nx.DiGraph, node_id: str) -> set[str]:
    """Get all nodes that depend on node_id (directly or transitively)."""
    return set(nx.descendants(G, node_id))
