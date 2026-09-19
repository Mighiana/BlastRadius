import { StrictMode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { SessionProvider, useSession } from './session';
import { session } from './test/fixtures';

function Status() {
  const { loading, session: current } = useSession();
  return <p>{loading ? 'Loading' : current?.csrf_token}</p>;
}
it('coalesces strict-mode session initialization to avoid racing CSRF cookies', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(session)));
  vi.stubGlobal('fetch', fetcher);
  render(<StrictMode><SessionProvider><Status /></SessionProvider></StrictMode>);
  await waitFor(() => expect(screen.getByText('test-csrf')).toBeVisible());
  expect(fetcher).toHaveBeenCalledTimes(1);
});
