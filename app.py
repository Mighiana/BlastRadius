"""BlastRadius - Streamlit dashboard.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import difflib
import html
import re
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Tuple, cast

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components
from lark.exceptions import LarkError

from blastradius.graph import analyze, build_graph, compare
from blastradius.graph.attack_paths import AnalysisResult
from blastradius.graph.diff_engine import GraphDiff, Verdict, highlight_edges, highlight_nodes
from blastradius.parser import parse_directory
from blastradius.report import build_report
from blastradius.policy import PolicyError, discover_policy
from blastradius.parser.models import AttackPath, GraphEdge, NodeType, ResourceNode, Risk
from blastradius import gitsource, scenarios, simulation
from blastradius.security import remediation
from blastradius.security.decision import DeploymentDecision, decide
from blastradius.security.risk_score import PENALTIES
from blastradius.session_storage import (
    SessionWorkspace,
    StorageError,
    checked_path,
    cleanup_expired,
    trusted_local_enabled,
)
from blastradius.visualization import LEGEND, render_graph

ROOT = Path(__file__).resolve().parent
SAFE_DIR = ROOT / "examples" / "safe"
VULNERABLE_DIR = ROOT / "examples" / "vulnerable"
BUNDLED_DIRS = frozenset(
    directory for scenario in scenarios.SCENARIOS for directory in (scenario.before, scenario.after)
)

RISK_COLORS: Dict[Risk, str] = {
    Risk.NONE: "#34d399",
    Risk.LOW: "#34d399",
    Risk.MEDIUM: "#fbbf24",
    Risk.HIGH: "#fb923c",
    Risk.CRITICAL: "#f87171",
}

HOP_REASON_TITLES = {
    NodeType.SECURITY_GROUP: "Network exposure",
    NodeType.EC2: "Compute reached",
    NodeType.IAM_ROLE: "Privilege pivot",
    NodeType.S3_BUCKET: "Data access",
    NodeType.SENSITIVE_DATA: "Impact",
}

CSS = """
<style>
  .block-container { padding-top: 1.6rem; max-width: 1560px; }

  /* ---------- Product identity ---------- */
  .br-title { font-size: 5rem; font-weight: 900; letter-spacing: -3px; margin: 0; line-height: 1;
              background: linear-gradient(95deg,#f87171 5%,#fb923c 45%,#fbbf24 95%);
              -webkit-background-clip: text; -webkit-text-fill-color: transparent;
              background-clip: text; }
  .br-sub { color: #dbe4f0; font-size: 1.35rem; font-weight: 500; margin: .35rem 0 .1rem 0;
            letter-spacing: -.2px; }
  .br-kicker { color: #9fb0c6; font-size: .9rem; margin: .1rem 0 1.3rem 0; }

  /* ---------- Deployment decision (hero) ---------- */
  .br-decision { border-radius: 16px; padding: 1.4rem 1.6rem; margin: .2rem 0 1rem 0;
                 display: flex; align-items: center; gap: 1.5rem; border: 2px solid; }
  .br-decision .ic { font-size: 3.4rem; line-height: 1; }
  .br-dec-label { font-size: .78rem; font-weight: 800; letter-spacing: .18em; color: #c3cfe0; }
  .br-decision h1 { margin: .1rem 0 0 0; font-size: 2.9rem; font-weight: 900; letter-spacing: -1.5px;
                    line-height: 1.05; }
  .br-decision p { margin: .35rem 0 0 0; color: #e2e9f4; font-size: 1.05rem; max-width: 62ch; }
  .br-dec-right { margin-left: auto; text-align: right; white-space: nowrap; }
  .br-badge { display: inline-block; padding: .4rem .9rem; border-radius: 999px; font-weight: 900;
              font-size: 1.05rem; letter-spacing: .04em; border: 2px solid; }
  .br-score { font-size: 2.2rem; font-weight: 900; margin-top: .55rem; color: #f1f5fb; }
  .br-score small { color: #c3cfe0; font-size: .9rem; font-weight: 700; }
  .br-dec-block  { background: rgba(239,68,68,.16);  border-color: #ef4444; }
  .br-dec-review { background: rgba(245,158,11,.16); border-color: #f59e0b; }
  .br-dec-safe   { background: rgba(16,185,129,.16); border-color: #10b981; }

  /* ---------- Decision reasons ---------- */
  .br-reasons { display: grid; grid-template-columns: repeat(4, 1fr); gap: .8rem; margin-bottom: 1.5rem; }
  .br-reason { background: #0f172a; border: 1px solid #253248; border-left: 5px solid #334155;
               border-radius: 10px; padding: .7rem .95rem; }
  .br-reason .k { color: #cbd7e6; font-size: .8rem; font-weight: 700; text-transform: uppercase;
                  letter-spacing: .05em; }
  .br-reason .v { font-size: 1.6rem; font-weight: 900; line-height: 1.25; }
  .br-reason .d { color: #a9b8cc; font-size: .82rem; word-break: break-word; }

  /* ---------- Metric cards ---------- */
  .br-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: .9rem; margin-bottom: 1.5rem; }
  .br-card { background: #0f172a; border: 1px solid #253248; border-radius: 12px; padding: .9rem 1.1rem; }
  .br-card .lbl { color: #cbd7e6; font-size: .8rem; font-weight: 700; text-transform: uppercase;
                  letter-spacing: .06em; }
  .br-card .val { font-size: 2.3rem; font-weight: 900; line-height: 1.15; color: #f1f5fb; }
  .br-card .dlt { font-size: .9rem; font-weight: 700; }

  /* ---------- Graph panels ---------- */
  .br-side { display: flex; align-items: baseline; gap: .6rem; margin-bottom: .35rem;
             padding: .45rem .8rem; background: #0f172a; border: 1px solid #253248;
             border-radius: 10px 10px 0 0; }
  .br-side .s { font-size: .95rem; font-weight: 900; letter-spacing: .12em; color: #e8eef8; }
  .br-side .m { font-size: .85rem; color: #a9b8cc; }
  .br-legend { display: flex; flex-wrap: wrap; gap: 1rem; color: #c3cfe0; font-size: .85rem;
               margin: .2rem 0 .7rem 0; }
  .br-dot { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: .4rem; }

  /* ---------- Attack paths ---------- */
  .br-path { font-family: 'Cascadia Code', Consolas, monospace; font-size: 1.12rem; font-weight: 700;
             background: #1a1013; border: 1px solid #7f1d1d; border-left: 6px solid #ef4444;
             border-radius: 10px; padding: .85rem 1.1rem; margin: .5rem 0 1rem 0; color: #fecdd3; }
  .br-path-good { background: #0c1a16; border-color: #065f46; border-left-color: #10b981;
                  color: #a7f3d0; }
  .br-hop { border-left: 2px solid #3b4b63; margin-left: .4rem; padding: .2rem 0 .75rem 1rem; }
  .br-hop .h { font-weight: 800; color: #f1f5fb; font-size: 1rem; }
  .br-hop .r { color: #c3cfe0; font-size: .9rem; }
  .br-hop .t { color: #8fa3bd; font-size: .82rem; font-family: Consolas, monospace; }

  .br-note { color: #a9b8cc; font-size: .88rem; }
  .br-h { font-size: 1.45rem; font-weight: 800; color: #f1f5fb; margin: .4rem 0 .2rem 0;
          letter-spacing: -.3px; }
  hr { border-color: #253248; }
  .br-title { font-size: clamp(2.5rem, 9vw, 5rem); letter-spacing: -.04em; }
  .br-cards, .br-reasons { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .br-card, .br-reason, .br-decision > div { min-width: 0; overflow-wrap: anywhere; }
  .br-decision { flex-wrap: wrap; }
  .br-decision h1 { font-size: clamp(1.65rem, 5vw, 2.9rem); }
  .br-dec-right { white-space: normal; }
  .br-side { flex-wrap: wrap; overflow-wrap: anywhere; }
  .br-path, .br-hop, .br-kicker { overflow-wrap: anywhere; }
  iframe { max-width: 100%; }
  @media (max-width: 800px) {
    .br-cards, .br-reasons { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .br-decision { padding: 1rem; gap: .75rem; }
    .br-dec-right { margin-left: 0; text-align: left; width: 100%; }
    .br-path { font-size: .95rem; padding: .7rem; }
  }
  @media (max-width: 400px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; }
    .br-cards, .br-reasons { grid-template-columns: minmax(0, 1fr); }
    .br-badge { font-size: .9rem; }
  }
</style>
"""

GRAPH_FIT_HTML = """
<style>
  html, body { margin: 0; width: 100%; overflow: hidden; }
  .card { min-width: 0; max-width: 100%; border: 0; }
  #mynetwork { width: 100% !important; border: 0; }
</style>
<script>
  (() => {
    const fit = () => {
      if (container.clientWidth > 0) network.fit({animation: false});
    };
    const observer = new ResizeObserver(() => requestAnimationFrame(fit));
    observer.observe(container);
    requestAnimationFrame(fit);
    if (document.fonts) document.fonts.ready.then(fit);
  })();
</script>
"""


# ---------------------------------------------------------------------------
# Analysis and session-owned input boundaries
# ---------------------------------------------------------------------------
def workspace() -> SessionWorkspace:
    return cast(SessionWorkspace, st.session_state.workspace)


def validated_directory(directory: Path) -> Path:
    return workspace().validate_input(directory, BUNDLED_DIRS, trusted=trusted_local_enabled())


def analyze_dir(directory: Path, label: str) -> AnalysisResult:
    return analyze(build_graph(parse_directory(validated_directory(directory))), label)


def new_job(purpose: str) -> Path:
    keep = (Path(st.session_state.before_dir), Path(st.session_state.after_dir))
    return workspace().new_job(purpose, keep)


def apply_remediation(after_dir: Path, plan: remediation.RemediationPlan) -> None:
    source = validated_directory(after_dir)
    target = new_job("remediation")
    remediation.write_plan(plan, target, source)
    queue_scenario(source, target)


def queue_scenario(before_dir: Path, after_dir: Path) -> None:
    """Request a scenario switch on the next run.

    Streamlit forbids writing to a widget's session-state key after that widget
    has been created, so the change is staged and applied at the top of `main()`.
    """
    before_dir, after_dir = validated_directory(before_dir), validated_directory(after_dir)
    st.session_state.pending_scenario = (str(before_dir), str(after_dir))
    st.rerun()


def _apply_pending_scenario() -> None:
    pending = st.session_state.pop("pending_scenario", None)
    if pending:
        st.session_state.before_dir, st.session_state.after_dir = pending


def terraform_text(directory: Path) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(validated_directory(directory).glob("*.tf"))
    )


# ---------------------------------------------------------------------------
# Small rendering helpers
# ---------------------------------------------------------------------------
def risk_color(risk: Risk) -> str:
    return RISK_COLORS.get(risk, "#a9b8cc")


def esc(value: object) -> str:
    return html.escape(str(value))


def markdown_text(value: object) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>-])", r"\\\1", esc(value))


def safe_graph_html(
    graph: nx.DiGraph, nodes: List[str], edges: List[Tuple[str, str]], height: int
) -> str:
    """Escape PyVis HTML tooltips without changing the analysis graph."""
    display = graph.copy()
    for node_id, data in display.nodes(data=True):
        node = cast(ResourceNode, data["node"])
        display.nodes[node_id]["node"] = replace(node, id=esc(node.id), name=esc(node.name))
    for source, target, data in display.edges(data=True):
        edge = cast(GraphEdge, data["edge"])
        display.edges[source, target]["edge"] = replace(edge, reason=esc(edge.reason))
    document = render_graph(display, nodes, edges, height=height)
    return document.replace("</body>", GRAPH_FIT_HTML + "</body>")


def embed_html(html_doc: str, height: int) -> None:
    """Embed generated graph HTML, preferring `st.iframe` where available."""
    if hasattr(st, "iframe"):
        st.iframe(html_doc, height=height)
    else:  # Streamlit < 1.60
        components.html(html_doc, height=height)


def heading(text: str) -> None:
    st.markdown(f'<div class="br-h">{esc(text)}</div>', unsafe_allow_html=True)


def _delta_html(before: float, after: float) -> str:
    if before == after:
        return '<div class="dlt" style="color:#8fa3bd">no change</div>'
    color = "#f87171" if after > before else "#34d399"
    arrow = "&#9650;" if after > before else "&#9660;"
    return f'<div class="dlt" style="color:{color}">{arrow} {before} &rarr; {after}</div>'


# ---------------------------------------------------------------------------
# Priority 3: what-if simulator
# ---------------------------------------------------------------------------
def section_simulator(before_dir: Path) -> None:
    """Mutate the baseline Terraform live and re-run the real analysis on it."""
    risky = simulation.SIMULATIONS["public_ssh"]
    baseline = terraform_text(before_dir)
    can_simulate = risky.applies_to(baseline)

    left, middle, right = st.columns([1.1, 1.1, 2], gap="small")
    if left.button(
        "Simulate risky change",
        use_container_width=True,
        disabled=not can_simulate,
        help=risky.description if can_simulate else "The BEFORE config has no private SSH CIDR to widen.",
        icon=":material/bolt:",
        key="simulate_risky",
    ):
        result = simulation.simulate(validated_directory(before_dir), new_job("simulation"), risky)
        st.session_state.last_simulation = result.simulation.id
        queue_scenario(before_dir, result.directory)

    if middle.button(
        "Restore safe configuration",
        use_container_width=True,
        help="Return to the safe baseline with no pending change.",
        icon=":material/restart_alt:",
        key="restore_safe",
    ):
        st.session_state.pop("last_simulation", None)
        queue_scenario(SAFE_DIR, SAFE_DIR)

    right.markdown(
        '<span class="br-note">Simulated changes are written to a scratch directory and '
        "analysed by the same engine as committed Terraform - no results are faked.</span>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Priority 1: deployment decision
# ---------------------------------------------------------------------------
_DECISION_CSS_CLASS = {
    "BLOCK CHANGE": "br-dec-block",
    "REVIEW REQUIRED": "br-dec-review",
    "SAFE TO MERGE": "br-dec-safe",
}

_VERDICT_COLOR = {
    Verdict.REGRESSION: "#f87171",
    Verdict.IMPROVED: "#34d399",
    Verdict.UNCHANGED: "#9fb0c6",
}


def decision_banner(decision: DeploymentDecision, diff: GraphDiff) -> str:
    """The single most important element on the page."""
    verdict_color = _VERDICT_COLOR[diff.verdict]
    delta = diff.score_delta
    sign = "+" if delta > 0 else ""
    return (
        f'<div class="br-decision {_DECISION_CSS_CLASS[decision.decision.value]}">'
        f'<div class="ic">{decision.icon}</div>'
        f'<div><div class="br-dec-label">DEPLOYMENT DECISION</div>'
        f'<h1 style="color:{decision.color}">{esc(decision.decision.value)}</h1>'
        f"<p>{esc(decision.headline)}</p></div>"
        f'<div class="br-dec-right">'
        f'<div class="br-badge" style="color:{verdict_color};border-color:{verdict_color};'
        f'background:rgba(0,0,0,.25)">{esc(diff.verdict.value)}</div>'
        f'<div class="br-score">{diff.before.score} &rarr; {diff.after.score}'
        f'<small> /100</small></div>'
        f'<div style="color:{verdict_color};font-weight:800">{sign}{delta} points</div>'
        f"</div></div>"
    )


def decision_reasons(decision: DeploymentDecision) -> str:
    cards = []
    for reason in decision.reasons:
        color = risk_color(reason.severity) if reason.delta else "#8fa3bd"
        value = f"+{reason.delta}" if reason.delta else "0"
        if reason.label == "Security score delta":
            value = reason.detail.split()[-2] if "points" in reason.detail else "0"
            value = f"{value} pts" if value != "0" else "0"
        cards.append(
            f'<div class="br-reason" style="border-left-color:{color}">'
            f'<div class="k">{esc(reason.label)}</div>'
            f'<div class="v" style="color:{color}">{esc(value)}</div>'
            f'<div class="d">{esc(reason.detail)}</div></div>'
        )
    return f'<div class="br-reasons">{"".join(cards)}</div>'


def summary_cards(before: AnalysisResult, after: AnalysisResult) -> str:
    danger = "#f87171"
    good = "#34d399"
    cards = [
        (
            "Risk level",
            f'<span style="color:{risk_color(after.risk_level)}">{after.risk_level.value}</span>',
            f'<div class="dlt" style="color:#8fa3bd">was {before.risk_level.value}</div>',
        ),
        (
            "Internet-reachable resources",
            str(len(after.exposed_resources)),
            _delta_html(len(before.exposed_resources), len(after.exposed_resources)),
        ),
        (
            "Sensitive resources reachable",
            f'<span style="color:{danger if after.reachable_sensitive else good}">'
            f"{len(after.reachable_sensitive)}</span>",
            _delta_html(len(before.reachable_sensitive), len(after.reachable_sensitive)),
        ),
        (
            "Critical attack paths",
            f'<span style="color:{danger if after.critical_paths else good}">'
            f"{len(after.critical_paths)}</span>",
            _delta_html(len(before.critical_paths), len(after.critical_paths)),
        ),
    ]
    body = "".join(
        f'<div class="br-card"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div>{delta}</div>'
        for label, value, delta in cards
    )
    return f'<div class="br-cards">{body}</div>'


# ---------------------------------------------------------------------------
# Graph section
# ---------------------------------------------------------------------------
def legend_html() -> str:
    items = "".join(
        f'<span><span class="br-dot" style="background:{color}"></span>{label}</span>'
        for label, color in LEGEND
    )
    return (
        f'<div class="br-legend">{items}'
        "<span><b style=\"color:#f87171\">&#9473;&#9473;</b> &nbsp;new attack path</span>"
        "<span style=\"color:#8fa3bd\">faded = unchanged infrastructure</span></div>"
    )


def path_chip(labels: List[str], dangerous: bool = True) -> str:
    arrow = " &nbsp;&rarr;&nbsp; "
    css = "br-path" if dangerous else "br-path br-path-good"
    return f'<div class="{css}">{arrow.join(esc(label) for label in labels)}</div>'


def section_graphs(diff: GraphDiff) -> None:
    heading("Infrastructure attack graph")
    st.markdown(legend_html(), unsafe_allow_html=True)

    highlight_before = diff.verdict is Verdict.IMPROVED
    nodes, edges = highlight_nodes(diff), highlight_edges(diff)
    removed_nodes = [n for p in diff.removed_attack_paths for n in p.nodes]
    removed_edges = [(e.source, e.target) for p in diff.removed_attack_paths for e in p.edges]

    left, right = st.columns(2, gap="medium")
    for column, (result, side) in zip((left, right), ((diff.before, "BEFORE"), (diff.after, "AFTER"))):
        with column:
            color = risk_color(result.risk_level)
            st.markdown(
                f'<div class="br-side"><span class="s">{side}</span>'
                f'<span class="m">{esc(Path(result.label).name or result.label)}</span>'
                f'<span class="m" style="color:{color};font-weight:800;margin-left:auto">'
                f"RISK {esc(result.risk_level.value)}</span>"
                f'<span class="m">{len(result.critical_paths)} critical path(s)</span></div>',
                unsafe_allow_html=True,
            )
            if side == "BEFORE":
                hl_nodes = removed_nodes if highlight_before else []
                hl_edges = removed_edges if highlight_before else []
            else:
                hl_nodes, hl_edges = ([], []) if highlight_before else (nodes, edges)
            embed_html(safe_graph_html(result.graph, hl_nodes, hl_edges, height=470), height=480)


# ---------------------------------------------------------------------------
# Priority 4: explainable hops
# ---------------------------------------------------------------------------
def render_hops(result: AnalysisResult, path: AttackPath) -> str:
    rows = []
    for edge, target_id in zip(path.edges, path.nodes[1:]):
        source_name = result.node(edge.source).name
        target = result.node(target_id)
        title = HOP_REASON_TITLES.get(target.type, "Step")
        relationship = edge.relationship.value.replace("_", " ").lower()
        detail = (
            f'<div class="t">relationship: {esc(relationship)}'
            f"{' &middot; resource: ' + esc(edge.terraform_resource) if edge.terraform_resource else ''}"
            "</div>"
        )
        evidence = (
            f'<div class="t" style="color:#fbbf24">{esc(edge.evidence)}</div>' if edge.evidence else ""
        )
        rows.append(
            f'<div class="br-hop"><div class="h">{esc(title)}: {esc(source_name)} '
            f"&rarr; {esc(target.name)}</div>"
            f'<div class="r">Reason: {esc(edge.reason)}</div>{detail}{evidence}</div>'
        )
    return "".join(rows)


def section_paths(diff: GraphDiff) -> None:
    new_critical = diff.new_critical_paths
    removed_critical = diff.removed_critical_paths

    if new_critical:
        heading("New attack path detected")
        for path in new_critical:
            st.markdown(path_chip(diff.display_path(path)), unsafe_allow_html=True)
            st.markdown(render_hops(diff.after, path), unsafe_allow_html=True)
            st.info(markdown_text(path.explanation), icon=":material/psychology:")
    elif removed_critical:
        heading("Attack path eliminated")
        for path in removed_critical:
            st.markdown(
                path_chip(diff.display_path(path, "before"), dangerous=False),
                unsafe_allow_html=True,
            )
        st.success(
            "The internet-to-sensitive-data path no longer exists in the modelled graph.",
            icon=":material/verified_user:",
        )
    elif diff.after.critical_paths:
        heading("Existing attack paths")
        for path in diff.after.critical_paths:
            st.markdown(path_chip(diff.display_path(path)), unsafe_allow_html=True)
            st.markdown(render_hops(diff.after, path), unsafe_allow_html=True)
    else:
        heading("Attack paths")
        st.success(
            "No path from the internet to a resource marked sensitive was found in either "
            "configuration.",
            icon=":material/verified_user:",
        )


def section_change(diff: GraphDiff, before_dir: Path, after_dir: Path) -> None:
    heading("What changed")
    left, right = st.columns([3, 2], gap="medium")

    with left:
        st.caption("Terraform diff")
        patch = "".join(
            difflib.unified_diff(
                terraform_text(before_dir).splitlines(keepends=True),
                terraform_text(after_dir).splitlines(keepends=True),
                fromfile="before/main.tf",
                tofile="after/main.tf",
                n=3,
            )
        )
        st.code(patch or "(no textual difference)", language="diff")

    with right:
        st.caption("Graph impact")
        for edge in diff.new_edges:
            st.markdown(
                f"<b>+ new edge</b> <code>{esc(edge.source)}</code> &rarr; <code>{esc(edge.target)}</code><br>"
                f'<span class="br-note">{esc(edge.reason)}</span>',
                unsafe_allow_html=True,
            )
        for edge in diff.removed_edges:
            st.markdown(
                f"<b>&minus; removed edge</b> <code>{esc(edge.source)}</code> &rarr; <code>{esc(edge.target)}</code><br>"
                f'<span class="br-note">{esc(edge.reason)}</span>',
                unsafe_allow_html=True,
            )
        if diff.newly_exposed:
            st.markdown(
                "<b>Newly internet-reachable:</b> " + ", ".join(f"<code>{esc(n)}</code>" for n in diff.newly_exposed),
                unsafe_allow_html=True,
            )
        if diff.no_longer_exposed:
            st.markdown(
                "<b>No longer reachable:</b> " + ", ".join(f"<code>{esc(n)}</code>" for n in diff.no_longer_exposed),
                unsafe_allow_html=True,
            )
        if not (diff.new_edges or diff.removed_edges):
            st.markdown('<span class="br-note">No graph edges changed.</span>', unsafe_allow_html=True)


def section_pr_report(diff: GraphDiff, decision: DeploymentDecision, before_dir: Path, after_dir: Path) -> None:
    """Priority 5: the comment BlastRadius would post on the pull request."""
    heading("Pull request security report")
    text = build_report(diff, decision, before_dir, after_dir)
    status_color = "#34d399" if decision.passed else "#f87171"
    st.markdown(
        f'<span class="br-note">This is the check BlastRadius would post on the PR. '
        f'Status: <b style="color:{status_color}">'
        f'{"PASSED" if decision.passed else "FAILED"}</b>.</span>',
        unsafe_allow_html=True,
    )
    # st.code gives a one-click copy button in the top-right corner.
    st.code(text, language="markdown")
    st.download_button(
        "Download PR report",
        data=text,
        file_name="blastradius-pr-report.md",
        mime="text/markdown",
        icon=":material/download:",
        key="download_report",
    )


def section_remediation(after_dir: Path) -> None:
    heading("Remediation")
    plan = remediation.generate_safer_config(validated_directory(after_dir))

    if not plan.recommendations:
        st.success("No remediation needed for this configuration.", icon=":material/task_alt:")
        return

    for rec in plan.recommendations:
        with st.container(border=True):
            st.markdown(
                f"<b>{esc(rec.title)}</b> &nbsp;"
                f'<span style="color:{risk_color(rec.severity)};font-weight:800;font-size:.85rem">'
                f"{rec.severity.value}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f'<span class="br-note">{esc(rec.detail)}</span>', unsafe_allow_html=True)
            cols = st.columns(2)
            cols[0].code(rec.current, language="hcl")
            cols[1].code(rec.recommended, language="hcl")

    if not plan.can_autofix:
        st.caption("No automatic patch available for these findings - apply the guidance manually.")
        return

    st.caption("Generated safer configuration")
    st.code(plan.diff, language="diff")
    if st.button(
        "Generate Safer Configuration & Re-analyze",
        type="primary",
        use_container_width=True,
        key="apply_fix",
    ):
        apply_remediation(after_dir, plan)


def section_details(diff: GraphDiff) -> None:
    with st.expander("Security score breakdown"):
        st.markdown(
            "Deterministic heuristic starting at **100**. This is a demo aid, not a validated "
            "risk metric."
        )
        for label, result in (("Before", diff.before), ("After", diff.after)):
            st.markdown(f"**{label}: {result.score}/100**")
            if not result.score_breakdown:
                st.markdown('<span class="br-note">No deductions.</span>', unsafe_allow_html=True)
            for item in result.score_breakdown:
                st.markdown(
                    f'<span class="br-note">{esc(item["points"])} &nbsp; {esc(item["finding"])} '
                    f'(x{esc(item["count"])})</span>',
                    unsafe_allow_html=True,
                )
        st.caption(
            "Penalty table: " + ", ".join(f"{v[2]} = -{v[0]} (cap -{v[1]})" for v in PENALTIES.values())
        )

    with st.expander("All graph edges (after)"):
        for source, target, data in sorted(diff.after.graph.edges(data=True)):
            edge = data["edge"]
            st.markdown(
                f"<code>{esc(source)}</code> &rarr; <code>{esc(target)}</code> &nbsp; <b>{esc(edge.relationship.value)}</b> "
                f'&nbsp;<span class="br-note">{esc(edge.reason)}</span>',
                unsafe_allow_html=True,
            )

    with st.expander("Model scope and limitations"):
        st.markdown(
            """
BlastRadius uses a **simplified, intentionally incomplete** model of AWS reachability.

* Supported resources: security groups, EC2 instances, IAM roles / instance profiles, S3 buckets.
* Reachability is `INTERNET -> SECURITY_GROUP -> EC2 -> IAM_ROLE -> S3_BUCKET -> SENSITIVE_DATA`.
* VPC routing, NACLs, subnet placement, bucket policies, SCPs and KMS are **not** modelled, so a
  path shown here is not proof of exploitability, and the absence of a path is not proof of safety.
* Sensitivity comes from Terraform tags (`Sensitive = "true"` or a sensitive `DataClass`).
* Analysis is entirely static and local: no AWS credentials are used and nothing is deployed.
"""
        )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def sidebar() -> Tuple[Path, Path]:
    with st.sidebar:
        st.markdown("## Demo scenarios")
        st.caption("Three prepared changes, each with a different root cause.")

        for scenario in scenarios.SCENARIOS:
            if st.button(
                scenario.title,
                key=f"scenario_{scenario.id}",
                use_container_width=True,
                help=scenario.change,
            ):
                queue_scenario(scenario.before, scenario.after)

        st.divider()
        st.toggle(
            "Demo Mode",
            key="demo_mode",
            help="Single-screen presentation view: scenario, decision, graph, fix.",
        )

        if st.session_state.demo_mode or not trusted_local_enabled():
            for key in ("before_dir", "after_dir"):
                st.session_state[key] = st.session_state[key]
            if not trusted_local_enabled():
                st.caption("Hosted demo: bundled scenarios only. Analyze private infrastructure locally or in CI.")
            return Path(st.session_state.before_dir), Path(st.session_state.after_dir)

        with st.expander("Advanced: Analyze Git change"):
            st.caption("Compare two refs of a local repository. Your working tree is untouched.")
            repo = st.text_input("Repository directory", key="git_repo")
            base = st.text_input("Base ref", key="git_base")
            head = st.text_input("Candidate ref", key="git_head")
            tf_dir = st.text_input("Terraform directory (optional)", key="git_dir")
            if st.button("Analyze Git change", use_container_width=True, key="analyze_git"):
                _run_git_comparison(repo, base, head, tf_dir)

        with st.expander("Advanced: Compare local directories"):
            before_dir = st.text_input("BEFORE directory", key="before_dir")
            after_dir = st.text_input("AFTER directory", key="after_dir")
            if st.button("Re-analyze", use_container_width=True, key="reanalyze"):
                st.rerun()

        st.divider()
        st.caption(
            "Static analysis only. No AWS credentials are read and nothing is deployed. "
            "Simplified attack-path model - see Details."
        )

    return Path(before_dir), Path(after_dir)


def _run_git_comparison(repo: str, base: str, head: str, tf_dir: str) -> None:
    """Materialize two Git refs and switch the dashboard onto them."""
    if not trusted_local_enabled():
        st.error("Local Git access is disabled in the hosted demo.")
        return
    if not (repo and base and head):
        st.error("Repository, base ref and candidate ref are all required.")
        return
    target = new_job("git")
    try:
        repository = checked_path(repo)
        if (repository / ".git").exists() or (repository / ".git").is_symlink():
            checked_path(repository / ".git")
        if tf_dir and (Path(tf_dir).is_absolute() or ".." in Path(tf_dir).parts or "\\" in tf_dir or ":" in tf_dir):
            raise StorageError("Terraform directory must stay within the repository.")
        comparison = gitsource.prepare_comparison(repository, base, head, target, tf_dir or None)
        validated_directory(comparison.before_dir)
        validated_directory(comparison.after_dir)
        policy = gitsource.base_policy(comparison)
    except (gitsource.GitAnalysisError, PolicyError, StorageError, OSError) as error:
        workspace().discard_job(target)
        st.error(markdown_text(error))
        return
    st.session_state.git_summary = comparison.summary
    st.session_state.git_policy = (str(comparison.before_dir), str(comparison.after_dir), policy)
    queue_scenario(comparison.before_dir, comparison.after_dir)


def product_header() -> None:
    st.markdown(
        '<p class="br-title">BlastRadius</p>'
        '<p class="br-sub">Know the blast radius before you merge.</p>'
        '<p class="br-kicker">Attack-path change analysis for Terraform pull requests. '
        "Your Terraform diff shows what changed - BlastRadius shows what became "
        "<b>reachable</b>.</p>",
        unsafe_allow_html=True,
    )


def scenario_chip(before_dir: Path, after_dir: Path) -> None:
    active = scenarios.by_dirs(before_dir, after_dir)
    if not active:
        summary = st.session_state.get("git_summary")
        if summary:
            st.markdown(
                f'<p class="br-kicker" style="margin-top:-.9rem">Git comparison: '
                f"<code>{esc(summary)}</code></p>",
                unsafe_allow_html=True,
            )
        return
    st.markdown(
        f'<p class="br-kicker" style="margin-top:-.9rem">Scenario: '
        f'<b style="color:#e8eef8">{esc(active.title)}</b> &middot; root cause: '
        f"{esc(active.root_cause)} &middot; change: <code>{esc(active.change)}</code></p>",
        unsafe_allow_html=True,
    )


def path_summary_line(diff: GraphDiff) -> None:
    """One-line answer to 'what became reachable?'."""
    paths = diff.new_critical_paths or diff.after.critical_paths
    if paths:
        st.markdown(path_chip(diff.display_path(paths[0])), unsafe_allow_html=True)
    elif diff.removed_critical_paths:
        st.markdown(
            path_chip(diff.display_path(diff.removed_critical_paths[0], "before"), dangerous=False),
            unsafe_allow_html=True,
        )
    else:
        st.success("No internet-to-sensitive-data path in either configuration.",
                   icon=":material/verified_user:")


def primary_action(after_dir: Path, key: str) -> None:
    """The single most useful next step, surfaced on the Overview tab."""
    plan = remediation.generate_safer_config(validated_directory(after_dir))
    if plan.can_autofix:
        if st.button(
            "Generate Safer Configuration & Re-analyze",
            type="primary",
            use_container_width=True,
            icon=":material/build:",
            key=key,
        ):
            apply_remediation(after_dir, plan)
    elif plan.recommendations:
        st.info(
            f"{len(plan.recommendations)} manual remediation recommendation(s) - see the "
            "Remediation tab.",
            icon=":material/lightbulb:",
        )


def render_overview(diff: GraphDiff, decision: DeploymentDecision, after_dir: Path) -> None:
    st.markdown(decision_banner(decision, diff), unsafe_allow_html=True)
    st.markdown(decision_reasons(decision), unsafe_allow_html=True)
    st.markdown(summary_cards(diff.before, diff.after), unsafe_allow_html=True)
    heading("What became reachable")
    path_summary_line(diff)
    primary_action(after_dir, key="apply_fix_primary")


def render_tabs(
    diff: GraphDiff, decision: DeploymentDecision, before_dir: Path, after_dir: Path
) -> None:
    overview, attack_path, infra_diff, pr_report, remediate = st.tabs(
        ["Overview", "Attack Path", "Infrastructure Diff", "PR Security Report", "Remediation"]
    )
    with overview:
        render_overview(diff, decision, after_dir)
    with attack_path:
        section_graphs(diff)
        section_paths(diff)
    with infra_diff:
        section_change(diff, before_dir, after_dir)
        section_details(diff)
    with pr_report:
        section_pr_report(diff, decision, before_dir, after_dir)
    with remediate:
        section_remediation(after_dir)


def render_demo_mode(
    diff: GraphDiff, decision: DeploymentDecision, before_dir: Path, after_dir: Path
) -> None:
    """Phase 7: a single uncluttered screen for a live presentation."""
    st.markdown(decision_banner(decision, diff), unsafe_allow_html=True)
    st.markdown(summary_cards(diff.before, diff.after), unsafe_allow_html=True)
    section_graphs(diff)
    section_paths(diff)
    if diff.removed_critical_paths and decision.passed:
        st.success(
            "BLOCK CHANGE → SAFE TO MERGE — re-analysis confirms the attack path is eliminated."
        )
    heading("Remediation")
    primary_action(after_dir, key="demo_apply_fix")


def render_app() -> None:
    if "workspace" not in st.session_state:
        st.session_state.workspace = SessionWorkspace.create()
    try:
        workspace().touch()
    except FileNotFoundError:
        st.session_state.workspace = SessionWorkspace.create()
        for key in ("before_dir", "after_dir", "pending_scenario", "git_policy", "git_summary", "last_simulation"):
            st.session_state.pop(key, None)
        st.info("Your temporary demo session expired. The bundled scenario has been restored.")
    cleanup_expired(workspace().root)
    st.session_state.setdefault("before_dir", str(SAFE_DIR))
    st.session_state.setdefault("after_dir", str(VULNERABLE_DIR))
    st.session_state.setdefault("demo_mode", False)
    st.session_state.setdefault("git_repo", str(ROOT))
    st.session_state.setdefault("git_base", "main")
    st.session_state.setdefault("git_head", "")
    st.session_state.setdefault("git_dir", "")
    _apply_pending_scenario()

    before_dir, after_dir = sidebar()
    product_header()

    before_dir, after_dir = validated_directory(before_dir), validated_directory(after_dir)
    workspace().prune((before_dir, after_dir))

    scenario_chip(before_dir, after_dir)
    section_simulator(before_dir)

    before = analyze_dir(before_dir, str(before_dir))
    after = analyze_dir(after_dir, str(after_dir))
    diff = compare(before, after)
    try:
        binding = st.session_state.get("git_policy")
        policy = binding[2] if binding and binding[:2] == (str(before_dir), str(after_dir)) else discover_policy(before_dir)
    except PolicyError as error:
        st.error(markdown_text(error))
        return
    decision = decide(diff, policy)
    if policy.source:
        st.caption(markdown_text(policy.describe()))
    for note in decision.policy_notes:
        if not st.session_state.demo_mode:
            st.caption(markdown_text(note))

    if st.session_state.get("demo_mode"):
        render_demo_mode(diff, decision, before_dir, after_dir)
    else:
        render_tabs(diff, decision, before_dir, after_dir)


def main() -> None:
    st.set_page_config(page_title="BlastRadius", page_icon=":material/radar:", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        render_app()
    except StorageError as error:
        st.error(markdown_text(error))
    except (OSError, ValueError, LarkError) as error:
        if trusted_local_enabled():
            st.error(markdown_text(error))
        else:
            st.error("The selected demo input is unavailable or invalid. Choose a bundled scenario to continue.")


if __name__ == "__main__":
    main()
