"""Regression checks for AWS modeling and bounded graph traversal."""

from concurrent.futures import ThreadPoolExecutor

import networkx as nx
import pytest

from blastradius.graph import analyze, build_graph, compare
from blastradius.graph.attack_paths import MAX_PATH_WORK, MAX_PATHS_PER_TARGET
from blastradius.graph.graph_builder import edge_of
from blastradius.parser import parse_directory
from blastradius.parser.models import (
    INTERNET_ID, GraphEdge, NodeType, ParsedConfig, Relationship, ResourceNode,
    TerraformResource,
)
from blastradius.parser.plan_parser import parse_plan
from blastradius.security.decision import Decision, decide
from blastradius.security.rules import aws_pattern_matches, public_bucket_findings, public_ingress_findings
from tests.conftest import SAFE_DIR, VULNERABLE_DIR


def bucket_config(acl="private", statement=None, **flags):
    bucket = TerraformResource("aws_s3_bucket", "data", {
        "bucket": "test-data", "arn": "arn:aws:s3:::test-data",
        "acl": acl, "tags": {"Sensitive": "true"},
    }, "main.tf")
    resources = [bucket]
    if statement is not None:
        resources.append(TerraformResource("aws_s3_bucket_policy", "public", {
            "bucket": "aws_s3_bucket.data.id", "policy": {"Statement": [statement]},
        }, "main.tf"))
    if flags:
        resources.append(TerraformResource("aws_s3_bucket_public_access_block", "block", {
            "bucket": "aws_s3_bucket.data.id", **flags,
        }, "main.tf"))
    return ParsedConfig(resources=resources)


def public_statement(**overrides):
    return {
        "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::test-data/*", **overrides,
    }


@pytest.mark.parametrize(("flag", "remains_public"), [
    ("block_public_acls", True),
    ("ignore_public_acls", False),
    ("block_public_policy", True),
    ("restrict_public_buckets", True),
])
def test_acl_controls_distinguish_creation_blocks_from_effective_access(flag, remains_public):
    config = bucket_config("public-read", **{flag: True})
    result = analyze(build_graph(config))
    assert bool(result.critical_paths) is remains_public
    assert result.complete


@pytest.mark.parametrize(("flag", "remains_public"), [
    ("block_public_acls", True),
    ("ignore_public_acls", True),
    ("block_public_policy", True),
    ("restrict_public_buckets", False),
])
def test_policy_controls_distinguish_new_policy_block_from_existing_policy(flag, remains_public):
    config = bucket_config(statement=public_statement(), **{flag: True})
    result = analyze(build_graph(config))
    assert bool(result.critical_paths) is remains_public
    assert result.complete


def test_public_controls_are_bucket_scoped():
    config = bucket_config("public-read", ignore_public_acls=True)
    config.resources.append(TerraformResource("aws_s3_bucket", "other", {
        "acl": "public-read", "tags": {"Sensitive": "true"},
    }))
    result = analyze(build_graph(config))
    assert result.reachable_sensitive == ["aws_s3_bucket.other"]


def test_external_acl_resource_is_ignored_only_when_ignore_public_acls_is_true():
    config = bucket_config(ignore_public_acls=True)
    config.resources.append(TerraformResource("aws_s3_bucket_acl", "grant", {
        "bucket": "aws_s3_bucket.data.id", "acl": "public-read",
    }))
    assert not public_bucket_findings(config.resources[0], config.resources)
    config.resources[1].attributes["ignore_public_acls"] = False
    assert public_bucket_findings(config.resources[0], config.resources)


def test_conditional_policy_remains_possible_and_requires_review_with_restriction():
    config = bucket_config(statement=public_statement(Condition={"StringEquals": {"aws:SourceVpc": "vpc-1"}}),
                           restrict_public_buckets=True)
    result = analyze(build_graph(config))
    assert result.critical_paths and not result.complete
    assert edge_of(result.graph, INTERNET_ID, "aws_s3_bucket.data").confidence == "conditional"
    assert decide(compare(result, result)).decision is Decision.REVIEW


@pytest.mark.parametrize("principal", [
    {"Service": "*"}, {"AWS": "arn:aws:iam::123456789012:root"},
    {"AWS": "arn:aws:iam::*:root"}, ["*"],
])
def test_nonanonymous_principals_do_not_become_internet(principal):
    config = bucket_config(statement=public_statement(Principal=principal))
    assert not public_bucket_findings(config.resources[0], config.resources)


