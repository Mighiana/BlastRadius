import { describe, expect, it, vi } from 'vitest';
import { ApiError, mutate, projectSchema, reportSchema, request, safeGitHubUrl, setCsrf } from './api';
import { project, risky } from './test/fixtures';

describe('API security and contract', () => {
  it('accepts new projects before an update timestamp exists', () => {
    expect(projectSchema.parse({ ...project, updated_at: null }).updated_at).toBeNull();
  });
  it.each([
    ['invalid_origin', 'BR_PUBLIC_URL', 0],
    ['insufficient_role', 'workspace role', 0],
    ['csrf_required', 'session changed', 1],
  ])('distinguishes %s without replaying workspace creation', async (code, message, refreshes) => {
    const listener = vi.fn();
    window.addEventListener('br:session-refresh', listener);
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: code }), { status: 403 }));
    vi.stubGlobal('fetch', fetcher);
    try {
      await expect(mutate('/api/organizations', 'POST', { name: 'Example' })).rejects.toThrow(message);
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(listener).toHaveBeenCalledTimes(refreshes);
    } finally { window.removeEventListener('br:session-refresh', listener); }
  });
  it('uses same-origin cookies and memory-only CSRF for every mutation', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    setCsrf('rotated-token');
    await mutate('/api/analyses/test', 'DELETE');
    const options = fetcher.mock.calls[0]?.[1] as RequestInit;
    expect(options.credentials).toBe('same-origin');
    expect(new Headers(options.headers).get('X-CSRF-Token')).toBe('rotated-token');
  });
  it('does not leak server errors, untrusted HTML or host paths', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '/private/secret Traceback <script>alert(1)</script>' }), { status: 500, headers: { 'X-Request-ID': 'request-123' } })));
    await expect(request('/api/demo/public_ssh', reportSchema)).rejects.toMatchObject({
      message: 'The service could not complete this request.', requestId: 'request-123',
    });
  });
  it('rejects malformed or unsupported reports instead of presenting success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...risky, schema_version: 2 }))));
    await expect(request('/api/demo/public_ssh', reportSchema)).rejects.toThrow('incompatible');
  });
  it('requests session refresh on expiry without replaying a mutation', async () => {
    const event = vi.fn();
    window.addEventListener('br:session-refresh', event);
    const fetcher = vi.fn().mockResolvedValue(new Response('{"detail":"authentication_required"}', { status: 401 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(mutate('/api/projects', 'POST', {})).rejects.toBeInstanceOf(ApiError);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(event).toHaveBeenCalledTimes(1);
    window.removeEventListener('br:session-refresh', event);
  });
  it.each(['javascript:alert(1)', 'https://github.com.evil.test/x', 'https://evil.test', 'https://user:secret@github.com/x', 'http://github.com', 'https://github.com:8443'])('rejects unsafe GitHub link %s', value => {
    expect(() => safeGitHubUrl(value)).toThrow();
  });
  it('accepts only exact HTTPS GitHub links', () => {
    expect(safeGitHubUrl('https://github.com/apps/blastradius/installations/new')).toBe('https://github.com/apps/blastradius/installations/new');
  });
});
