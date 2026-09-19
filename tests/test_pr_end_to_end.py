import json
import os
import shutil
import subprocess
import sys

import pytest

from blastradius.github_pr import MARKER, publish_report
from blastradius.security.remediation import patch_public_admin_cidrs
from tests.conftest import ROOT
from tests.test_github_context import event_environment
from tests.test_github_pr import FakeClient, comment
from tests.test_gitsource import _git, repo
from tests.test_pr_workflow import workflow


def sha(repo, ref):
    return subprocess.check_output(['git', 'rev-parse', ref], cwd=repo, text=True).strip()


@pytest.fixture
def history(repo):
    risky = sha(repo, 'feature')
    _git(repo, 'checkout', '-q', 'feature')
    path = repo / 'infra' / 'main.tf'
    fixed, count = patch_public_admin_cidrs(path.read_text(encoding='utf-8'))
    assert count == 1
    path.write_text(fixed, encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'restrict administrative ingress')
    fixed_sha = sha(repo, 'feature')
    _git(repo, 'checkout', '-q', 'main')
    return repo, risky, fixed_sha


@pytest.mark.parametrize('fmt', ['summary', 'pr', 'json', 'sarif'])
def test_real_process_main_risky_and_remediation(history, fmt):
    repo, risky, fixed = history
    for head, expected in ((risky, 1), (fixed, 0)):
        result = subprocess.run([sys.executable, '-m', 'blastradius.cli', '--repo', str(repo),
                                 '--base', 'main', '--head', head, '--format', fmt],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert result.returncode == expected, result.stderr
        if fmt == 'json':
            payload = json.loads(result.stdout)
            assert payload['critical_paths_added'] == expected
            assert payload['security_score_after'] == (20 if expected else 100)
        elif fmt == 'sarif':
            payload = json.loads(result.stdout)
            findings = payload['runs'][0]['results']
            assert bool(findings) == bool(expected)
        else:
            assert ('BLOCK CHANGE' if expected else 'SAFE TO MERGE') in result.stdout


def test_workflow_environment_reports_outputs_and_one_comment(history, tmp_path):
    repo, risky, fixed = history
    client = FakeClient(head=risky)
    for head, expected in ((risky, 1), (fixed, 0)):
        env = {**os.environ, **event_environment(repo, tmp_path, head=head)}
        reports = tmp_path / 'reports'
        result = subprocess.run([sys.executable, '-m', 'blastradius.cli', '--github-action',
                                 '--report-dir', str(reports), '--format', 'json'],
                                cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert result.returncode == expected, result.stderr
        payload = json.loads((reports / 'result.json').read_text())
        assert payload == json.loads(result.stdout)
        assert payload['decision'] == ('BLOCK CHANGE' if expected else 'SAFE TO MERGE')
        outputs = dict(line.split('=', 1) for line in (tmp_path / 'outputs').read_text().splitlines())
        assert outputs['exit_code'] == str(expected)
        assert outputs['critical_paths_added'] == str(expected)
        report = (reports / 'report.md').read_text(encoding='utf-8')
        assert report.startswith(MARKER)
        if expected:
            assert '10.0.0.0/24' in report and '0.0.0.0/0' in report
        client.head = head
        publication = publish_report('owner/repo', 3, report, head_sha=head, client=client)
        assert publication.status == ('created' if expected else 'updated')
        client.pages = [[comment(report)]]
    assert [method for method, _, _ in client.calls if method != 'GET'] == ['POST', 'PATCH']
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == b''
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=repo).strip() == b'main'


@pytest.mark.parametrize('status,expected', [('0', 0), ('1', 1), ('2', 2), ('', 2), ('unexpected', 2)])
def test_actual_workflow_gate_shell_preserves_failure(status, expected):
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('Bash is required to validate the Linux workflow shell')
    steps = workflow()['jobs']['blast-radius']['steps']
    gate = steps[-1]['run']
    result = subprocess.run([bash, '-c', gate], env={**os.environ, 'ANALYSIS_EXIT': status},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == expected


def test_all_example_shell_steps_parse():
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('Bash is required to validate the Linux workflow shell')
    for step in workflow()['jobs']['blast-radius']['steps']:
        if 'run' in step:
            result = subprocess.run([bash, '-n'], input=step['run'], text=True, capture_output=True, timeout=10)
            assert result.returncode == 0, (step.get('name'), result.stderr)
