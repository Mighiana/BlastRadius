import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ReportView } from './ReportView';
import { risky, safe } from '../test/fixtures';
import { validateFiles, validatePlan } from './AnalysisForm';

describe('report evidence and graph', () => {
  it('never renders or exports an incomplete result claiming SAFE', () => {
    render(<ReportView report={{ ...safe, analysis_complete: false }} />);
    expect(screen.getByRole('alert')).toHaveTextContent('The analysis result is inconsistent');
    expect(screen.queryByText('SAFE TO MERGE')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'JSON' })).not.toBeInTheDocument();
  });
  it('explains a demo baseline without implying that a candidate change exists', () => {
    render(<ReportView report={{ ...safe, responsible_changes: [], demo: {
      scenario_id: 'public_ssh', stage: 'safe', remediation_kind: 'supported_patch', note: '',
    } }} />);
    expect(screen.getByLabelText('Responsible change')).toHaveTextContent('Baseline configuration — no candidate change yet.');
    expect(screen.getByText(/No HCL source changes to display/)).toBeVisible();
  });
  it('shows the backend decision, heuristic labels, all nodes and disclosed evidence', async () => {
    const user = userEvent.setup();
    render(<ReportView report={risky} />);
    expect(screen.getByLabelText('Analysis decision')).toHaveTextContent('BLOCK CHANGE');
    expect(screen.getByText(/Heuristic · not a risk probability/)).toBeVisible();
    expect(screen.getByText('-65 points')).toBeVisible();
    expect(screen.getByLabelText('Responsible change')).toHaveTextContent('Bucket ACL changed.');
    const path = screen.getByRole('list', { name: 'Attack path' });
    expect(within(path).getByText('Internet')).toBeVisible();
    expect(within(path).getByText('Customer Data')).toBeVisible();
    const summary = screen.getAllByText('public access', { exact: true })[0]?.closest('summary');
    expect(summary).not.toBeNull();
    await user.click(summary!);
    expect(summary?.parentElement).toHaveAttribute('open');
    expect(screen.getAllByText('acl = "public-read"')[0]).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Before' }));
    expect(screen.getByText('No modeled attack path from the internet')).toBeVisible();
    expect(screen.queryByRole('list', { name: 'Attack path' })).not.toBeInTheDocument();
  });
  it('escapes malicious resource names and never interprets report HTML', () => {
    const value = '<img src=x onerror=alert(1)>';
    const report = { ...risky, headline: value, responsible_change: '<script>alert(1)</script>' };
    const { container } = render(<ReportView report={report} />);
    expect(screen.getByRole('heading', { name: value })).toBeVisible();
    expect(container.querySelector('img,script')).toBeNull();
  });
  it('does not infer score 100 from SAFE or claim no existing exposure', () => {
    render(<ReportView report={{ ...safe, score: { before: 85, after: 85, delta: 0 } }} />);
    expect(screen.getByText('SAFE TO MERGE')).toBeVisible();
    expect(screen.getAllByText('85')).toHaveLength(2);
    expect(screen.getByText(/does not prove safety/)).toBeVisible();
  });
  it('disables persisted SARIF when stripped by the server entitlement gate', () => {
    render(<ReportView jobId="saved" report={{ ...risky, reports: { markdown: risky.reports.markdown } }} />);
    expect(screen.getByRole('button', { name: 'SARIF' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'JSON' })).toBeEnabled();
    expect(screen.getByText(/Saved SARIF exports require/)).toBeInTheDocument();
  });
  it('enables real SARIF for an entitled persisted report and public demo', () => {
    const { rerender } = render(<ReportView report={risky} />);
    expect(screen.getByRole('button', { name: 'SARIF' })).toBeEnabled();
    rerender(<ReportView report={risky} jobId="saved" />);
    expect(screen.getByRole('button', { name: 'SARIF' })).toBeEnabled();
  });
  it('inspects actual node evidence and bounds zoom with a reset', async () => {
    Element.prototype.scrollTo = vi.fn();
    Element.prototype.scrollBy = vi.fn();
    render(<ReportView report={risky} />);
    await userEvent.click(screen.getByRole('button', { name: 'Inspect node Customer Data' }));
    const inspector = screen.getByRole('region', { name: 'Selected node evidence' });
    expect(within(inspector).getByText('acl = "public-read"')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inspect node Customer Data' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByRole('list', { name: 'Attack path' })).toHaveStyle({ width: '120%' });
    await userEvent.click(screen.getByRole('button', { name: 'Pan graph right' }));
    expect(Element.prototype.scrollBy).toHaveBeenCalledWith({ left: 200 });
    await userEvent.click(screen.getByRole('button', { name: 'Fit / reset' }));
    expect(screen.getByRole('list', { name: 'Attack path' })).toHaveStyle({ width: '100%' });
    expect(screen.getByRole('button', { name: 'Pan graph right' })).toBeDisabled();
  });
});
describe('upload guardrails', () => {
  it.each(['../main.tf', 'folder/main.tf', '.hidden.tf', 'evil..tf', 'plan.json'])('rejects path or unsupported filename %s', name => {
    expect(() => validateFiles({ [name]: 'content' })).toThrow('simple ASCII');
  });
  it('rejects empty maps, oversized file counts and binary contents', () => {
    expect(() => validateFiles({})).toThrow('at least one');
    expect(() => validateFiles(Object.fromEntries(Array.from({ length: 31 }, (_, i) => [`file${i}.tf`, ''])))).toThrow('30');
    expect(() => validateFiles({ 'main.tf': '\0' })).toThrow('NUL');
  });
  it('accepts flat Terraform text as data', () => {
    expect(() => validateFiles({ 'main.tf': 'resource "aws_s3_bucket" "data" {}' })).not.toThrow();
  });
  it.each(['not-json', 'null', '[]', '{"wrong":true}', '{"planned_values":null}', '{"resource_changes":[{"invalid":"shape"}]}'])('rejects invalid plan %s', value => {
    expect(() => validatePlan(value)).toThrow();
  });
  it('accepts Terraform plan JSON without running it', () => {
    expect(validatePlan('{"resource_changes":[]}')).toEqual({ resource_changes: [] });
  });
});
