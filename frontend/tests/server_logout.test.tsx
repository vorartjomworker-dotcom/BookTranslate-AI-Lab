import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { AuthProvider, useAuth } from '../app/AuthProvider';
import { getAccessToken, setAccessToken } from '../app/lib/api';

const user = {
  id: 1,
  email: 'editor@example.com',
  role: 'editor',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

function Harness() {
  const { status, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <button type="button" onClick={() => void login('editor@example.com', 'correct-password')}>login</button>
      <button type="button" onClick={() => void logout()}>logout</button>
    </div>
  );
}

beforeEach(() => {
  setAccessToken(null);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAccessToken(null);
});

it('sends the in-memory bearer token to server logout before clearing local auth', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
      return json({ access_token: 'server-revoke-token', token_type: 'bearer', expires_in: 900, user });
    }
    if (url.endsWith('/api/v1/auth/logout') && method === 'POST') {
      const headers = new Headers(init?.headers);
      expect(headers.get('Authorization')).toBe('Bearer server-revoke-token');
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><Harness /></AuthProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'login' }));
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
  expect(getAccessToken()).toBe('server-revoke-token');

  fireEvent.click(screen.getByRole('button', { name: 'logout' }));
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  expect(getAccessToken()).toBeNull();

  expect(fetchMock.mock.calls.some(([input, init]) => (
    String(input).endsWith('/api/v1/auth/logout') && init?.method === 'POST'
  ))).toBe(true);
});

it('always clears local auth even when server revocation cannot be reached', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
      return json({ access_token: 'offline-revoke-token', token_type: 'bearer', expires_in: 900, user });
    }
    if (url.endsWith('/api/v1/auth/logout') && method === 'POST') {
      throw new TypeError('network unavailable');
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><Harness /></AuthProvider>);
  fireEvent.click(screen.getByRole('button', { name: 'login' }));
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('authenticated'));
  expect(getAccessToken()).toBe('offline-revoke-token');

  fireEvent.click(screen.getByRole('button', { name: 'logout' }));
  await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('unauthenticated'));
  expect(getAccessToken()).toBeNull();
});
