import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BooksView, BenchmarksView, QualityView } from '../app/components/views';
import { bookRowLabel, failedJobMessage, qualityIssueCount } from '../app/lib/presenters';
import { benchmarkPayload, canRetryJob, pollUntilTerminal, validateUpload } from '../app/lib/workflow';
import type { Book, QualityReport, TranslationJob } from '../app/lib/types';

const book: Book = { id: 1, title: 'Distributed Systems', author: 'A. Writer', description: null, file_path: 'book.epub', file_type: 'epub', language: 'en', status: 'uploaded' };
const failedJob: TranslationJob = { id: 2, segment_id: 1, provider: 'openai', model: 'gpt-4o', status: 'failed', attempt: 3, max_attempts: 3, retry_of_id: null, error_code: 'provider_unavailable_error', error_message: 'hidden', created_at: null, queued_at: null, started_at: null, completed_at: null, failed_at: null, request_id: 'req-1' };

it('renders a stable book list label', () => expect(bookRowLabel(book)).toBe('Distributed Systems - A. Writer - EN'));
it('validates upload extension and size', () => { expect(validateUpload({ name: 'book.exe', size: 10 })).toContain('EPUB'); expect(validateUpload({ name: 'book.epub', size: 26 * 1024 * 1024 })).toContain('25 MB'); expect(validateUpload({ name: 'book.epub', size: 10 })).toBeNull(); });
it('shows retry only for failed jobs', () => { expect(canRetryJob('failed')).toBe(true); expect(canRetryJob('running')).toBe(false); expect(failedJobMessage(failedJob)).toContain('failure'); });
it('keeps benchmark execution in dry-run mode', () => expect(benchmarkPayload('openai', 'gpt-4o', 5)).toMatchObject({ dry_run: true, confirm_live_provider: false, max_cases: 5 }));
it('exposes QA issue count', () => { const report = { issues: [{ code: 'missing', severity: 'error', message: 'Missing', field: null, expected: null, actual: null, score_impact: 5 }] } as QualityReport; expect(qualityIssueCount(report)).toBe(1); });
it('renders a book row in the Books workflow', () => { render(<BooksView books={[book]} selectedBook={null} chapters={[]} selectedChapter={null} segments={[]} selectedSegment={null} qualitySummary={null} detailLoading={false} uploadFile={null} busy={false} onBook={vi.fn()} onChapter={vi.fn()} onSegment={vi.fn()} onFile={vi.fn()} onUpload={vi.fn()} />); expect(screen.getByText('Distributed Systems')).toBeTruthy(); });
it('renders QA issues in the Quality workflow', () => { const report = { issues: [{ code: 'missing', severity: 'error', message: 'Wrong term', field: 'terminology', expected: 'API', actual: 'api', score_impact: 5 }], overall_score: 70, deterministic_score: 70, ai_score: null, ai_evaluated: false, status: 'needs_review', summary: 'Review needed', mode: 'deterministic' } as QualityReport; render(<QualityView segment={{ id: 1, chapter_id: 1, segment_number: 1, original_text: 'Source', translated_text: 'Translation', confidence: 1, model_used: null, status: 'translated', qa_score: 70, qa_status: 'needs_review', qa_comment: null, translation_profile: 'general', tokens_used: 3, latency_ms: 10 }} report={report} mode="deterministic" busy={false} onMode={vi.fn()} onCheck={vi.fn()} />); expect(screen.getByText('Wrong term')).toBeTruthy(); });
it('renders the safe benchmark dry-run form', () => { render(<BenchmarksView runs={[]} selectedRun={null} cases={[]} form={{ provider: 'openai', model: 'gpt-4o', max_cases: 5 }} busy={false} detailLoading={false} onForm={vi.fn()} onCreate={vi.fn()} onRun={vi.fn()} onResume={vi.fn()} onCancel={vi.fn()} onExport={vi.fn()} />); expect(screen.getByRole('button', { name: /start dry-run/i })).toBeTruthy(); });

describe('job polling', () => {
  it('stops after a terminal status with one request per update', async () => { const fetchStatus = vi.fn().mockResolvedValueOnce({ status: 'running' }).mockResolvedValueOnce({ status: 'completed' }); const controller = new AbortController(); const resultPromise = pollUntilTerminal(fetchStatus, { signal: controller.signal, intervalMs: 0 }); await expect(resultPromise).resolves.toEqual({ status: 'completed' }); expect(fetchStatus).toHaveBeenCalledTimes(2); });
  it('aborts polling after unmount/navigation', async () => { const controller = new AbortController(); const fetchStatus = vi.fn().mockResolvedValue({ status: 'running' }); const resultPromise = pollUntilTerminal(fetchStatus, { signal: controller.signal, intervalMs: 50 }); controller.abort(); await expect(resultPromise).rejects.toMatchObject({ name: 'AbortError' }); expect(fetchStatus).toHaveBeenCalledTimes(1); });
});
