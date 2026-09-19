"""Attack-graph rendering with PyVis.

Design goals for a live demo:
  * deterministic layout - nodes are pinned to a left-to-right column per node
    type and physics is disabled, so the graph looks identical every run
  * readable in two seconds - a dangerous path is thick and red, everything else
    is muted
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import networkx as nx
from pyvis.network import Network

from blastradius.graph.graph_builder import node_of
from blastradius.parser.models import NodeType, Risk

# Column order of the attack graph, left to right.
LAYERS: Dict[NodeType, int] = {
    NodeType.INTERNET: 0,
    NodeType.SECURITY_GROUP: 1,
    NodeType.EC2: 2,
    NodeType.IAM_ROLE: 3,
    NodeType.S3_BUCKET: 4,
    NodeType.SENSITIVE_DATA: 5,
}

STYLE: Dict[NodeType, Dict[str, object]] = {
    NodeType.INTERNET: {"color": "#475569", "shape": "hexagon", "size": 30, "icon": "WWW"},
    NodeType.SECURITY_GROUP: {"color": "#0ea5e9", "shape": "diamond", "size": 26, "icon": "SG"},
    NodeType.EC2: {"color": "#8b5cf6", "shape": "box", "size": 26, "icon": "EC2"},
    NodeType.IAM_ROLE: {"color": "#f59e0b", "shape": "box", "size": 26, "icon": "IAM"},
    NodeType.S3_BUCKET: {"color": "#10b981", "shape": "database", "size": 26, "icon": "S3"},
    NodeType.SENSITIVE_DATA: {"color": "#ef4444", "shape": "star", "size": 34, "icon": "DATA"},
}

LEGEND: List[Tuple[str, str]] = [
    ("Internet", "#475569"),
    ("Security Group", "#0ea5e9"),
    ("EC2", "#8b5cf6"),
    ("IAM Role", "#f59e0b"),
    ("S3 Bucket", "#10b981"),
    ("Sensitive Data", "#ef4444"),
]

DANGER_COLOR = "#ef4444"
SAFE_EDGE_COLOR = "#cbd5e1"
MUTED_NODE_BORDER = "#1e293b"

_X_SPACING = 215
_Y_SPACING = 125

_OPTIONS = """
{
  "physics": { "enabled": false },
  "interaction": { "hover": true, "dragNodes": true, "zoomView": true, "navigationButtons": false },
  "nodes": {
    "font": { "color": "#e2e8f0", "size": 19, "face": "Segoe UI", "strokeWidth": 0 },
    "borderWidth": 2
  },
  "edges": {
    "arrows": { "to": { "enabled": true, "scaleFactor": 0.8 } },
    "smooth": { "enabled": true, "type": "cubicBezier", "forceDirection": "horizontal", "roundness": 0.35 },
    "font": { "color": "#94a3b8", "size": 11, "strokeWidth": 4, "strokeColor": "#0b1120", "align": "top" }
  }
}
"""


def _positions(graph: nx.DiGraph) -> Dict[str, Tuple[int, int]]:
    """Pin every node to (layer column, stacked row) coordinates."""
    by_layer: Dict[int, List[str]] = {}
    for node_id in graph.nodes:
        layer = LAYERS.get(node_of(graph, node_id).type, 6)
        by_layer.setdefault(layer, []).append(node_id)

    positions: Dict[str, Tuple[int, int]] = {}
    for layer, node_ids in by_layer.items():
        for index, node_id in enumerate(sorted(node_ids)):
            offset = index - (len(node_ids) - 1) / 2
            positions[node_id] = (layer * _X_SPACING, int(offset * _Y_SPACING))
    return positions


def _hex_to_rgba(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _node_tooltip(node, on_path: bool) -> str:
    lines = [f"{node.type.value}: {node.name}", f"id: {node.id}"]
    if node.sensitive:
        lines.append("marked SENSITIVE")
    if on_path:
        lines.append("on a detected attack path")
    return " | ".join(lines)


def render_graph(
    graph: nx.DiGraph,
    highlight_nodes: Iterable[str] = (),
    highlight_edges: Iterable[Sequence[str]] = (),
    height: int = 460,
    show_edge_labels: bool = False,
) -> str:
    """Return standalone HTML for the graph, ready for `st.components.v1.html`."""
    highlighted_nodes = set(highlight_nodes)
    highlighted_edges = {tuple(e) for e in highlight_edges}
    # When a path is highlighted, everything else is dimmed so the dangerous
    # route is the only thing competing for attention.
    fade = bool(highlighted_nodes)

    network = Network(
        height=f"{height}px",
        width="100%",
        directed=True,
        bgcolor="#0b1120",
        font_color="#e2e8f0",
        cdn_resources="in_line",
    )
    network.set_options(_OPTIONS)

    positions = _positions(graph)
    for node_id in sorted(graph.nodes):
        node = node_of(graph, node_id)
        style = STYLE.get(node.type, {"color": "#64748b", "shape": "dot", "size": 22})
        on_path = node_id in highlighted_nodes
        dimmed = fade and not on_path
        x, y = positions[node_id]
        background = _hex_to_rgba(str(style["color"]), 0.28) if dimmed else style["color"]
        network.add_node(
            node_id,
            label=f"{style['icon']}\n{node.name}" if style.get("icon") else node.name,
            title=_node_tooltip(node, on_path),
            color={
                "background": background,
                "border": DANGER_COLOR if on_path else ("#243044" if dimmed else MUTED_NODE_BORDER),
                "highlight": {"background": style["color"], "border": DANGER_COLOR},
            },
            shape=style["shape"],
            size=int(style["size"]) + 6 if on_path else style["size"],
            borderWidth=6 if on_path else 2,
            shadow={"enabled": on_path, "color": DANGER_COLOR, "size": 28, "x": 0, "y": 0},
            font={"color": "#64748b"} if dimmed else {"color": "#e8eef8"},
            x=x,
            y=y,
            physics=False,
        )

    for source, target, data in graph.edges(data=True):
        edge = data["edge"]
        on_path = (source, target) in highlighted_edges
        dimmed = fade and not on_path
        if on_path:
            color = DANGER_COLOR
        elif dimmed:
            color = "rgba(100,116,139,.35)"
        else:
            color = _edge_color(edge.risk)
        network.add_edge(
            source,
            target,
            title=edge.reason,
            label=edge.relationship.value.replace("_", " ").lower() if show_edge_labels else None,
            color=color,
            width=7 if on_path else 1.5,
            shadow={"enabled": on_path, "color": DANGER_COLOR, "size": 18, "x": 0, "y": 0},
            dashes=not on_path and edge.risk == Risk.LOW,
        )

    return network.generate_html(notebook=False)


def _edge_color(risk: Risk) -> str:
    return {
        Risk.CRITICAL: "#f87171",
        Risk.HIGH: "#fb923c",
        Risk.MEDIUM: "#fbbf24",
    }.get(risk, SAFE_EDGE_COLOR)
