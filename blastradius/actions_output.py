from __future__ import annotations

import json
from pathlib import Path

from blastradius.github_pr import MARKER
from blastradius.report import build_pr_comment
from blastradius.sarif import build_sarif


def step_outputs(diff, decision, exit_code):
    return {
        'decision': decision.decision.value,
        'security_score_before': diff.before.score,
        'security_score_after': diff.after.score,
        'critical_paths_added': len(diff.new_critical_paths),
        'sensitive_resources_added': len(diff.newly_reachable_sensitive),
        'exit_code': exit_code,
    }


def job_summary(diff, decision, exit_code):
    status = 'BLOCKED' if exit_code else 'REVIEW REQUIRED' if decision.decision.value == 'REVIEW REQUIRED' else 'PASSED'
    count = len(diff.new_critical_paths)
    detail = f'{count} critical attack path' + ('s' if count != 1 else '') + ' introduced' if count else 'No new modeled critical attack paths detected.'
    return f'## BlastRadius — {status}\n\n{detail}\n\nSecurity score: {diff.before.score} → {diff.after.score}\n'


def write_delivery(args, outputs, summary, report, payload, sarif):
    if args.report_dir:
        directory = Path(args.report_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for filename, content in (
            ('report.md', report), ('summary.md', summary),
            ('result.json', json.dumps(payload, indent=2)),
            ('results.sarif', json.dumps(sarif, indent=2)),
        ):
            (directory / filename).write_text(content, encoding='utf-8')
    if args.github_output:
        with Path(args.github_output).open('a', encoding='utf-8') as output:
            output.write(''.join(f'{key}={value}\n' for key, value in outputs.items()))
    if args.github_summary:
        with Path(args.github_summary).open('a', encoding='utf-8') as target:
            target.write(summary + '\n' + report + '\n')


def deliver_success(args, diff, decision, payload, before_dir, after_dir, exit_code):
    report = build_pr_comment(diff, decision, before_dir, after_dir)
    outputs = step_outputs(diff, decision, exit_code)
    payload.update(outputs)
    write_delivery(args, outputs, job_summary(diff, decision, exit_code), report,
                   payload, build_sarif(diff, decision))


def deliver_error(args):
    summary = '## BlastRadius — ERROR\n\nAnalysis did not complete. No merge safety conclusion is available; inspect the CLI logs.\n'
    outputs = {
        'decision': 'ERROR', 'security_score_before': '', 'security_score_after': '',
        'critical_paths_added': '', 'sensitive_resources_added': '', 'exit_code': 2,
    }
    report = MARKER + '\n' + summary
    sarif = {
        'version': '2.1.0',
        'runs': [{'tool': {'driver': {'name': 'BlastRadius'}}, 'results': [],
                  'invocations': [{'executionSuccessful': False}]}],
    }
    write_delivery(args, outputs, summary, report, {**outputs, 'passed': False}, sarif)
