import type { ApiErrorEnvelope } from './api-types';

export type RequestOptions = RequestInit & { timeoutMs?: number; responseType?: 'json' | 'blob' };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string | null;

  constructor(status: number, envelope: ApiErrorEnvelope | null) {
    super(safeMessage(status, envelope?.code));
    this.name = 'ApiError';
    this.status = status;
    this.code = envelope?.code || 'http_error';
    this.details = envelope?.details ?? {};
    this.requestId = envelope?.request_id ?? null;
  }
}

export class ApiTimeoutError extends Error {
  constructor() {
    super('The request timed out. Please try again.');
    this.name = 'ApiTimeoutError';
  }
}

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const DEFAULT_TIMEOUT_MS = 15000;

// In-memory only: the access token is never written to localStorage/sessionStorage so it
// cannot be exfiltrated via XSS reading persistent storage. It is cleared on page reload
// and explicit logout by design; there is no refresh-token cookie or silent refresh flow.
let accessToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function safeMessage(status: number, code?: string): string {
  if (status === 401) return 'Your session has expired. Please log in again.';
  if (status === 403) return 'You do not have permission to perform this action.';
  if (status === 404) return 'The requested resource was not found.';
  if (status === 409) return 'This action conflicts with the current resource state.';
  if (status === 413) return 'The uploaded file is too large.';
  if (status === 415) return 'This file type is not supported.';
  if (status === 422) return 'Some request fields are invalid.';
  if (status >= 500) return 'The service is temporarily unavailable.';
  if (code === 'validation_error') return 'Some request fields are invalid.';
  return 'The request could not be completed.';
}

async function parseEnvelope(response: Response): Promise<ApiErrorEnvelope | null> {
  try {
    const body: unknown = await response.json();
    if (!body || typeof body !== 'object') return null;
    const candidate = body as Record<string, unknown>;
    return {
      code: typeof candidate.code === 'string' ? candidate.code : undefined,
      message: typeof candidate.message === 'string' ? candidate.message : undefined,
      details: candidate.details,
      request_id: typeof candidate.request_id === 'string' ? candidate.request_id : undefined,
    };
  } catch {
    return null;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const signal = options.signal;
  const abortFromCaller = () => controller.abort();
  signal?.addEventListener('abort', abortFromCaller, { once: true });
  try {
    const headers = new Headers(options.headers);
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const token = accessToken;
    if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: 'include', signal: controller.signal });
    if (!response.ok) {
      if (response.status === 401 && token && unauthorizedHandler) unauthorizedHandler();
      throw new ApiError(response.status, await parseEnvelope(response));
    }
    if (response.status === 204) return undefined as T;
    if (options.responseType === 'blob') return (await response.blob()) as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (error instanceof DOMException && error.name === 'AbortError') throw new ApiTimeoutError();
    throw new Error('Unable to reach the translation service.');
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abortFromCaller);
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'POST', body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>(path, { ...options, method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  upload: <T>(path: string, body: FormData, options?: RequestOptions) => request<T>(path, { ...options, method: 'POST', body }),
};
