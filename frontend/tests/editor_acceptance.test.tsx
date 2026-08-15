import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

import HomePage from '../app/page';
import type { Book, QualityReport, Segment } from '../app/lib/types';

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

async function openEditor() {
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));
  await screen.findByDisplayValue('Old translation');
}

function baseFetchRoutes(url: string, method: string, segment: Segment = sourceSegment): Response | null {
  if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
  if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
  if (url.endsWith('/api/v1/books/1')) return json(book);
  if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
  if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 1, translated_segments: 1, checked_segments: 1, passed: 1, needs_review: 0, failed: 0, stale_reports: 0, average_score: 86 });
  if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [segment] });
  if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
  if (url.endsWith('/api/v1/segments/21/quality-report') && method === 'GET') return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
  return null;
}

it('preserves newer local edits when an earlier save response returns and prevents duplicate saves', async () => {
  let resolveSave!: (response: Response) => void;
  const pendingSave = new Promise<Response>((resolve) => { resolveSave = resolve; });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    const base = baseFetchRoutes(url, method);
    if (base) return base;
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') return pendingSave;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<HomePage />);
  await openEditor();

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Submitted translation' } });
  const saveButton = screen.getByRole('button', { name: /save translation/i }) as HTMLButtonElement;
  fireEvent.click(saveButton);
  fireEvent.click(saveButton);

  await waitFor(() => {
    const patchCalls = fetchMock.mock.calls.filter(([input, init]) => String(input).endsWith('/api/v1/segments/21/translation') && (init?.method || 'GET') === 'PATCH');
    expect(patchCalls).toHaveLength(1);
  });
  expect(saveButton.disabled).toBe(true);

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Newer local draft' } });
  resolveSave(json({ ...sourceSegment, translated_text: 'Submitted translation', qa_status: 'stale', qa_score: 0, qa_comment: 'Manual translation edit invalidated the previous QA result.' }));

  await waitFor(() => expect(screen.getByDisplayValue('Newer local draft')).toBeTruthy());
  expect(screen.getByText('Unsaved changes')).toBeTruthy();
  expect(screen.getByText('Translation saved. Newer edits remain unsaved.')).toBeTruthy();
  await waitFor(() => expect((screen.getByRole('button', { name: /save translation/i }) as HTMLButtonElement).disabled).toBe(false));
});

it('aborts an obsolete save and clears the discarded draft when navigating away', async () => {
  let patchStarted = false;
  let patchAborted = false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    const base = baseFetchRoutes(url, method);
    if (base) return base;
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') {
      const signal = init?.signal;
      if (!signal) throw new Error('PATCH must receive an AbortSignal');
      patchStarted = true;
      return await new Promise<Response>((_resolve, reject) => {
        signal.addEventListener('abort', () => {
          patchAborted = true;
          reject(new DOMException('Aborted', 'AbortError'));
        }, { once: true });
      });
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<HomePage />);
  await openEditor();

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Draft to discard' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));
  await waitFor(() => expect(patchStarted).toBe(true));

  fireEvent.click(screen.getByRole('button', { name: /^quality$/i }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Quality', level: 1 })).toBeTruthy());
  expect(confirmSpy).toHaveBeenCalledTimes(1);
  expect(patchAborted).toBe(true);

  confirmSpy.mockClear();
  fireEvent.click(screen.getByRole('button', { name: /^books$/i }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Books', level: 1 })).toBeTruthy());
  expect(confirmSpy).not.toHaveBeenCalled();
  expect(screen.getByDisplayValue('Old translation')).toBeTruthy();
  expect(screen.queryByText('Unsaved changes')).toBeNull();
});

it('refreshes selected segment and list QA state after rerunning quality without a page reload', async () => {
  const staleSegment = { ...sourceSegment, qa_score: 0, qa_status: 'stale', qa_comment: 'Manual translation edit invalidated the previous QA result.' };
  const report: QualityReport = {
    id: 90,
    segment_id: 21,
    translation_job_id: null,
    evaluator_version: '1.0.0',
    mode: 'deterministic',
    deterministic_score: 97,
    ai_score: null,
    overall_score: 97,
    evaluator_error_code: null,
    score: 97,
    status: 'passed',
    summary: 'No quality issues detected.',
    provider: 'openai',
    model: 'gpt-4o',
    source_language: 'en',
    target_language: 'ru',
    ai_evaluated: false,
    issues: [],
    created_at: null,
    updated_at: null,
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    const base = baseFetchRoutes(url, method, staleSegment);
    if (base) return base;
    if (url.endsWith('/api/v1/segments/21/quality-check') && method === 'POST') return json(report);
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<HomePage />);
  await openEditor();
  fireEvent.click(screen.getByRole('button', { name: /^quality$/i }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Quality', level: 1 })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: /run quality check/i }));

  await waitFor(() => expect(screen.getByText('No quality issues detected.')).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: /^books$/i }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Books', level: 1 })).toBeTruthy());
  expect(screen.getByText('passed')).toBeTruthy();
  expect(screen.queryByText('stale')).toBeNull();
});
