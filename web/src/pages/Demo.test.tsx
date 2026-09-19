import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import Demo from './Demo';
import { risky, safe } from '../test/fixtures';

describe('real API demo transitions', () => {
  it('requests SAFE, risky and remediated reports rather than deriving results in the browser', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url);
      const body = url.endsWith('/scenarios') ? { scenarios: [{ id: 'public_ssh', title: 'Public SSH exposure', root_cause: 'network', change: 'CIDR widens', stages: ['safe', 'risky', 'remediated'] }] } : url.includes('stage=risky') ? risky : safe;
      return new Response(JSON.stringify(body));
    }));
    const user = userEvent.setup();
    render(<Demo />);
    expect(await screen.findByText('SAFE TO MERGE')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Simulate risky change' }));
    expect(await screen.findByText('BLOCK CHANGE')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Remediate & re-analyze' }));
    expect(await screen.findByText('SAFE TO MERGE')).toBeVisible();
    expect(urls).toContain('/api/demo/public_ssh?stage=safe');
    expect(urls).toContain('/api/demo/public_ssh?stage=risky');
    expect(urls).toContain('/api/demo/public_ssh?stage=remediated');
  });
  it('shows a useful error instead of fake results if the engine API is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Network error')));
    render(<Demo />);
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
    expect(screen.queryByLabelText('Analysis decision')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Simulate risky change' })).toBeDisabled();
  });
});
