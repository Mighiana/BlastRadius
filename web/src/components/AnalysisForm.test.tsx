import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AnalysisForm } from './AnalysisForm';

const example = {
  scenario_id: 'public_ssh',
  title: 'Public SSH exposure',
  before_files: { 'main.tf': 'resource "aws_security_group" "web" {}' },
  after_files: { 'main.tf': 'resource "aws_security_group" "web" { ingress {} }' },
};

describe('AnalysisForm public example loader', () => {
  it('loads the public SSH fixture into both editors without submitting', async () => {
    const fetcher = vi.fn(async (url: string) => {
      expect(url).toBe('/api/demo/public_ssh/files');
      return new Response(JSON.stringify(example));
    });
    vi.stubGlobal('fetch', fetcher);
    const user = userEvent.setup();
    render(<AnalysisForm projectId="project" onSubmitted={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Load the example (public SSH change)' }));

    expect(await screen.findByLabelText('Baseline HCL')).toHaveValue(example.before_files['main.tf']);
    expect(screen.getByLabelText('Candidate HCL')).toHaveValue(example.after_files['main.tf']);
    expect(screen.getByLabelText('Baseline label')).toHaveValue('example-baseline');
    expect(screen.getByLabelText('Candidate label')).toHaveValue('example-public-ssh');
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('shows an API error and leaves editors empty when the example is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 })));
    const user = userEvent.setup();
    render(<AnalysisForm projectId="project" onSubmitted={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Load the example (public SSH change)' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('This item is unavailable'));
    expect(screen.queryByLabelText('Baseline HCL')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Candidate HCL')).not.toBeInTheDocument();
  });
});
