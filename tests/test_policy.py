import copy
import io

import pytest

from blastradius.cli import run
from blastradius.graph import analyze, build_graph, compare
from blastradius.policy import Policy, PolicyError, discover_policy, load_policy_data, load_policy_file
from blastradius.security.decision import Decision, decide


def public_change(safe_config, port):
    changed = copy.deepcopy(safe_config)
    sg = changed.by_address('aws_security_group.web')
    sg.attributes['ingress'][0].update(from_port=port, to_port=port, cidr_blocks=['0.0.0.0/0'])
    for config in (safe_config, changed):
        config.by_address('aws_s3_bucket.customer_data').attributes['tags'] = {}
    return compare(analyze(build_graph(safe_config)), analyze(build_graph(changed)))


def test_legacy_default_keeps_ssh_significant(safe_config):
    diff = public_change(safe_config, 22)
    assert decide(diff).decision is Decision.REVIEW
    assert decide(diff, load_policy_data({'version': 1})).decision is Decision.BLOCK


def test_policy_preserves_public_https_context(safe_config):
    diff = public_change(safe_config, 443)
    assert decide(diff, load_policy_data({'version': 1})).decision is Decision.REVIEW
    assert decide(diff, Policy(allow_public_https=False)).decision is Decision.BLOCK


def test_https_exception_does_not_hide_sensitive_paths(safe_result, vulnerable_config):
    vulnerable_config.by_address('aws_security_group.web').attributes['ingress'][0].update(
        from_port=443, to_port=443
    )
    diff = compare(safe_result, analyze(build_graph(vulnerable_config)))
    assert decide(diff, Policy(allow_public_https=True)).decision is Decision.BLOCK


def test_explicit_disabled_gates_still_report_findings(safe_result, vulnerable_result):
    diff = compare(safe_result, vulnerable_result)
    policy = Policy(block_new_critical_paths=False, block_new_sensitive_exposure=False)
    decision = decide(diff, policy)
    assert decision.decision is Decision.REVIEW
    assert len(diff.new_critical_paths) == 1
    assert len(decision.reasons) == 4
    assert any('disabled' in note for note in decision.policy_notes)


def test_score_threshold_is_enforced_without_mutating_score(safe_result, vulnerable_result):
    diff = compare(vulnerable_result, vulnerable_result)
    decision = decide(diff, Policy(minimum_security_score=70))
    assert decision.decision is Decision.BLOCK
    assert any('below minimum' in note for note in decision.policy_notes)
    assert vulnerable_result.score == 20
    assert decide(compare(vulnerable_result, safe_result), Policy(minimum_security_score=70)).passed


@pytest.mark.parametrize('data', [
    {'version': 2}, {'gate': {'block_new_critical_paths': 'false'}},
    {'thresholds': {'minimum_security_score': -1}},
    {'thresholds': {'minimum_security_score': True}},
    {'thresholds': {'minimum_security_score': 70.5}},
    {'gate': {'typo': True}}, {'oops': {}}, ['bad'],
])
def test_invalid_policy_is_rejected(data):
    with pytest.raises(PolicyError):
        load_policy_data(data)


def test_discovery_and_cli_error(tmp_path):
    assert discover_policy(tmp_path).is_default
    path = tmp_path / 'blastradius.yml'
    path.write_text('version: 1\nthresholds:\n  minimum_security_score: 95\n', encoding='utf-8')
    assert discover_policy(tmp_path).minimum_security_score == 95
    path.write_text('version: 999\n', encoding='utf-8')
    with pytest.raises(PolicyError):
        load_policy_file(path)
    out = io.StringIO()
    assert run(['--before', 'examples/safe', '--after', 'examples/safe', '--policy', str(path)], stream=out) == 2


def test_policy_cli_exit_and_reasons(tmp_path):
    path = tmp_path / 'policy.yml'
    path.write_text('version: 1\nthresholds:\n  minimum_security_score: 90\n', encoding='utf-8')
    out = io.StringIO()
    assert run(['--before', 'examples/vulnerable', '--after', 'examples/vulnerable', '--policy', str(path)], stream=out) == 1
    assert 'below minimum' in out.getvalue()
