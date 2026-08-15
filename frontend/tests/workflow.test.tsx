import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import HomePage from '../app/page';
import { BooksView, BenchmarksView, QualityView } from '../app/components/views';
import { bookRowLabel, failedJobMessage, qualityIssueCount } from '../app/lib/presenters';
import { benchmarkPayload, canRetryJob, pollUntilTerminal, validateUpload } from '../app/lib/workflow';
import type { Book, QualityReport, TranslationJob } from '../app/lib/types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function createDeferredResponse() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

const book: Book = { id: 1, title: 'Distributed Systems', author: 'A. Writer', description: null, file_path: 'book.epub', file_type: 'epub', language: 'en', status: 'uploaded' };
const failedJob: TranslationJob = { id: 2, segment_id: 1, provider: 'openai', model: 'gpt-4o', status: 'failed', attempt: 3, max_attempts: 3, retry_of_id: null, error_code: 'provider_unavailable_error', error_message: 'hidden', created_at: null, queued_at: null, started_at: null, completed_at: null, failed_at: null, request_id: 'req-1' };

it('renders a stable book list label', () => expect(bookRowLabel(book)).toBe('Distributed Systems - A. Writer - EN'));
it('validates only EPUB/DOCX extension and size', () => { expect(validateUpload({ name: 'book.exe', size: 10 })).toContain('EPUB'); expect(validateUpload({ name: 'book.pdf', size: 10 })).toContain('EPUB'); expect(validateUpload({ name: 'book.epub', size: 26 * 1024 * 1024 })).toContain('25 MB'); expect(validateUpload({ name: 'book.epub', size: 10 })).toBeNull(); });
it('shows retry only for failed jobs', () => { expect(canRetryJob('failed')).toBe(true); expect(canRetryJob('running')).toBe(false); expect(failedJobMessage(failedJob)).toContain('failure'); });
it('keeps benchmark execution in dry-run mode', () => expect(benchmarkPayload('openai', 'gpt-4o', 5)).toMatchObject({ dry_run: true, confirm_live_provider: false, max_cases: 5 }));
it('exposes QA issue count', () => { const report = { issues: [{ code: 'missing', severity: 'error', message: 'Missing', field: null, expected: null, actual: null, score_impact: 5 }] } as QualityReport; expect(qualityIssueCount(report)).toBe(1); });
it('renders a book row in the Books workflow', () => { render(<BooksView books={[book]} selectedBook={null} chapters={[]} selectedChapter={null} segments={[]} selectedSegment={null} qualitySummary={null} detailLoading={false} uploadFile={null} busy={false} onBook={vi.fn()} onChapter={vi.fn()} onSegment={vi.fn()} onFile={vi.fn()} onUpload={vi.fn()} />); expect(screen.getByText('Distributed Systems')).toBeTruthy(); });
it('exposes only EPUB/DOCX in the Books upload UI', () => { render(<BooksView books={[]} selectedBook={null} chapters={[]} selectedChapter={null} segments={[]} selectedSegment={null} qualitySummary={null} detailLoading={false} uploadFile={null} busy={false} onBook={vi.fn()} onChapter={vi.fn()} onSegment={vi.fn()} onFile={vi.fn()} onUpload={vi.fn()} />); expect(screen.getByLabelText('Source document').getAttribute('accept')).toBe('.docx,.epub'); });
it('renders QA issues in the Quality workflow', () => { const report = { issues: [{ code: 'missing', severity: 'error', message: 'Wrong term', field: 'terminology', expected: 'API', actual: 'api', score_impact: 5 }], overall_score: 70, deterministic_score: 70, ai_score: null, ai_evaluated: false, status: 'needs_review', summary: 'Review needed', mode: 'deterministic' } as QualityReport; render(<QualityView segment={{ id: 1, chapter_id: 1, segment_number: 1, original_text: 'Source', translated_text: 'Translation', confidence: 1, model_used: null, status: 'translated', qa_score: 70, qa_status: 'needs_review', qa_comment: null, translation_profile: 'general', tokens_used: 3, latency_ms: 10 }} report={report} mode="deterministic" busy={false} onMode={vi.fn()} onCheck={vi.fn()} />); expect(screen.getByText('Wrong term')).toBeTruthy(); });
it('renders the safe benchmark dry-run form', () => { render(<BenchmarksView runs={[]} selectedRun={null} cases={[]} form={{ provider: 'openai', model: 'gpt-4o', max_cases: 5 }} busy={false} detailLoading={false} onForm={vi.fn()} onCreate={vi.fn()} onRun={vi.fn()} onResume={vi.fn()} onCancel={vi.fn()} onExport={vi.fn()} />); expect(screen.getByRole('button', { name: /start dry-run/i })).toBeTruthy(); });
it('maps every benchmark provider to its supported model', () => { const onForm = vi.fn(); render(<BenchmarksView runs={[]} selectedRun={null} cases={[]} form={{ provider: 'openai', model: 'gpt-4o', max_cases: 5 }} busy={false} detailLoading={false} onForm={onForm} onCreate={vi.fn()} onRun={vi.fn()} onResume={vi.fn()} onCancel={vi.fn()} onExport={vi.fn()} />); fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'deepl' } }); expect(onForm).toHaveBeenCalledWith(expect.objectContaining({ provider: 'deepl', model: 'free' })); });
it('requires explicit benchmark cancellation confirmation', () => { const onCancel = vi.fn(); const run = { run_id: 'run-1', provider: 'openai', model: 'gpt-4o', status: 'running', dataset_name: 'technical_translation', dataset_version: '2026.08.15', metrics: {}, category_metrics: {}, created_at: null }; render(<BenchmarksView runs={[run]} selectedRun={run} cases={[]} form={{ provider: 'openai', model: 'gpt-4o', max_cases: 5 }} busy={false} detailLoading={false} onForm={vi.fn()} onCreate={vi.fn()} onRun={vi.fn()} onResume={vi.fn()} onCancel={onCancel} onExport={vi.fn()} />); fireEvent.click(screen.getByRole('button', { name: 'Cancel' })); expect(onCancel).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole('button', { name: 'Cancel run' })); expect(onCancel).toHaveBeenCalledWith(run); });
it('renders persisted benchmark category metrics without recalculation', () => { const run = { run_id: 'run-1', provider: 'openai', model: 'gpt-4o', status: 'completed', dataset_name: 'technical_translation', dataset_version: '2026.08.15', metrics: { case_count: 2 }, category_metrics: { terminology: { case_count: 2, success_rate: 50, average_qa_score: 72, p95_latency_ms: 140, total_estimated_cost_usd: 0.01 } }, created_at: null }; render(<BenchmarksView runs={[run]} selectedRun={run} cases={[]} form={{ provider: 'openai', model: 'gpt-4o', max_cases: 5 }} busy={false} detailLoading={false} onForm={vi.fn()} onCreate={vi.fn()} onRun={vi.fn()} onResume={vi.fn()} onCancel={vi.fn()} onExport={vi.fn()} />); expect(screen.getByText('terminology')).toBeTruthy(); expect(screen.getByText('50% success')).toBeTruthy(); expect(screen.getByText('72 QA')).toBeTruthy(); });

