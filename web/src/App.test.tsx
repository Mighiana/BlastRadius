import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { SessionProvider } from './session';
import { safe, session } from './test/fixtures';

describe('mobile navigation', () => {
  it('locks body scrolling while the navigation menu is open', async () => {
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/me') return new Response(JSON.stringify(session));
      if (url === '/api/demo/scenarios') {
        return new Response(JSON.stringify({ scenarios: [] }));
      }
      return new Response(JSON.stringify(safe));
    }));
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/demo']}>
        <SessionProvider><App /></SessionProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole('button', { name: 'Open navigation' }));
    expect(document.body.classList.contains('nav-open')).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Close navigation' }));
    expect(document.body.classList.contains('nav-open')).toBe(false);
  });
});
