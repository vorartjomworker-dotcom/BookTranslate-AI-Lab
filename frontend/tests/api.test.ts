import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from '../app/lib/api';

afterEach(() => vi.restoreAllMocks());

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
});
