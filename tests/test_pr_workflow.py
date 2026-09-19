import io
from pathlib import Path

import yaml

from blastradius.cli import run
from blastradius.github_pr import MARKER

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / 'examples/github-action/blastradius-pr-check.yml'


def workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))


def test_workflow_uses_trusted_base_and_sha_inputs():
    data = workflow()
    assert 'pull_request' in data.get('on', data.get(True))
    assert 'pull_request_target' not in data.get('on', data.get(True))
    steps = data['jobs']['blast-radius']['steps']
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.base.sha }}'
    assert checkout['with']['persist-credentials'] is False
    assert data['env']['HEAD_SHA'] == '${{ github.event.pull_request.head.sha }}'
    scripts = '\n'.join(s.get('run', '') for s in steps)
    assert '${{ github.head_ref }}' not in scripts
    assert '${{ github.base_ref }}' not in scripts
    assert ' -I -m blastradius.' in scripts
    assert 'git checkout' not in scripts
    assert 'working-directory' not in data['jobs']['blast-radius']['defaults']['run']
    assert all(s.get('working-directory') == '${{ runner.temp }}' for s in steps if 'run' in s)


def test_comment_is_best_effort_but_gate_is_not():
    data = workflow()
    steps = data['jobs']['blast-radius']['steps']
    comment = next(s for s in steps if s.get('name') == 'Post or update one PR comment')
    assert comment['continue-on-error'] is True
    assert '--head-sha "$HEAD_SHA"' in comment['run']
    gate = steps[-1]
    assert gate['if'] == 'always()'
    assert 'continue-on-error' not in gate
    assert 'exit 1' in gate['run'] and 'exit 2' in gate['run']
    assert data['concurrency']['cancel-in-progress'] is True


def test_comment_file_generation_preserves_analysis_exit(tmp_path):
    report = tmp_path / 'report.md'
    for before, after, code in [('safe', 'vulnerable', 1), ('vulnerable', 'safe', 0)]:
        assert run(['--before', str(ROOT / 'examples' / before), '--after', str(ROOT / 'examples' / after),
                    '--comment-file', str(report)], stream=io.StringIO()) == code
        assert report.read_text(encoding='utf-8').startswith(MARKER)


def test_hosted_acceptance_uses_pinned_production_path():
    data = yaml.safe_load((ROOT / '.github/workflows/blastradius-hosted-test.yml').read_text(encoding='utf-8'))
    assert len(data['env']['BLASTRADIUS_REVISION']) == 40
    steps = data['jobs']['blast-radius']['steps']
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.base.sha }}'
    scripts = '\n'.join(s.get('run', '') for s in steps)
    assert '--github-action' in scripts
    assert '--terraform-dir examples/hosted-pr' in scripts
    assert ' -I -m blastradius.github_pr' in scripts
    assert steps[-1]['if'] == 'always()'
    assert 'working-directory' not in data['jobs']['blast-radius']['defaults']['run']
    assert all(s.get('working-directory') == '${{ runner.temp }}' for s in steps if 'run' in s)
    ci = yaml.safe_load((ROOT / '.github/workflows/blastradius.yml').read_text(encoding='utf-8'))
    assert any(s.get('run') == 'python -m pytest -q' for s in ci['jobs']['tests']['steps'])


def test_failed_report_write_is_not_a_pass(tmp_path):
    assert run(['--before', str(ROOT / 'examples/safe'), '--after', str(ROOT / 'examples/safe'),
                '--comment-file', str(tmp_path / 'missing' / 'report.md')], stream=io.StringIO()) == 2