it('renders a translation editor with read-only source and local draft tracking', () => {
  render(
    <BooksView
      books={[]}
      selectedBook={null}
      chapters={[]}
      selectedChapter={null}
      segments={[]}
      selectedSegment={{ id: 1, chapter_id: 10, segment_number: 1, original_text: 'Original text', translated_text: 'Old text', confidence: 0.9, model_used: 'gpt-4o', status: 'translated', qa_score: 88, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 10, latency_ms: 200 }}
      qualitySummary={null}
      detailLoading={false}
      uploadFile={null}
      busy={false}
      onBook={vi.fn()}
      onChapter={vi.fn()}
      onSegment={vi.fn()}
      onFile={vi.fn()}
      onUpload={vi.fn()}
    />
  );
  expect(screen.getByText('Original text')).toBeTruthy();
  expect(screen.getByDisplayValue('Old text')).toBeTruthy();
  expect(screen.getByRole('button', { name: /save translation/i })).toBeTruthy();
});

it('shows segment position and disables previous/next at boundaries', () => {
  const segments = [
    { id: 1, chapter_id: 10, segment_number: 1, original_text: 'First', translated_text: 'One', confidence: 0.8, model_used: 'gpt-4o', status: 'translated', qa_score: 80, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 5, latency_ms: 100 },
    { id: 2, chapter_id: 10, segment_number: 2, original_text: 'Second', translated_text: 'Two', confidence: 0.8, model_used: 'gpt-4o', status: 'translated', qa_score: 80, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 5, latency_ms: 100 },
    { id: 3, chapter_id: 10, segment_number: 3, original_text: 'Third', translated_text: 'Three', confidence: 0.8, model_used: 'gpt-4o', status: 'translated', qa_score: 80, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 5, latency_ms: 100 },
  ];
  render(
    <BooksView
      books={[]}
      selectedBook={null}
      chapters={[]}
      selectedChapter={null}
      segments={segments}
      selectedSegment={segments[0]}
      qualitySummary={null}
      detailLoading={false}
      uploadFile={null}
      busy={false}
      onPrevious={vi.fn()}
      onNext={vi.fn()}
      onBook={vi.fn()}
      onChapter={vi.fn()}
      onSegment={vi.fn()}
      onFile={vi.fn()}
      onUpload={vi.fn()}
    />
  );
  expect(screen.getByText('Segment 1 of 3')).toBeTruthy();
  const previousButton = screen.getByRole('button', { name: /previous/i }) as HTMLButtonElement;
  const nextButton = screen.getByRole('button', { name: /next/i }) as HTMLButtonElement;
  expect(previousButton.disabled).toBe(true);
  expect(nextButton.disabled).toBe(false);
});

