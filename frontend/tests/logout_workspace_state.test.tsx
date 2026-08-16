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

const chapter = {
  id: 11,
  book_id: 1,
  chapter_number: 1,
  title: 'Intro',
  content: null,
  status: 'segmented',
};

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

const editorUser = {
  id: 1,
  email: 'editor@example.com',
  role: 'editor',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
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
  if (url.endsWith('/api/v1/books/1/quality-summary')) {
    return json({
      book_id: 1,
      total_segments: 1,
      translated_segments: 1,
      checked_segments: 1,
      passed: 1,
      needs_review: 0,
      failed: 0,
      stale_reports: 0,
      average_score: 86,
    });
  }
  if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [sourceSegment] });
  if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
  if (url.endsWith('/api/v1/segments/21/quality-report') && method === 'GET') {
    return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
  }
  return null;
}

async function openEditor() {
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));
  await screen.findByDisplayValue('Old translation');
}

it('clears all workspace-local state on explicit logout before another login', async () => {
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
  await signIn();
  await openEditor();

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Sensitive unsaved draft' } });
  expect(screen.getByDisplayValue('Sensitive unsaved draft')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: /^logout$/i }));
  await screen.findByRole('heading', { name: 'Sign in' });

  await signIn();
  await screen.findByText('Distributed Systems');

  expect(screen.queryByDisplayValue('Sensitive unsaved draft')).toBeNull();
  expect(screen.queryByDisplayValue('Old translation')).toBeNull();
  expect(screen.queryByText('Intro')).toBeNull();
  expect(screen.queryByText('Source text')).toBeNull();
});

it('preserves an unsaved draft across session-expiry reauthentication', async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
      return json({ access_token: 'test-token', token_type: 'bearer', expires_in: 900, user: editorUser });
    }
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') {
      return json({ code: 'unauthorized', message: 'Your session has expired. Please log in again.', details: {}, request_id: 'req-expired' }, 401);
    }
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await signIn();
  await openEditor();

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Unsaved draft text' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/api/v1/segments/21/translation'),
    expect.objectContaining({ method: 'PATCH' }),
  ));
  await screen.findByRole('alertdialog', { name: 'Session expired' });
  expect(screen.queryByDisplayValue('Unsaved draft text')).toBeNull();
  expect(screen.queryByText('Source text')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: /log in again/i }));
  await screen.findByRole('heading', { name: 'Sign in' });
  await signIn();

  await screen.findByDisplayValue('Unsaved draft text');
  expect(screen.getByDisplayValue('Unsaved draft text')).toBeTruthy();
  // Same user.id reauthenticated: workspace selection must also survive, not just the draft.
  expect(screen.getAllByText('Distributed Systems').length).toBeGreaterThan(0);
  expect(screen.getByText('Intro')).toBeTruthy();
});

it('remounts and clears the previous user workspace when a different user reauthenticates after session expiry', async () => {
  const otherUser = {
    id: 2,
    email: 'other-editor@example.com',
    role: 'editor' as const,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  };
  let activeUserId = editorUser.id;

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/auth/login') && method === 'POST') {
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      if (body.email === otherUser.email) {
        activeUserId = otherUser.id;
        return json({ access_token: 'test-token-b', token_type: 'bearer', expires_in: 900, user: otherUser });
      }
      activeUserId = editorUser.id;
      return json({ access_token: 'test-token-a', token_type: 'bearer', expires_in: 900, user: editorUser });
    }
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') {
      return json({ code: 'unauthorized', message: 'Your session has expired. Please log in again.', details: {}, request_id: 'req-expired' }, 401);
    }
    if (activeUserId === otherUser.id) {
      if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [] });
      if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
      return null;
    }
    const workspaceResponse = workspaceRoutes(url, method);
    if (workspaceResponse) return workspaceResponse;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<AuthProvider><HomePage /></AuthProvider>);
  await signIn();
  await openEditor();

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'User A secret draft' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/api/v1/segments/21/translation'),
    expect.objectContaining({ method: 'PATCH' }),
  ));
  await screen.findByRole('alertdialog', { name: 'Session expired' });
  expect(screen.queryByDisplayValue('User A secret draft')).toBeNull();
  expect(screen.queryByText('Source text')).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: /log in again/i }));
  await screen.findByRole('heading', { name: 'Sign in' });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: otherUser.email } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'other-correct-password' } });
  fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

  await waitFor(() => expect(screen.getByText(otherUser.email)).toBeTruthy());

  // Different user.id: user A's draft, selection, and derived state must never be visible to B.
  expect(screen.queryByDisplayValue('User A secret draft')).toBeNull();
  expect(screen.queryByText('Distributed Systems')).toBeNull();
  expect(screen.queryByText('Intro')).toBeNull();
  expect(screen.queryByText('Source text')).toBeNull();
});