@pytest.mark.parametrize("principal", ["*", {"AWS": "*"}, {"AWS": ["*", "123456789012"]}])
def test_wildcard_aws_principals_are_anonymous(principal):
    config = bucket_config(statement=public_statement(Principal=principal))
    assert public_bucket_findings(config.resources[0], config.resources)


@pytest.mark.parametrize(("action", "read"), [
    ("s3:PutObject", False), ("s3:ListBucket", False), ("s3:GetBucketLocation", False),
    ("s3:DeleteObject", False), ("s3:GetObjectAcl", False), ("ec2:*", False),
    ("s3:GetObject", True), ("s3:GetObjectVersion", True), ("S3:GET*", True),
    ("s3:Get?bject", True), ("s3:*", True), ("*", True),
    ("s3:Get[O]bject", False),
])
def test_public_access_requires_object_read_action(action, read):
    config = bucket_config(statement=public_statement(Action=action))
    assert bool(public_bucket_findings(config.resources[0], config.resources)) is read


@pytest.mark.parametrize(("resource", "read"), [
    ("arn:aws:s3:::other/*", False), ("arn:aws:s3:::test-data", False),
    ("arn:aws:s3:::test-data/", False), ("arn:aws:s3:::test-*/*", True),
    ("arn:aws:s3:::test-data/private/key", True),
    ("${aws_s3_bucket.data.arn}/*", True), ("*", True),
])
def test_public_policy_resource_scope_must_include_objects(resource, read):
    config = bucket_config(statement=public_statement(Resource=resource))
    assert bool(public_bucket_findings(config.resources[0], config.resources)) is read


def test_wildcard_matching_handles_adversarial_nonmatch_without_backtracking_explosion():
    assert not aws_pattern_matches("a" * 2000, "*a" * 100 + "b")
    assert aws_pattern_matches("a[b]", "a[b]")
    assert not aws_pattern_matches("ab", "a[b]")


def test_authenticated_acl_is_not_anonymous_and_cannot_be_called_safe():
    result = analyze(build_graph(bucket_config("authenticated-read")))
    assert not result.critical_paths and not result.complete
    assert decide(compare(result, result)).decision is Decision.REVIEW


def test_write_only_iam_edge_is_privilege_evidence_not_proof_of_read():
    config = parse_directory(VULNERABLE_DIR)
    policy = config.by_address("aws_iam_role_policy.app_s3_read")
    policy.attributes["policy"] = {"Statement": [{
        "Effect": "Allow", "Action": "s3:PutObject", "Resource": "${aws_s3_bucket.customer_data.arn}/*",
    }]}
    result = analyze(build_graph(config))
    edge = edge_of(result.graph, "aws_iam_role.app", "aws_s3_bucket.customer_data")
    assert edge.category == "privilege"
    assert edge.metadata["data_read"] is False
    assert "not proof of data exfiltration" in result.critical_paths[0].explanation


def test_plan_public_access_block_relationship_is_recovered_from_bucket_id():
    entries = [
        {"address": "aws_s3_bucket.data", "type": "aws_s3_bucket", "name": "data",
         "values": {"id": "test-data", "bucket": "test-data", "acl": "public-read"}},
        {"address": "aws_s3_bucket_public_access_block.data", "type": "aws_s3_bucket_public_access_block",
         "name": "data", "values": {"bucket": "test-data", "ignore_public_acls": True}},
    ]
    result = analyze(build_graph(parse_plan({"planned_values": {"root_module": {"resources": entries}}})))
    assert not result.graph.has_edge(INTERNET_ID, "aws_s3_bucket.data")
    assert result.complete


def test_all_demo_edges_have_auditable_metadata_without_host_paths():
    config = parse_directory(VULNERABLE_DIR)
    for resource in config.resources:
        resource.source_file = "/private/worker/snapshot/main.tf"
    graph = build_graph(config)
    for _, _, data in graph.edges(data=True):
        edge = data["edge"]
        assert edge.confidence and edge.category and edge.remediation and edge.evidence
        assert edge.source_file == "main.tf"


def test_parallel_calls_do_not_share_graph_attributes_or_diagnostics():
    config = parse_directory(SAFE_DIR)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: analyze(build_graph(config)), range(8)))
    results[0].graph.nodes["aws_s3_bucket.customer_data"]["node"].attributes["tags"]["Sensitive"] = False
    results[0].diagnostics.clear()
    assert all(r.score == 100 and r.complete for r in results)
    assert config.by_address("aws_s3_bucket.customer_data").tags()["Sensitive"] == "true"
    assert results[1].graph.nodes["aws_s3_bucket.customer_data"]["node"].attributes["tags"]["Sensitive"] == "true"