it('uses the safe translation endpoint for manual  edits and keeps a draft on save failure', async () => {
  const chapter = { id: 11, book_id: 1, chapter_number: 1, title: 'Intro', content: null, status: 'segmented' };
  const sourceSegment = { id: 21, chapter_id: 11, segment_number: 1, original_text: 'Source text', translated_text: 'Old translation', confidence: 0.7, model_used: 'gpt-4o', status: 'translated', qa_score: 86, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 14, latency_ms: 30 };
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
    if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
    if (url.endsWith('/api/v1/books/1')) return json(book);
    if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
    if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 1, translated_segments: 1, checked_segments: 1, passed: 1, needs_review: 0, failed: 0, stale_reports: 0, average_score: 86 });
    if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [sourceSegment] });
    if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
    if (url.endsWith('/api/v1/segments/21/quality-report')) return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') return json({ code: 'internal_error', message: 'save failed', details: {}, request_id: 'req-fail' }, 500);
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<HomePage />);
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Updated translation' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/segments/21/translation'), expect.objectContaining({ method: 'PATCH' })));
  expect(screen.getByDisplayValue('Updated translation')).toBeTruthy();
  expect(screen.getByText('The action could not be completed.')).toBeTruthy();
});

it('ignores a stale save response after the active segment changes', async () => {
  const chapter = { id: 11, book_id: 1, chapter_number: 1, title: 'Intro', content: null, status: 'segmented' };
  const firstSegment = { id: 21, chapter_id: 11, segment_number: 1, original_text: 'Source text', translated_text: 'Old translation', confidence: 0.7, model_used: 'gpt-4o', status: 'translated', qa_score: 86, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 14, latency_ms: 30 };
  const secondSegment = { ...firstSegment, id: 22, segment_number: 2, original_text: 'Source text two', translated_text: 'Other translation' };
  const pendingSave = createDeferredResponse();
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
    if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
    if (url.endsWith('/api/v1/books/1')) return json(book);
    if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
    if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 2, translated_segments: 2, checked_segments: 2, passed: 2, needs_review: 0, failed: 0, stale_reports: 0, average_score: 86 });
    if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [firstSegment, secondSegment] });
    if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
    if (url.endsWith('/api/v1/segments/22/translation-jobs?page=1&page_size=20')) return json([]);
    if (url.endsWith('/api/v1/segments/21/quality-report')) return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
    if (url.endsWith('/api/v1/segments/22/quality-report')) return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') return pendingSave.promise;
    if (url.endsWith('/api/v1/segments/22/translation') && method === 'PATCH') return json({ ...secondSegment, translated_text: 'Newer translation', qa_status: 'stale', qa_score: 0, qa_comment: 'Manual translation edit invalidated the previous QA result.' });
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<HomePage />);
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Updated translation' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/segments/21/translation'), expect.objectContaining({ method: 'PATCH' })));

  fireEvent.click(screen.getByText('Source text two'));
  await waitFor(() => expect(screen.getByText('Source text two')).toBeTruthy());
  expect(screen.getByDisplayValue('Other translation')).toBeTruthy();

  pendingSave.resolve(json({ ...firstSegment, translated_text: 'Stale translation from the old request', qa_status: 'stale', qa_score: 0, qa_comment: 'Manual translation edit invalidated the previous QA result.' }));

  await waitFor(() => expect(screen.getByDisplayValue('Other translation')).toBeTruthy());
  expect(screen.queryByDisplayValue('Stale translation from the old request')).toBeNull();
  expect(screen.queryByText('Translation saved. Prior QA was marked stale.')).toBeNull();
  expect(screen.getByText('Source text two')).toBeTruthy();
});

