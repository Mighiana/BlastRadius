import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AuthGate } from './AuthGate';
import { session } from '../test/fixtures';
import { SessionProvider } from '../session';

describe('AuthGate', () => {
  it.each([
    ['Google', 'Sign in with Google'],
    [null, 'Sign in with your identity provider'],
  ])('uses the provider name when available (%s)', async (providerName, expected) => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      ...session,
      auth: { ...session.auth, mode: 'oidc', provider_name: providerName },
    }))));
    render(
      <MemoryRouter>
        <SessionProvider><AuthGate>Workspace</AuthGate></SessionProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('link', { name: expected })).toBeVisible();
  });
});
