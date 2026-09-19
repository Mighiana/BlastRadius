import io
import json
import subprocess

import pytest

from blastradius.cli import run
from blastradius.github_context import GitHubContextError, PullRequestContext
from blastradius.policy import PolicyError, load_policy_data
from tests.test_gitsource import _git, repo


def event_environment(repo, tmp_path, base='main', head='feature'):
    def sha(ref):
        return subprocess.check_output(['git', 'rev-parse', ref], cwd=repo, text=True).strip()
    event = {'repository': {'full_name': 'owner/repo'}, 'pull_request': {
        'number': 3, 'base': {'sha': sha(base), 'repo': {'full_name': 'owner/repo'}},
        'head': {'sha': sha(head), 'ref': 'untrusted-branch-name', 'repo': {'full_name': 'fork/repo'}}}}
    path = tmp_path / 'event.json'
    path.write_text(json.dumps(event), encoding='utf-8')
    return {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REPOSITORY': 'owner/repo',
            'GITHUB_WORKSPACE': str(repo), 'GITHUB_EVENT_PATH': str(path),
            'GITHUB_OUTPUT': str(tmp_path / 'outputs'), 'GITHUB_STEP_SUMMARY': str(tmp_path / 'summary')}


def test_event_supplies_shas_and_fork_context(repo, tmp_path, monkeypatch):
    env = event_environment(repo, tmp_path)
    context = PullRequestContext.from_environment(env)
    assert context.number == 3 and context.repository == 'owner/repo'
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    out = io.StringIO()
    assert run(['--github-action', '--format', 'json'], stream=out) == 1
    payload = json.loads(out.getvalue())
    assert payload['decision'] == 'BLOCK CHANGE'
    assert 'critical_paths_added=1' in (tmp_path / 'outputs').read_text()


@pytest.mark.parametrize('field,value', [('GITHUB_EVENT_NAME', 'pull_request_target'),
                                       ('GITHUB_EVENT_NAME', 'push'),
                                       ('GITHUB_REPOSITORY', 'different/repo')])
def test_untrusted_context_is_rejected(repo, tmp_path, field, value):
    env = event_environment(repo, tmp_path)
    env[field] = value
    with pytest.raises(GitHubContextError):
        PullRequestContext.from_environment(env)


def test_branch_names_cannot_replace_event_shas(repo, tmp_path):
    env = event_environment(repo, tmp_path)
    path = tmp_path / 'event.json'
    data = json.loads(path.read_text())
    data['pull_request']['head']['sha'] = 'feature; echo unsafe'
    path.write_text(json.dumps(data))
    with pytest.raises(GitHubContextError):
        PullRequestContext.from_environment(env)


def test_multiple_roots_require_explicit_or_base_config(repo, tmp_path):
    _git(repo, 'checkout', '-q', 'main')
    (repo / 'other').mkdir()
    (repo / 'other' / 'main.tf').write_text('resource "aws_s3_bucket" "other" { bucket = "other" }')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'add second root')
    args = ['--repo', str(repo), '--base', 'main', '--head', 'feature']
    out = io.StringIO()
    assert run(args, stream=out) == 2
    assert 'Multiple Terraform directories' in out.getvalue()
    (repo / 'blastradius.yml').write_text('version: 1\nterraform_dir: infra\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'select trusted Terraform root')
    out = io.StringIO()
    assert run(args + ['--format', 'json'], stream=out) == 1
    assert json.loads(out.getvalue())['critical_paths_added'] == 1


@pytest.mark.parametrize('directory', ['../escape', '/absolute', 'C:\\absolute', '', 42])
def test_invalid_configured_root(directory):
    with pytest.raises(PolicyError):
        load_policy_data({'terraform_dir': directory})


def test_dot_prefixed_root_is_normalized():
    assert load_policy_data({'terraform_dir': './infra/'}).terraform_dir == 'infra'


def test_github_mode_rejects_manual_sha_override(repo, tmp_path, monkeypatch):
    for name, value in event_environment(repo, tmp_path).items():
        monkeypatch.setenv(name, value)
    assert run(['--github-action', '--head', 'feature'], stream=io.StringIO()) == 2
    assert 'decision=ERROR' in (tmp_path / 'outputs').read_text()