it('does not leave the next section permanently busy after a save is invalidated by navigation', async () => {
  const chapter = { id: 11, book_id: 1, chapter_number: 1, title: 'Intro', content: null, status: 'segmented' };
  const firstSegment = { id: 21, chapter_id: 11, segment_number: 1, original_text: 'Source text', translated_text: 'Old translation', confidence: 0.7, model_used: 'gpt-4o', status: 'translated', qa_score: 86, qa_status: 'passed', qa_comment: null, translation_profile: 'general', tokens_used: 14, latency_ms: 30 };
  const pendingSave = createDeferredResponse();
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
    if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
    if (url.endsWith('/api/v1/books/1')) return json(book);
    if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
    if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 1, translated_segments: 1, checked_segments: 1, passed: 1, needs_review: 0, failed: 0, stale_reports: 0, average_score: 86 });
    if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [firstSegment] });
    if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20')) return json([]);
    if (url.endsWith('/api/v1/segments/21/quality-report')) return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
    if (url.endsWith('/api/v1/segments/21/translation') && method === 'PATCH') return pendingSave.promise;
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(window, 'confirm').mockReturnValue(true);

  render(<HomePage />);
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));

  fireEvent.change(screen.getByLabelText('Translation'), { target: { value: 'Updated translation' } });
  fireEvent.click(screen.getByRole('button', { name: /save translation/i }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/segments/21/translation'), expect.objectContaining({ method: 'PATCH' })));

  fireEvent.click(screen.getByRole('button', { name: /quality/i }));
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Quality', level: 1 })).toBeTruthy());

  pendingSave.resolve(json({ ...firstSegment, translated_text: 'Rejected stale translation', qa_status: 'stale', qa_score: 0, qa_comment: 'Manual translation edit invalidated the previous QA result.' }));

  const qualityButton = screen.getByRole('button', { name: /run quality check/i }) as HTMLButtonElement;
  await waitFor(() => expect(qualityButton.disabled).toBe(false));
  expect(screen.getByText('Updated translation')).toBeTruthy();
  expect(screen.queryByText('Rejected stale translation')).toBeNull();
  expect(screen.queryByText('Translation saved. Prior QA was marked stale.')).toBeNull();
});

