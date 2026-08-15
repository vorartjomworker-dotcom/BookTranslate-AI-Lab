'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, ApiTimeoutError } from './lib/api';
import type { BenchmarkCase, BenchmarkRun, Book, Chapter, Paginated, QualityReport, QualitySummary, Segment, TranslationJob } from './lib/types';
import { benchmarkPayload, canRetryJob, pollUntilTerminal, validateUpload } from './lib/workflow';
import { BenchmarksView, BooksView, JobsView, QualityView } from './components/views';

type Section = 'books' | 'jobs' | 'quality' | 'benchmarks';
const sections: { id: Section; label: string; number: string }[] = [{ id: 'books', label: 'Books', number: '01' }, { id: 'jobs', label: 'Translation Jobs', number: '02' }, { id: 'quality', label: 'Quality', number: '03' }, { id: 'benchmarks', label: 'Benchmarks', number: '04' }];

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'The action could not be completed.';
    return error.message;
  }
  if (error instanceof ApiTimeoutError || error instanceof Error) return error.message;
  return 'The action could not be completed.';
}

export default function HomePage() {
  const [section, setSection] = useState<Section>('books');
  const [books, setBooks] = useState<Book[]>([]);
  const [selectedBook, setSelectedBook] = useState<Book | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<Chapter | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [selectedSegment, setSelectedSegment] = useState<Segment | null>(null);
  const [jobs, setJobs] = useState<TranslationJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<TranslationJob | null>(null);
  const [qualityReport, setQualityReport] = useState<QualityReport | null>(null);
  const [qualitySummary, setQualitySummary] = useState<QualitySummary | null>(null);
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRun | null>(null);
  const [benchmarkCases, setBenchmarkCases] = useState<BenchmarkCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [qualityMode, setQualityMode] = useState<'deterministic' | 'full'>('deterministic');
  const [benchmarkForm, setBenchmarkForm] = useState({ provider: 'openai', model: 'gpt-4o', max_cases: 5 });
  const [draftTranslation, setDraftTranslation] = useState('');
  const [draftDirty, setDraftDirty] = useState(false);
  const detailRequestController = useRef<AbortController | null>(null);
  const saveRequestController = useRef<AbortController | null>(null);
  const saveRequestToken = useRef(0);
  const activeSegmentIdRef = useRef<number | null>(null);
  const draftTranslationRef = useRef('');

  function invalidateSaveRequest() {
    saveRequestToken.current += 1;
    saveRequestController.current?.abort();
    saveRequestController.current = null;
    setSaveBusy(false);
  }

  async function loadBooks() { setLoading(true); setError(''); try { const response = await api.get<Paginated<Book>>('/api/v1/books?page=1&page_size=50'); setBooks(response.items || []); } catch (requestError) { setError(errorMessage(requestError)); } finally { setLoading(false); } }
  async function loadRuns() { try { const response = await api.get<Paginated<BenchmarkRun>>('/api/v1/benchmark-runs?page=1&page_size=50'); setRuns(response.items || []); } catch (requestError) { setError(errorMessage(requestError)); } }
  // These calls synchronize the initial view with the external API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void loadBooks(); void loadRuns(); }, []);

  function clearSegmentState() { setSelectedJob(null); setJobs([]); setQualityReport(null); draftTranslationRef.current = ''; setDraftTranslation(''); setDraftDirty(false); activeSegmentIdRef.current = null; }
  function startDetailRequest() { detailRequestController.current?.abort(); const controller = new AbortController(); detailRequestController.current = controller; return controller; }
  function isAbortError(error: unknown) { return error instanceof DOMException && error.name === 'AbortError'; }
  async function openBook(book: Book) { const controller = startDetailRequest(); invalidateSaveRequest(); clearSegmentState(); setSelectedBook(book); setSelectedChapter(null); setSelectedSegment(null); setChapters([]); setSegments([]); setQualitySummary(null); setDetailLoading(true); setError(''); try { const [bookResponse, chapterResponse, summaryResponse] = await Promise.all([api.get<Book>(`/api/v1/books/${book.id}`, { signal: controller.signal }), api.get<Paginated<Chapter>>(`/api/v1/books/${book.id}/chapters?page=1&page_size=50`, { signal: controller.signal }), api.get<QualitySummary>(`/api/v1/books/${book.id}/quality-summary`, { signal: controller.signal })]); if (controller.signal.aborted) return; setSelectedBook(bookResponse); setChapters(chapterResponse.items || []); setQualitySummary(summaryResponse); } catch (requestError) { if (!isAbortError(requestError)) setError(errorMessage(requestError)); } finally { if (!controller.signal.aborted) setDetailLoading(false); } }
  async function openChapter(chapter: Chapter) { const controller = startDetailRequest(); invalidateSaveRequest(); clearSegmentState(); setSelectedChapter(chapter); setSelectedSegment(null); setSegments([]); setDetailLoading(true); setError(''); try { const response = await api.get<Paginated<Segment>>(`/api/v1/chapters/${chapter.id}/segments?page=1&page_size=100`, { signal: controller.signal }); if (!controller.signal.aborted) setSegments(response.items || []); } catch (requestError) { if (!isAbortError(requestError)) setError(errorMessage(requestError)); } finally { if (!controller.signal.aborted) setDetailLoading(false); } }
  async function openSegment(segment: Segment) { const controller = startDetailRequest(); invalidateSaveRequest(); clearSegmentState(); activeSegmentIdRef.current = segment.id; setSelectedSegment(segment); const canonicalDraft = segment.translated_text ?? ''; draftTranslationRef.current = canonicalDraft; setDraftTranslation(canonicalDraft); setDraftDirty(false); setError(''); const [jobResponse, reportResponse] = await Promise.allSettled([api.get<TranslationJob[]>(`/api/v1/segments/${segment.id}/translation-jobs?page=1&page_size=20`, { signal: controller.signal }), api.get<QualityReport>(`/api/v1/segments/${segment.id}/quality-report`, { signal: controller.signal })]); if (controller.signal.aborted) return; if (jobResponse.status === 'fulfilled') setJobs(jobResponse.value); if (reportResponse.status === 'fulfilled') setQualityReport(reportResponse.value); else if (reportResponse.reason instanceof ApiError && reportResponse.reason.status !== 404) setError(errorMessage(reportResponse.reason)); if (jobResponse.status === 'rejected' && !isAbortError(jobResponse.reason)) setJobs([]); }

  useEffect(() => {
    if (!draftDirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [draftDirty]);

  const saveTranslation = useCallback(async () => {
    if (!selectedSegment || saveBusy) return;
    const original = selectedSegment.translated_text ?? '';
    if (draftTranslation === original) {
      setDraftDirty(false);
      return;
    }
    const segmentId = selectedSegment.id;
    const submittedDraft = draftTranslation;
    const token = ++saveRequestToken.current;
    const controller = new AbortController();
    saveRequestController.current = controller;
    setSaveBusy(true);
    setError('');
    try {
      const updated = await api.patch<Segment>(
        `/api/v1/segments/${segmentId}/translation`,
        { translated_text: submittedDraft },
        { signal: controller.signal },
      );
      if (controller.signal.aborted || saveRequestToken.current !== token || activeSegmentIdRef.current !== segmentId) return;
      const nextSegment = { ...updated, qa_status: 'stale', qa_score: 0, qa_comment: 'Manual translation edit invalidated the previous QA result.' };
      setSelectedSegment(nextSegment);
      setSegments((current) => current.map((item) => item.id === nextSegment.id ? nextSegment : item));
      const currentDraft = draftTranslationRef.current;
      const canonicalDraft = nextSegment.translated_text ?? '';
      if (currentDraft === submittedDraft) {
        draftTranslationRef.current = canonicalDraft;
        setDraftTranslation(canonicalDraft);
        setDraftDirty(false);
        setNotice('Translation saved. Prior QA was marked stale.');
      } else {
        setDraftDirty(currentDraft !== canonicalDraft);
        setNotice('Translation saved. Newer edits remain unsaved.');
      }
      setQualityReport(null);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return;
      if (saveRequestToken.current !== token || activeSegmentIdRef.current !== segmentId) return;
      setError(errorMessage(requestError));
    } finally {
      if (saveRequestController.current === controller) saveRequestController.current = null;
      if (saveRequestToken.current === token && activeSegmentIdRef.current === segmentId) setSaveBusy(false);
    }
  }, [draftTranslation, saveBusy, selectedSegment]);

  useEffect(() => {
    if (!selectedSegment) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        if (!busy && !saveBusy && draftTranslation !== (selectedSegment.translated_text ?? '')) {
          void saveTranslation();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedSegment?.id, draftTranslation, busy, saveBusy, saveTranslation]);

  function handleDraftChange(value: string) {
    draftTranslationRef.current = value;
    setDraftTranslation(value);
    if (!selectedSegment) {
      setDraftDirty(false);
      return;
    }
    setDraftDirty(value !== (selectedSegment.translated_text ?? ''));
  }

  function confirmNavigation(action: () => void) {
    if (!draftDirty) {
      action();
      return;
    }
    const proceed = window.confirm('You have unsaved changes. Discard the draft and continue?');
    if (proceed) {
      const canonicalDraft = selectedSegment?.translated_text ?? '';
      draftTranslationRef.current = canonicalDraft;
      setDraftTranslation(canonicalDraft);
      setDraftDirty(false);
      action();
    }
  }

  function changeSection(nextSection: Section) {
    if (section === nextSection) return;
    confirmNavigation(() => {
      invalidateSaveRequest();
      setSection(nextSection);
    });
  }

  function moveToSegment(offset: number) {
    if (!selectedSegment || !segments.length) return;
    const index = segments.findIndex((segment) => segment.id === selectedSegment.id);
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= segments.length) return;
    confirmNavigation(() => {
      invalidateSaveRequest();
      const nextSegment = segments[nextIndex];
      if (!nextSegment) return;
      void openSegment(nextSegment);
    });
  }

  function resetDraft() {
    if (!selectedSegment) return;
    const canonicalDraft = selectedSegment.translated_text ?? '';
    draftTranslationRef.current = canonicalDraft;
    setDraftTranslation(canonicalDraft);
    setDraftDirty(false);
  }

  async function refreshCompletedSegment(segmentId: number, signal: AbortSignal) {
    const [segmentResponse, reportResponse] = await Promise.allSettled([
      api.get<Segment>(`/api/v1/segments/${segmentId}`, { signal }),
      api.get<QualityReport>(`/api/v1/segments/${segmentId}/quality-report`, { signal }),
    ]);
    if (signal.aborted) return;
    if (segmentResponse.status === 'fulfilled') {
      setSelectedSegment((current) => current?.id === segmentId ? segmentResponse.value : current);
      setSegments((current) => current.map((item) => item.id === segmentId ? segmentResponse.value : item));
    } else if (!isAbortError(segmentResponse.reason)) {
      setError(errorMessage(segmentResponse.reason));
    }
    if (reportResponse.status === 'fulfilled') {
      setQualityReport(reportResponse.value);
    } else if (reportResponse.reason instanceof ApiError && reportResponse.reason.status === 404) {
      setQualityReport(null);
    } else if (!isAbortError(reportResponse.reason)) {
      setError(errorMessage(reportResponse.reason));
    }
  }

  useEffect(() => {
    if (section !== 'jobs' || !selectedSegment || !selectedJob || selectedJob.segment_id !== selectedSegment.id || selectedJob.status === 'completed' || selectedJob.status === 'failed') return;
    const controller = new AbortController();
    const segmentId = selectedSegment.id;
    const jobId = selectedJob.id;
    void pollUntilTerminal(
      () => api.get<TranslationJob>(`/api/v1/translation-jobs/${jobId}`, { signal: controller.signal }),
      {
        signal: controller.signal,
        intervalMs: 1200,
        onUpdate: (job) => {
          if (controller.signal.aborted) return;
          setSelectedJob(job);
          setJobs((current) => current.map((item) => item.id === job.id ? job : item));
        },
      },
    ).then(async (terminalJob) => {
      if (controller.signal.aborted || terminalJob.status !== 'completed') return;
      await refreshCompletedSegment(segmentId, controller.signal);
    }).catch((pollError) => {
      if (!(pollError instanceof DOMException && pollError.name === 'AbortError')) setError(errorMessage(pollError));
    });
    return () => controller.abort();
  }, [section, selectedSegment?.id, selectedJob?.id]);
  useEffect(() => () => { detailRequestController.current?.abort(); saveRequestController.current?.abort(); }, []);

  async function upload(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!uploadFile) { setError('Choose an EPUB or DOCX file.'); return; } const validationError = validateUpload(uploadFile); if (validationError) { setError(validationError); return; } const body = new FormData(); body.append('file', uploadFile); setBusy(true); setError(''); setNotice(''); try { await api.upload('/api/v1/books/upload', body); setUploadFile(null); setNotice('Document uploaded and queued for ingestion.'); await loadBooks(); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }
  async function createJob() { if (!selectedSegment) return; setBusy(true); setError(''); try { const job = await api.post<TranslationJob>(`/api/v1/segments/${selectedSegment.id}/translation-jobs`, {}); setJobs((current) => [job, ...current]); setSelectedJob(job); setNotice('Translation job queued.'); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }
  async function retryJob(job: TranslationJob) { if (!canRetryJob(job.status)) return; setBusy(true); setError(''); try { const retry = await api.post<TranslationJob>(`/api/v1/translation-jobs/${job.id}/retry`); setJobs((current) => [retry, ...current]); setSelectedJob(retry); setNotice('Failed job queued for retry.'); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }
  async function runQualityCheck() {
    if (!selectedSegment) return;
    const segmentId = selectedSegment.id;
    setBusy(true);
    setError('');
    try {
      const report = await api.post<QualityReport>(`/api/v1/segments/${segmentId}/quality-check`, { mode: qualityMode });
      if (activeSegmentIdRef.current !== segmentId) return;
      const qaPatch = { qa_status: report.status, qa_score: report.overall_score, qa_comment: report.summary };
      setQualityReport(report);
      setSelectedSegment((current) => current?.id === segmentId ? { ...current, ...qaPatch } : current);
      setSegments((current) => current.map((item) => item.id === segmentId ? { ...item, ...qaPatch } : item));
      setNotice(`${qualityMode} quality check completed.`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }
  async function createBenchmark(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(''); try { const created = await api.post<{ run_id: string }>('/api/v1/benchmark-runs', benchmarkPayload(benchmarkForm.provider, benchmarkForm.model, benchmarkForm.max_cases)); await api.post(`/api/v1/benchmark-runs/${created.run_id}/resume`); setNotice(`Benchmark ${created.run_id} completed in dry-run mode.`); await loadRuns(); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }

  async function openRun(run: BenchmarkRun) { setSelectedRun(run); setDetailLoading(true); setError(''); try { const [detail, cases] = await Promise.all([api.get<BenchmarkRun>(`/api/v1/benchmark-runs/${run.run_id}`), api.get<{ items: BenchmarkCase[] }>(`/api/v1/benchmark-runs/${run.run_id}/cases`)]); setSelectedRun(detail); setBenchmarkCases(cases.items || []); } catch (requestError) { setError(errorMessage(requestError)); } finally { setDetailLoading(false); } }
  async function resumeRun(run: BenchmarkRun) { setBusy(true); try { await api.post(`/api/v1/benchmark-runs/${run.run_id}/resume`); await loadRuns(); setNotice('Benchmark resumed.'); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }
  async function cancelRun(run: BenchmarkRun) { setBusy(true); try { await api.post(`/api/v1/benchmark-runs/${run.run_id}/cancel`, { reason: 'Cancelled from workspace.' }); await loadRuns(); setNotice('Benchmark cancelled.'); } catch (requestError) { setError(errorMessage(requestError)); } finally { setBusy(false); } }
  async function exportRun(run: BenchmarkRun, format: 'json' | 'csv') { try { const blob = await api.get<Blob>(`/api/v1/benchmark-runs/${run.run_id}/export?format=${format}`, { responseType: 'blob', headers: { Accept: format === 'csv' ? 'text/csv' : 'application/json' } }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${run.run_id}.${format}`; link.click(); URL.revokeObjectURL(link.href); } catch (requestError) { setError(errorMessage(requestError)); } }

  const current = sections.find((item) => item.id === section);
  return <main className="appShell"><aside className="sidebar"><div className="brandMark"><span className="brandGlyph">BT</span><span><strong>BookTranslate</strong><small>AI LAB / WORKSPACE</small></span></div><div className="sidebarLabel">Workspace</div><nav className="sideNav" aria-label="Workspace sections">{sections.map((item) => <button key={item.id} className={section === item.id ? 'navItem active' : 'navItem'} onClick={() => changeSection(item.id)}><span>{item.number}</span>{item.label}</button>)}</nav><div className="sidebarFooter"><span>v0.1.0 / local workspace</span></div></aside><section className="contentArea"><header className="topBar"><div><span className="eyebrow">TRANSLATION OPERATIONS</span><h1>{current?.label}</h1></div><span className="avatar" aria-hidden="true">BT</span></header>{error && <div className="alert alertError" role="alert"><strong>Action blocked</strong><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}{notice && <div className="alert alertSuccess" role="status" aria-live="polite"><strong>Done</strong><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Dismiss notice">×</button></div>}{loading ? <div className="loadingState"><span className="loader" /> Loading workspace</div> : <>{section === 'books' && <BooksView books={books} selectedBook={selectedBook} chapters={chapters} selectedChapter={selectedChapter} segments={segments} selectedSegment={selectedSegment} qualitySummary={qualitySummary} detailLoading={detailLoading} uploadFile={uploadFile} busy={busy} draftTranslation={draftTranslation} isDirty={draftDirty} canSave={Boolean(selectedSegment) && draftTranslation !== (selectedSegment?.translated_text ?? '') && !busy && !saveBusy} onPrevious={() => moveToSegment(-1)} onNext={() => moveToSegment(1)} onDraftChange={handleDraftChange} onSave={saveTranslation} onReset={resetDraft} onBook={(book) => confirmNavigation(() => { void openBook(book); })} onChapter={(chapter) => confirmNavigation(() => { void openChapter(chapter); })} onSegment={(segment) => confirmNavigation(() => { void openSegment(segment); })} onFile={(event) => setUploadFile(event.target.files?.[0] || null)} onUpload={upload} />}{section === 'jobs' && <JobsView segment={selectedSegment} jobs={jobs} selectedJob={selectedJob} busy={busy} onCreate={createJob} onRetry={retryJob} />}{section === 'quality' && <QualityView segment={selectedSegment} report={qualityReport} mode={qualityMode} busy={busy} onMode={setQualityMode} onCheck={runQualityCheck} />}{section === 'benchmarks' && <BenchmarksView runs={runs} selectedRun={selectedRun} cases={benchmarkCases} form={benchmarkForm} busy={busy} detailLoading={detailLoading} onForm={setBenchmarkForm} onCreate={createBenchmark} onRun={openRun} onResume={resumeRun} onCancel={cancelRun} onExport={exportRun} />}</>}</section></main>;
}
