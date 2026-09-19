"""Graph construction and attack-path detection."""

import networkx as nx

from blastradius.graph.graph_builder import build_graph, node_of, nodes_of_type
from blastradius.parser.models import INTERNET_ID, NodeType, Relationship, Risk


def test_graph_contains_expected_node_types(vulnerable_result):
    graph = vulnerable_result.graph
    types = {node_of(graph, n).type for n in graph.nodes}
    assert types == {
        NodeType.INTERNET,
        NodeType.SECURITY_GROUP,
        NodeType.EC2,
        NodeType.IAM_ROLE,
        NodeType.S3_BUCKET,
        NodeType.SENSITIVE_DATA,
    }


def test_security_group_to_ec2_edge_exists(safe_result):
    edge = safe_result.graph.edges["aws_security_group.web", "aws_instance.web_server"]["edge"]
    assert edge.relationship is Relationship.PROTECTS


def test_ec2_to_iam_role_edge_exists(safe_result):
    edge = safe_result.graph.edges["aws_instance.web_server", "aws_iam_role.app"]["edge"]
    assert edge.relationship is Relationship.ASSUMES_ROLE
    assert "instance profile" in edge.reason


def test_iam_role_to_s3_edge_exists(safe_result):
    edge = safe_result.graph.edges["aws_iam_role.app", "aws_s3_bucket.customer_data"]["edge"]
    assert edge.relationship is Relationship.CAN_ACCESS


def test_sensitive_bucket_gets_sensitive_data_node(safe_result):
    markers = nodes_of_type(safe_result.graph, NodeType.SENSITIVE_DATA)
    assert markers == ["sensitive_data.customer_data"]
    edge = safe_result.graph.edges["aws_s3_bucket.customer_data", "sensitive_data.customer_data"]["edge"]
    assert edge.relationship is Relationship.CONTAINS


def test_safe_config_has_no_internet_edge(safe_result):
    assert list(safe_result.graph.successors(INTERNET_ID)) == []


def test_vulnerable_config_has_internet_to_security_group_edge(vulnerable_result):
    edge = vulnerable_result.graph.edges[INTERNET_ID, "aws_security_group.web"]["edge"]
    assert edge.relationship is Relationship.INGRESS_ALLOWS
    assert edge.risk is Risk.CRITICAL


# --- The two assertions the whole demo depends on --------------------------
def test_safe_config_has_no_critical_attack_path(safe_result):
    assert safe_result.critical_paths == []
    assert safe_result.reachable_sensitive == []
    assert safe_result.exposed_resources == []
    assert safe_result.risk_level is Risk.LOW


def test_vulnerable_config_has_internet_to_sensitive_path(vulnerable_result):
    assert len(vulnerable_result.critical_paths) == 1
    path = vulnerable_result.critical_paths[0]
    assert path.nodes == [
        INTERNET_ID,
        "aws_security_group.web",
        "aws_instance.web_server",
        "aws_iam_role.app",
        "aws_s3_bucket.customer_data",
        "sensitive_data.customer_data",
    ]
    assert path.severity is Risk.CRITICAL
    assert vulnerable_result.risk_level is Risk.CRITICAL
    assert vulnerable_result.reachable_sensitive == ["aws_s3_bucket.customer_data"]


def test_vulnerable_exposed_resources_are_ec2_iam_and_s3(vulnerable_result):
    assert vulnerable_result.exposed_resources == [
        "aws_iam_role.app",
        "aws_instance.web_server",
        "aws_s3_bucket.customer_data",
    ]


def test_attack_path_explanation_is_populated(vulnerable_result):
    explanation = vulnerable_result.critical_paths[0].explanation
    assert "internet" in explanation.lower()
    assert "sensitive" in explanation.lower()


def test_path_edges_match_path_nodes(vulnerable_result):
    path = vulnerable_result.critical_paths[0]
    assert len(path.edges) == len(path.nodes) - 1
    for edge, (source, target) in zip(path.edges, zip(path.nodes, path.nodes[1:])):
        assert (edge.source, edge.target) == (source, target)


def test_every_edge_has_a_reason(vulnerable_result):
    for _, _, data in vulnerable_result.graph.edges(data=True):
        assert data["edge"].reason


def test_graph_is_acyclic_for_demo_configs(vulnerable_result):
    assert nx.is_directed_acyclic_graph(vulnerable_result.graph)


def test_analysis_is_deterministic():
    from blastradius.graph import analyze
    from blastradius.parser import parse_directory
    from tests.conftest import VULNERABLE_DIR

    first = analyze(build_graph(parse_directory(VULNERABLE_DIR)))
    second = analyze(build_graph(parse_directory(VULNERABLE_DIR)))
    assert first.path_keys == second.path_keys
    assert first.score == second.score
    assert first.exposed_resources == second.exposed_resources


def test_empty_config_produces_only_internet_node():
    from blastradius.parser.models import ParsedConfig

    graph = build_graph(ParsedConfig())
    assert list(graph.nodes) == [INTERNET_ID]
