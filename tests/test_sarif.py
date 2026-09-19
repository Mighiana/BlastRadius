import io
import json

from blastradius.cli import run
from blastradius.graph import compare
from blastradius.sarif import RULES, build_sarif
from tests.test_gitsource import repo


def test_sarif_structure_and_evidence(safe_result, vulnerable_result):
    document = build_sarif(compare(safe_result, vulnerable_result))
    assert document['version'] == '2.1.0'
    run_data = document['runs'][0]
    assert run_data['tool']['driver']['rules'] == RULES
    findings = run_data['results']
    assert findings[0]['ruleId'] == 'BR001'
    assert findings[0]['level'] == 'error'
    assert findings[0]['properties']['attackPath'][0] == 'INTERNET'
    assert findings[0]['properties']['recommendation']
    assert findings[0]['properties']['terraformResource'] == 'aws_security_group.web'
    assert 'region' not in findings[0]['locations'][0]['physicalLocation']
    assert len(findings[0]['codeFlows'][0]['threadFlows'][0]['locations']) == 5


def test_no_findings_for_identical_safe_config(safe_result):
    assert build_sarif(compare(safe_result, safe_result))['runs'][0]['results'] == []


def test_plan_cli_is_valid_json_and_sarif():
    for fmt in ('json', 'sarif'):
        out = io.StringIO()
        assert run(['--plan', 'examples/plans/ssh_open_plan.json', '--format', fmt], stream=out) == 1
        data = json.loads(out.getvalue())
        if fmt == 'sarif':
            assert data['version'] == '2.1.0'
        else:
            assert 'aws_cloudwatch_log_group' in data['unsupported_resource_types']


def test_git_sarif_has_repo_relative_files_and_no_temp_paths(repo):
    out = io.StringIO()
    assert run(['--repo', str(repo), '--base', 'main', '--head', 'feature', '--format', 'sarif'], stream=out) == 1
    data = json.loads(out.getvalue())
    loc = data['runs'][0]['results'][0]['locations'][0]
    assert loc['physicalLocation']['artifactLocation']['uri'] == 'infra/main.tf'
    assert 'blastradius-' not in out.getvalue()


def test_git_json_is_not_prefixed_with_diagnostics(repo):
    out = io.StringIO()
    assert run(['--repo', str(repo), '--base', 'main', '--head', 'feature', '--format', 'json'], stream=out) == 1
    assert json.loads(out.getvalue())['diagnostics']
