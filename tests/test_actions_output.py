import io
import json

from blastradius.cli import run
from blastradius.github_pr import MARKER
from tests.conftest import ROOT


def test_one_run_writes_consistent_outputs_and_artifacts(tmp_path):
    directory = tmp_path / 'reports'
    output = tmp_path / 'outputs'
    summary = tmp_path / 'summary'
    for before, after, code in [('safe', 'vulnerable', 1), ('vulnerable', 'safe', 0)]:
        args = ['--before', str(ROOT / 'examples' / before), '--after', str(ROOT / 'examples' / after),
                '--report-dir', str(directory), '--github-output', str(output), '--github-summary', str(summary), '--format', 'json']
        stdout = io.StringIO()
        assert run(args, stream=stdout) == code
        payload = json.loads(stdout.getvalue())
        assert json.loads((directory / 'result.json').read_text(encoding='utf-8')) == payload
        values = dict(line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines())
        for key in ('decision', 'security_score_before', 'security_score_after', 'critical_paths_added', 'sensitive_resources_added', 'exit_code'):
            assert str(payload[key]) == values[key]
        assert payload['critical_paths_added'] == code
        assert (directory / 'report.md').read_text(encoding='utf-8').startswith(MARKER)
        assert json.loads((directory / 'results.sarif').read_text())['version'] == '2.1.0'
    text = summary.read_text(encoding='utf-8')
    assert 'BlastRadius — BLOCKED' in text
    assert 'BlastRadius — PASSED' in text
    assert 'No new modeled critical attack paths' in text


def test_failed_analysis_emits_error_not_a_false_pass(tmp_path):
    directory = tmp_path / 'reports'
    output = tmp_path / 'outputs'
    summary = tmp_path / 'summary'
    assert run(['--before', str(tmp_path / 'missing'), '--after', str(ROOT / 'examples/safe'),
                '--report-dir', str(directory), '--github-output', str(output), '--github-summary', str(summary)], stream=io.StringIO()) == 2
    payload = json.loads((directory / 'result.json').read_text())
    assert payload['decision'] == 'ERROR' and payload['passed'] is False
    assert payload['critical_paths_added'] == ''
    assert 'BlastRadius — ERROR' in summary.read_text(encoding='utf-8')
    assert json.loads((directory / 'results.sarif').read_text())['runs'][0]['invocations'][0]['executionSuccessful'] is False


def test_hcl_unsupported_resources_are_visible_in_comment(tmp_path):
    before = tmp_path / 'before'
    after = tmp_path / 'after'
    before.mkdir()
    after.mkdir()
    source = 'resource "aws_lambda_function" "outside" { function_name = "not-modeled" }'
    (before / 'main.tf').write_text(source)
    (after / 'main.tf').write_text(source)
    directory = tmp_path / 'reports'
    assert run(['--before', str(before), '--after', str(after), '--report-dir', str(directory)], stream=io.StringIO()) == 0
    assert 'Outside current model coverage' in (directory / 'report.md').read_text(encoding='utf-8')
    assert json.loads((directory / 'result.json').read_text())['unsupported_resource_types'] == ['aws_lambda_function']
