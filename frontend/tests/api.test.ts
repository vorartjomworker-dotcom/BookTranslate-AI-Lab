import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, getAccessToken, request, setAccessToken, setUnauthorizedHandler } from '../app/lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
  setUnauthorizedHandler(null);
});

describe('typed API client', () => {
  it('returns JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 })));
    await expect(request<{ items: unknown[] }>('/api/v1/books')).resolves.toEqual({ items: [] });
  });

  it('normalizes backend errors and preserves request_id without leaking message text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'internal_server_error', message: 'Traceback /srv/app/secret.py', details: {}, request_id: 'req-123' }), { status: 500 })));
    const error: ApiError = await request<never>('/api/v1/books').catch((value) => value as ApiError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('The service is temporarily unavailable.');
    expect(error.message).not.toContain('Traceback');
    expect(error.requestId).toBe('req-123');
  });

  it('supports multipart upload without forcing JSON content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    const body = new FormData();
    body.append('file', new File(['book'], 'book.epub'));
    await request('/api/v1/books/upload', { method: 'POST', body });
    expect(fetchMock.mock.calls[0][1].headers.get('Content-Type')).toBeNull();
  });

  it('always omits browser credentials for bearer-only authentication', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await request('/api/v1/books', { credentials: 'include' });

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1].credentials).toBe('omit');
  });

  it('propagates caller cancellation without converting it into a timeout', async () => {
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))));
    const pending = request('/api/v1/translation-jobs/1', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('shows a neutral invalid-credentials message for a 401 with no bearer token and does not fire the unauthorized handler', async () => {
    const unauthorizedHandler = vi.fn();
    setUnauthorizedHandler(unauthorizedHandler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'unauthorized', message: 'Invalid email or password.', details: {}, request_id: 'req-login' }), { status: 401 })));

    const error: ApiError = await request<never>('/api/v1/auth/login', { method: 'POST' }).catch((value) => value as ApiError);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('Invalid email or password.');
    expect(error.message).not.toMatch(/session/i);
    expect(unauthorizedHandler).not.toHaveBeenCalled();
  });

  it('never surfaces the raw backend message for an unauthenticated 401, even if it differs from the safe default', async () => {
    const unauthorizedHandler = vi.fn();
    setUnauthorizedHandler(unauthorizedHandler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'unauthorized', message: 'This account is inactive.', details: {}, request_id: 'req-inactive' }), { status: 401 })));

    const error: ApiError = await request<never>('/api/v1/auth/login', { method: 'POST' }).catch((value) => value as ApiError);

    expect(error.message).toBe('Invalid email or password.');
    expect(unauthorizedHandler).not.toHaveBeenCalled();
  });

  it('shows a session-expired message and fires the unauthorized handler for a 401 on an authenticated request', async () => {
    const unauthorizedHandler = vi.fn();
    setAccessToken('a-valid-looking-token');
    setUnauthorizedHandler(unauthorizedHandler);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'unauthorized', message: 'Invalid or expired token.', details: {}, request_id: 'req-expired' }), { status: 401 })));

    const error: ApiError = await request<never>('/api/v1/books').catch((value) => value as ApiError);

    expect(error.message).toBe('Your session has expired. Please log in again.');
    expect(unauthorizedHandler).toHaveBeenCalledOnce();
  });

  it('does not let a delayed 401 from a stale bearer request tear down a newer session', async () => {
    const unauthorizedHandler = vi.fn();
    let resolveFetch: (response: Response) => void = () => undefined;
    const delayedResponse = new Promise<Response>((resolve) => {
      resolveFetch = resolve;
    });

    setAccessToken('old-session-token');
    setUnauthorizedHandler(unauthorizedHandler);
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(delayedResponse));

    const pending = request<never>('/api/v1/books').catch((value) => value as ApiError);
    setAccessToken('new-session-token');
    resolveFetch(new Response(JSON.stringify({ code: 'unauthorized', message: 'Invalid or expired token.', details: {}, request_id: 'req-stale' }), { status: 401 }));

    const error = await pending;
    expect(error.message).toBe('Your session has expired. Please log in again.');
    expect(unauthorizedHandler).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe('new-session-token');
  });
});
