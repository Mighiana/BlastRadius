import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { reportSchema } from '../api';
import sshDemo from '../test/ssh-demo.json';
import { blockingDiagnosticGroups } from './diagnostics';
import { ReportView } from './ReportView';
import { ResultHero } from './ResultHero';

const risky = reportSchema.parse(sshDemo.risky);
const remediated = reportSchema.parse(sshDemo.remediated);

function renderHero(report: typeof risky) {
  return render(<ResultHero report={report} blockingGroups={blockingDiagnosticGroups(report.diagnostics)} />);
}

function pathLabels(path: HTMLElement) {
  return within(path).getAllByRole('listitem').map(item =>
    within(item).getByText(/.+/, { selector: 'strong' }).textContent?.trim(),
  );
}

describe('ResultHero', () => {
  it('shows the blocking SSH path, score, and changed CIDRs from the fixture', () => {
    renderHero(risky);
    const hero = screen.getByLabelText('Analysis decision');
    expect(within(hero).getByText('BLOCK CHANGE')).toBeVisible();
    expect(within(hero).getByRole('group', { name: 'Heuristic score 100 to 20, change -80' })).toBeVisible();
    expect(within(hero).getByText('Heuristic score · not a risk probability')).toBeVisible();

    const path = within(hero).getByRole('list', { name: 'Primary new path' });
    const nodes = within(path).getAllByRole('listitem');
    expect(pathLabels(path)).toEqual(['Internet', 'Web SG', 'Web Server', 'App Role', 'Customer Data', 'Sensitive Data']);
    expect(within(nodes[0]!).getByText(/^Entry$/i)).toBeVisible();
    expect(within(nodes.at(-1)!).getByText(/^Sensitive$/i)).toBeVisible();
    expect(within(hero).getByText('10.0.0.0/24', { exact: true })).toBeVisible();
    expect(within(hero).getByText('0.0.0.0/0', { exact: true })).toBeVisible();
  });

  it('renders the path supplied by the report instead of a fixed node sequence', () => {
    const fixturePath = risky.new_attack_paths[0]!;
    const shortenedPath = {
      ...fixturePath,
      id: 'shortened-fixture-path',
      nodes: fixturePath.nodes.slice(0, 3),
      labels: fixturePath.labels.slice(0, 3),
      edges: fixturePath.edges.slice(0, 2),
      reaches_sensitive: false,
    };
    const report = reportSchema.parse({
      ...risky,
      new_critical_paths: [],
      new_attack_paths: [shortenedPath],
    });
    renderHero(report);
    const path = screen.getByRole('list', { name: 'Primary new path' });
    expect(pathLabels(path)).toEqual(['Internet', 'Web SG', 'Web Server']);
    expect(within(path).queryByText('App Role')).not.toBeInTheDocument();
  });

  it('shows the safe result and removed path without rendering a new-path graph', () => {
    renderHero(remediated);
    const hero = screen.getByLabelText('Analysis decision');
    expect(within(hero).getByText('SAFE TO MERGE')).toBeVisible();
    expect(screen.queryByText('NO NEW PATHS')).not.toBeInTheDocument();
    expect(within(hero).getByText('No new modeled blocking findings detected.')).toBeVisible();
    expect(within(hero).getByText('No new modeled blocking path')).toBeVisible();
    expect(screen.queryByRole('list', { name: 'Primary new path' })).not.toBeInTheDocument();
    expect(within(hero).getByRole('list', { name: 'Removed path' })).toBeVisible();
    expect(within(hero).getByRole('group', { name: 'Heuristic score 20 to 100, change +80' })).toBeVisible();
  });

  it('shows only blocking coverage chips and marks incomplete review counts as lower bounds', () => {
    const review = reportSchema.parse({
      ...risky,
      decision: 'REVIEW REQUIRED',
      analysis_complete: false,
      new_critical_paths: [],
      new_attack_paths: [],
      newly_exposed: [],
      newly_reachable_sensitive: [],
      diagnostics: [
        { code: 'UNEXPANDED_MODULE', severity: 'warning', message: 'Module cannot be expanded', blocks_analysis: true },
        { code: 'UNEXPANDED_MODULE', severity: 'warning', message: 'Another module cannot be expanded', blocks_analysis: true },
        { code: 'INVALID_POLICY', severity: 'warning', message: 'Policy document is templated', blocks_analysis: true },
        { code: 'UNSUPPORTED_RESOURCE', severity: 'warning', message: 'Outside modeled coverage: aws_lambda_function', blocks_analysis: true },
        { code: 'UNSUPPORTED_RESOURCE', severity: 'warning', message: 'Outside modeled coverage: aws_db_instance', blocks_analysis: true },
        { code: 'model_limitations', severity: 'info', message: 'Synthetic model limitation note' },
        { code: 'UNSUPPORTED_RESOURCE', severity: 'warning', message: 'Outside modeled coverage (no reachability effect): aws_vpc', blocks_analysis: false },
      ],
    });
    render(<ReportView report={review} />);
    const hero = screen.getByLabelText('Analysis decision');
    expect(within(hero).getByText('REVIEW REQUIRED')).toBeVisible();
    expect(within(hero).getByText('Analysis coverage incomplete.')).toBeVisible();
    expect(within(hero).getByText(/Counts are lower bounds/)).toBeVisible();
    const metrics = within(hero).getByRole('list', { name: 'Change in the model' });
    expect((metrics.textContent ?? '').replace(/at least /g, '').replace(/\s/g, '')).toContain('≥0');

    const coverage = within(hero).getByRole('list', { name: 'Analysis coverage' });
    expect(within(coverage).getByText('2× Modules not expanded')).toBeVisible();
    expect(within(coverage).getByText('1× IAM policy not evaluable')).toBeVisible();
    expect(within(coverage).getByText('2× Resource types outside coverage')).toBeVisible();
    expect(within(coverage).queryByText(/aws_vpc|Synthetic model limitation note/)).not.toBeInTheDocument();
    expect(within(hero).getByText('Human review required')).toBeVisible();
    expect(screen.queryByText('SAFE TO MERGE')).not.toBeInTheDocument();
    expect(screen.getByText('Model limitations and notes (2)')).toBeVisible();
    expect(screen.getByText('Coverage diagnostics (5)')).toBeVisible();
  });

  it('keeps a zero-delta SAFE score label valid', () => {
    const report = reportSchema.parse({
      ...remediated,
      score: { before: 100, after: 100, delta: 0 },
    });
    renderHero(report);
    expect(screen.getByRole('group', { name: 'Heuristic score 100 to 100, change 0' })).toBeVisible();
  });

  it('shows the recommended fix and opens the supported patch for inspection', async () => {
    const originalScrollIntoView = Element.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      const user = userEvent.setup();
      render(<ReportView report={risky} />);
      const change = screen.getByLabelText('Responsible change');
      expect(within(change).getByText('Current')).toBeVisible();
      expect(within(change).getByText('Recommended')).toBeVisible();
      expect(within(change).getByText('cidr_blocks = ["0.0.0.0/0"]')).toBeVisible();
      expect(within(change).getByText('cidr_blocks = ["10.0.0.0/24"]')).toBeVisible();
      expect(within(change).getByText('Downloads never modify infrastructure.')).toBeVisible();

      await user.click(within(change).getByRole('button', { name: 'Inspect patch' }));
      expect(document.querySelector('details#remediation-patch')).toHaveAttribute('open');
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    } finally {
      Element.prototype.scrollIntoView = originalScrollIntoView;
    }
  });
});
