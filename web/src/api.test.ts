import { describe, expect, it, vi } from 'vitest';
import { ApiError, mutate, reportSchema, request, safeBillingUrl, setCsrf } from './api';
import { risky } from './test/fixtures';

describe('API security and contract', () => {
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
  it.each(['javascript:alert(1)', 'https://checkout.stripe.com.evil.test/x', 'https://evil.test', 'https://user:secret@billing.stripe.com/x', 'http://checkout.stripe.com', 'https://checkout.stripe.com:8443'])('rejects unsafe billing redirect %s', value => {
    expect(() => safeBillingUrl(value)).toThrow();
  });
  it('accepts only exact HTTPS Stripe checkout and portal hosts', () => {
    expect(safeBillingUrl('https://checkout.stripe.com/c/pay/test')).toBe('https://checkout.stripe.com/c/pay/test');
    expect(safeBillingUrl('https://billing.stripe.com/p/session/test')).toBe('https://billing.stripe.com/p/session/test');
  });
});