it('refreshes the translated segment and QA report after a job completes', async () => {
  const chapter = { id: 11, book_id: 1, chapter_number: 1, title: 'Intro', content: null, status: 'segmented' };
  const sourceSegment = { id: 21, chapter_id: 11, segment_number: 1, original_text: 'Source text', translated_text: null, confidence: 0, model_used: null, status: 'pending', qa_score: 0, qa_status: null, qa_comment: null, translation_profile: 'general', tokens_used: 0, latency_ms: 0 };
  const translatedSegment = { ...sourceSegment, translated_text: 'Fresh translation', confidence: 0.98, model_used: 'gpt-4o', status: 'translated', qa_score: 96, qa_status: 'passed', tokens_used: 12, latency_ms: 30 };
  const report = { id: 31, segment_id: 21, translation_job_id: 41, evaluator_version: '1.0.0', mode: 'deterministic', deterministic_score: 96, ai_score: null, overall_score: 96, evaluator_error_code: null, score: 96, status: 'passed', summary: 'Fresh QA report', provider: 'openai', model: 'gpt-4o', source_language: 'en', target_language: 'ru', ai_evaluated: false, issues: [], created_at: null, updated_at: null };
  const queuedJob = { id: 41, segment_id: 21, provider: 'openai', model: 'gpt-4o', status: 'pending_enqueue', attempt: 0, max_attempts: 3, retry_of_id: null, error_code: null, error_message: null, created_at: null, queued_at: null, started_at: null, completed_at: null, failed_at: null, request_id: 'req-41' };
  const completedJob = { ...queuedJob, status: 'completed', attempt: 1, completed_at: '2026-08-15T04:30:00Z' };
  let qualityReads = 0;
  const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method || 'GET';
    if (url.endsWith('/api/v1/books?page=1&page_size=50')) return json({ items: [book] });
    if (url.endsWith('/api/v1/benchmark-runs?page=1&page_size=50')) return json({ items: [] });
    if (url.endsWith('/api/v1/books/1/chapters?page=1&page_size=50')) return json({ items: [chapter] });
    if (url.endsWith('/api/v1/books/1/quality-summary')) return json({ book_id: 1, total_segments: 1, translated_segments: 0, checked_segments: 0, passed: 0, needs_review: 0, failed: 0, stale_reports: 0, average_score: null });
    if (url.endsWith('/api/v1/books/1')) return json(book);
    if (url.endsWith('/api/v1/chapters/11/segments?page=1&page_size=100')) return json({ items: [sourceSegment] });
    if (url.endsWith('/api/v1/segments/21/translation-jobs?page=1&page_size=20') && method === 'GET') return json([]);
    if (url.endsWith('/api/v1/segments/21/translation-jobs') && method === 'POST') return json(queuedJob, 202);
    if (url.endsWith('/api/v1/translation-jobs/41')) return json(completedJob);
    if (url.endsWith('/api/v1/segments/21') && method === 'GET') return json(translatedSegment);
    if (url.endsWith('/api/v1/segments/21/quality-report')) {
      qualityReads += 1;
      if (qualityReads === 1) return json({ code: 'not_found', message: 'Quality report not found.', details: {}, request_id: 'req-missing' }, 404);
      return json(report);
    }
    throw new Error(`Unexpected request: ${method} ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<HomePage />);
  await screen.findByText('Distributed Systems');
  fireEvent.click(screen.getByText('Distributed Systems'));
  await screen.findByText('Intro');
  fireEvent.click(screen.getByText('Intro'));
  await screen.findByText('Source text');
  fireEvent.click(screen.getByText('Source text'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/segments/21/translation-jobs'), expect.anything()));
  fireEvent.click(screen.getByRole('button', { name: /Translation Jobs/ }));
  fireEvent.click(screen.getByRole('button', { name: /Queue translation/i }));

  await screen.findByText('Fresh translation');
  fireEvent.click(screen.getByRole('button', { name: /Quality/ }));
  await screen.findByText('Fresh QA report');
  expect(qualityReads).toBe(2);
});

describe('job polling', () => {
  it('stops scheduling requests when the polling component unmounts', async () => {
    function PollingHarness({ fetchStatus }: { fetchStatus: () => Promise<{ status: 'running' | 'completed' }> }) { React.useEffect(() => { const controller = new AbortController(); void pollUntilTerminal(fetchStatus, { signal: controller.signal, intervalMs: 20 }).catch((error: unknown) => { if (!(error instanceof DOMException && error.name === 'AbortError')) throw error; }); return () => controller.abort(); }, [fetchStatus]); return <span>polling</span>; }
    const fetchStatus = vi.fn().mockResolvedValue({ status: 'running' as const });
    const rendered = render(<PollingHarness fetchStatus={fetchStatus} />);
    await waitFor(() => expect(fetchStatus).toHaveBeenCalledTimes(1));
    rendered.unmount();
    await new Promise((resolve) => setTimeout(resolve, 35));
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it('stops after a terminal status with one request per update', async () => { const fetchStatus = vi.fn().mockResolvedValueOnce({ status: 'running' }).mockResolvedValueOnce({ status: 'completed' }); const controller = new AbortController(); const resultPromise = pollUntilTerminal(fetchStatus, { signal: controller.signal, intervalMs: 0 }); await expect(resultPromise).resolves.toEqual({ status: 'completed' }); expect(fetchStatus).toHaveBeenCalledTimes(2); });
  it('aborts polling after unmount/navigation', async () => { const controller = new AbortController(); const fetchStatus = vi.fn().mockResolvedValue({ status: 'running' }); const resultPromise = pollUntilTerminal(fetchStatus, { signal: controller.signal, intervalMs: 50 }); controller.abort(); await expect(resultPromise).rejects.toMatchObject({ name: 'AbortError' }); expect(fetchStatus).toHaveBeenCalledTimes(1); });
});
