import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { AuthProvider } from '../app/AuthProvider';
import HomePage from '../app/page';
import type { Book, Segment } from '../app/lib/types';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const book: Book = {
  id: 1,
  title: 'Distributed Systems',
  author: 'A. Writer',
  description: null,
  file_path: 'book.epub',
  file_type: 'epub',
  language: 'en',
  status: 'uploaded',
};

const chapter = { id: 11, book_id: 1, chapter_number: 1, title: 'Intro', content: null, status: 'segmented' };
const sourceSegment: Segment = {
  id: 21,
  chapter_id: 11,
  segment_number: 1,
  original_text: 'Source text',
  translated_text: 'Old translation',
  confidence: 0.7,
  model_used: 'gpt-4o',
  status: 'translated',
  qa_score: 86,
  qa_status: 'passed',
  qa_comment: null,
  translation_profile: 'general',
  tokens_used: 14,
  latency_ms: 30,
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
}

async function signIn() {
  await screen.findByRole('heading', { name: 'Sign in' });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'editor@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-password' } });
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }));
}

function workspaceRoutes(url: string, method: string): Response | null {
  if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
  if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
  if (url.endsWith('/api/v1/books/1')) return json(book);
  if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
  if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 1, translated_segments: 1, checked_segments: 1, passed: 1, needs_review: 0, failed: 0, stale_reports: 0, average_score: 86 });
  if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [sourceSegment] });
  if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
  if (url.endsWith('/api/v1/segments/21/quality-report') && method === 'GET') return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
  return null;
}

const editorUser = { id: 1, email: 'editor@example.com', role: 'editor', is_active: true, created_at: '2026-01-01T00:00:00Z' };
const viewerUser = { id: 2, email: 'viewer@example.com', role: 'viewer', is_active: true, created_at: '2026-01-01T00:00:00Z' };

it('shows the login screen when there is no valid session', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') return json({ code: 'unauthorized', message: 'Missing credentials.', details: {}, request_id: 'req-1' }, 401);
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);

  await screen.findByRole('heading', { name: 'Sign in' });
  expect(screen.queryByText('Distributed Systems')).toBeNull();
});

it('logs in successfully and reaches the workspace', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
      return json({ access_token: 'test-token', token_type: 'bearer', expires_in: 900, user: editorUser });
    }
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await screen.findByRole('heading', { name: 'Sign in' });

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'editor@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct-password' } });
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

  await screen.findByText('Distributed Systems');
  expect(screen.getByText('editor@example.com')).toBeTruthy();
});

it('shows a login error and keeps the user on the login screen', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') return json({ code: 'unauthorized', message: 'Invalid email or password.', details: {}, request_id: 'req-2' }, 401);
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await screen.findByRole('heading', { name: 'Sign in' });

  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'editor@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } });
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

  await screen.findByText('Sign-in failed');
  // A first, never-authenticated login failure must read as an invalid-credentials
  // rejection, never as an expired session (those are different auth states).
  expect(screen.getByText('Invalid email or password.')).toBeTruthy();
  expect(screen.queryByText(/session has expired/i)).toBeNull();
  expect(screen.queryByText('Distributed Systems')).toBeNull();
});

it('logs out and returns to the login screen', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') return json({ access_token: 'test-token', token_type: 'bearer', expires_in: 900, user: editorUser });
    if (url.endsWith('/api/v1/auth/logout') && method === 'POST') return new Response(null, { status: 204 });
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await signIn();
  await screen.findByText('Distributed Systems');

  fireEvent.click(screen.getByRole('button', { name: /logout/i }));
  await screen.findByRole('heading', { name: 'Sign in' });
});

it('hides mutation controls for a viewer role', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') return json({ access_token: 'test-token', token_type: 'bearer', expires_in: 900, user: viewerUser });
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await signIn();
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));

  await screen.findByDisplayValue('Old translation');
  expect(screen.queryByRole('button', { name: /save translation/i })).toBeNull();
  expect(screen.getByLabelText('Translation')).toHaveProperty('readOnly', true);
});

it('blocks workspace visibility and interaction when a save fails with an expired session', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') return json({ access_token: 'test-token', token_type: 'bearer', expires_in: 900, user: editorUser });
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') return json({ code: 'unauthorized', message: 'Your session has expired. Please log in again.', details: {}, request_id: 'req-expired' }, 401);
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await signIn();
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));
  await screen.findByDisplayValue('Old translation');

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Unsaved draft text' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/segments/21/translation'), expect.objectContaining({ method: 'PATCH' })));
  const dialog = await screen.findByRole('alertdialog', { name: 'Session expired' });
  expect(dialog.getAttribute('aria-modal')).toBe('true');
  expect(screen.getByRole('button', { name: /log in again/i })).toBeTruthy();
  expect(screen.queryByLabelText('Translation')).toBeNull();
  expect(screen.queryByText('Source text')).toBeNull();
  expect(screen.queryByRole('button', { name: /dismiss/i })).toBeNull();

  const saveRequests = () => fetchMock.mock.calls.filter(([input, init]) => (
    String(input).endsWith('/api/v1/segments/21/translation') && init?.method === 'PATCH'
  ));
  expect(saveRequests()).toHaveLength(1);
  fireEvent.keyDown(window, { key: 's', ctrlKey: true });
  expect(saveRequests()).toHaveLength(1);
});