def layered_graph(layers, reaches_target):
    graph = nx.DiGraph()
    graph.add_node(INTERNET_ID, node=ResourceNode(INTERNET_ID, NodeType.INTERNET, "Internet"))
    graph.add_node("zz-target", node=ResourceNode("zz-target", NodeType.SENSITIVE_DATA, "Sensitive"))
    previous = [INTERNET_ID]
    for layer in range(layers):
        current = [f"a{layer:02d}-{i}" for i in range(2)]
        for node in current:
            graph.add_node(node, node=ResourceNode(node, NodeType.IAM_ROLE, node))
        for source in previous:
            for target in current:
                add_edge(graph, source, target)
        previous = current
    if reaches_target:
        for source in previous:
            add_edge(graph, source, "zz-target")
    else:
        add_edge(graph, INTERNET_ID, "zz-target")
    return graph


def add_edge(graph, source, target):
    graph.add_edge(source, target, edge=GraphEdge(source, target, Relationship.CAN_ACCESS, "test edge"))


def test_path_output_budget_is_deterministic_across_insertion_order():
    graph = layered_graph(9, True)
    reverse = nx.DiGraph()
    reverse.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reverse.add_edges_from(reversed(list(graph.edges(data=True))))
    first, second = analyze(graph), analyze(reverse)
    assert first.path_keys == second.path_keys
    assert len(first.attack_paths) == MAX_PATHS_PER_TARGET
    assert first.paths_truncated and not first.complete
    assert first.path_work <= MAX_PATH_WORK
    assert decide(compare(first, first)).decision is Decision.REVIEW


def test_exponential_deadends_hit_work_budget_even_with_one_output_path():
    result = analyze(layered_graph(20, False))
    assert len(result.attack_paths) == 1
    assert result.path_work == MAX_PATH_WORK
    assert result.paths_truncated
    assert [d.code for d in result.diagnostics] == ["PATHS_TRUNCATED"]


def test_depth_budget_retains_reachability_even_when_path_is_not_enumerated():
    graph = nx.DiGraph()
    ids = [INTERNET_ID, *[f"node-{i}" for i in range(40)], "bucket", "sensitive"]
    for name in ids:
        kind = NodeType.SENSITIVE_DATA if name == "sensitive" else NodeType.S3_BUCKET
        graph.add_node(name, node=ResourceNode(name, kind, name, sensitive=name == "bucket"))
    for source, target in zip(ids, ids[1:]):
        add_edge(graph, source, target)
    result = analyze(graph)
    assert result.reachable_sensitive == ["bucket"]
    assert result.paths_truncated and not result.attack_paths
    assert result.risk_level.value == "CRITICAL"
    assert result.score < 100


def test_invalid_ports_do_not_crash_or_invent_an_administrative_port():
    malformed = TerraformResource("aws_security_group", "bad", {"ingress": [{
        "protocol": "tcp", "from_port": "var.port", "to_port": None,
        "cidr_blocks": ["0.0.0.0/0"],
    }]})
    result = analyze(build_graph(ParsedConfig(resources=[malformed])))
    assert not result.complete and not public_ingress_findings(malformed)
    icmp = TerraformResource("aws_security_group", "ping", {"ingress": [{
        "protocol": "icmp", "from_port": 0, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"],
    }]})
    assert not public_ingress_findings(icmp)[0].is_admin_port


def test_global_path_output_budget():
    graph = layered_graph(7, True)
    for index in range(20):
        name = f"sensitive-{index}"
        graph.add_node(name, node=ResourceNode(name, NodeType.SENSITIVE_DATA, name))
        for source in ("a06-0", "a06-1"):
            add_edge(graph, source, name)
    result = analyze(graph)
    assert len(result.attack_paths) == 500 and result.paths_truncated


def test_graph_edge_budget_truncates_with_explicit_diagnostic():
    resources = []
    for index in range(143):
        resources.extend([
            TerraformResource("aws_iam_role", f"r{index}", {}),
            TerraformResource("aws_iam_role_policy", f"p{index}", {
                "role": f"aws_iam_role.r{index}.name",
                "policy": {"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]},
            }),
            TerraformResource("aws_s3_bucket", f"b{index}", {}),
        ])
    result = analyze(build_graph(ParsedConfig(resources=resources)))
    assert result.graph.number_of_edges() == 20_000
    assert not result.complete
    assert "GRAPH_TRUNCATED" in {d.code for d in result.diagnostics}
