import copy
import io
import json
import subprocess

import yaml

from blastradius import gitsource
from blastradius.cli import run
from blastradius.parser.inputs import parse_input
from blastradius.parser.plan_parser import load_plan, parse_plan
from tests.conftest import ROOT, SAFE_DIR
from tests.test_gitsource import _git, repo
from tests.test_plan_parser import PLAN


def test_shared_parser_accepts_hcl_directory_file_and_plan():
    directory = parse_input(SAFE_DIR)
    source = parse_input(SAFE_DIR / 'main.tf')
    plan = parse_input(PLAN, 'before')
    assert [r.address for r in directory.resources] == [r.address for r in source.resources]
    assert [r.address for r in plan.resources] == [r.address for r in source.resources]


def test_plan_does_not_apply_candidate_references_to_prior_state():
    data = load_plan(PLAN)
    data['configuration']['root_module']['resources'][0]['expressions']['iam_instance_profile'] = {
        'references': ['aws_iam_instance_profile.other.name']
    }
    prior = parse_plan(data, 'before')
    assert prior.by_address('aws_instance.web_server').get('iam_instance_profile') == 'aws_iam_instance_profile.app.name'


def test_unknown_reference_is_recovered_when_value_is_absent():
    data = load_plan(PLAN)
    instance = next(r for r in data['planned_values']['root_module']['resources'] if r['type'] == 'aws_instance')
    del instance['values']['vpc_security_group_ids']
    result = parse_plan(data)
    assert result.by_address('aws_instance.web_server').get('vpc_security_group_ids') == ['aws_security_group.web.id']


def test_real_module_instances_are_reported_not_collapsed():
    data = load_plan(PLAN)
    bucket = next(r for r in data['planned_values']['root_module']['resources'] if r['type'] == 'aws_s3_bucket')
    duplicate = copy.deepcopy(bucket)
    duplicate['address'] = 'module.other.aws_s3_bucket.customer_data'
    data['planned_values']['root_module']['resources'].append(duplicate)
    config = parse_plan(data)
    assert len([r for r in config.resources if r.type == 'aws_s3_bucket']) == 1
    assert any('module.other' in item for item in config.unsupported)


def test_policy_is_loaded_from_base_not_candidate_or_worktree(repo, tmp_path):
    _git(repo, 'checkout', '-q', 'feature')
    (repo / 'blastradius.yml').write_text('version: 1\ngate:\n  block_new_critical_paths: false\n  block_new_sensitive_exposure: false\n  block_public_admin_ports: false\n', encoding='utf-8')
    _git(repo, 'add', 'blastradius.yml')
    _git(repo, 'commit', '-qm', 'candidate attempts to weaken gate')
    (repo / 'infra' / 'main.tf').write_text('uncommitted work must survive', encoding='utf-8')
    before_status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo)
    out = io.StringIO()
    assert run(['--repo', str(repo), '--base', 'main', '--head', 'feature', '--format', 'json'], stream=out) == 1
    assert json.loads(out.getvalue())['decision'] == 'BLOCK CHANGE'
    assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo) == before_status
    assert (repo / 'infra' / 'main.tf').read_text() == 'uncommitted work must survive'


def test_git_options_are_not_accepted_as_refs(repo, tmp_path):
    out = io.StringIO()
    assert run(['--repo', str(repo), '--base=--help', '--head', 'feature'], stream=out) == 2
    assert 'Ref not found' in out.getvalue()


def test_malformed_hcl_is_a_clear_input_error(tmp_path):
    (tmp_path / 'main.tf').write_text('resource "broken" {', encoding='utf-8')
    out = io.StringIO()
    assert run(['--before', str(SAFE_DIR), '--after', str(tmp_path)], stream=out) == 2
    assert 'error:' in out.getvalue()


def test_workflows_have_real_pr_gate_and_no_placeholder_install():
    workflow = yaml.safe_load((ROOT / '.github/workflows/blastradius.yml').read_text(encoding='utf-8'))
    steps = workflow['jobs']['terraform-pr-gate']['steps']
    checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout'))
    assert checkout['with']['ref'] == '${{ github.event.pull_request.base.sha }}'
    assert checkout['with']['persist-credentials'] is False
    shell = '\n'.join(s.get('run', '') for s in steps)
    assert '--base "$BASE_SHA" --head "$HEAD_SHA"' in shell
    assert '--format sarif' in shell
    assert 'Enforce merge gate' in [s.get('name') for s in steps]
    example_text = (ROOT / 'examples/github-action/blastradius-pr-check.yml').read_text(encoding='utf-8')
    assert '<your-org>' not in example_text
    assert 'pull_request_target' not in example_text
    example = yaml.safe_load(example_text)
    assert example['permissions']['contents'] == 'read'
