import type { TranslationJobStatus } from './types';

export const ACCEPTED_UPLOAD_TYPES = new Set(['epub', 'docx', 'pdf']);
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const TERMINAL_JOB_STATUSES = new Set<TranslationJobStatus>(['completed', 'failed']);

export function validateUpload(file: { name: string; size: number }): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  if (!ACCEPTED_UPLOAD_TYPES.has(extension)) return 'Choose an EPUB, DOCX, or PDF file.';
  if (file.size > MAX_UPLOAD_BYTES) return 'The selected file is larger than 25 MB.';
  return null;
}

export function canRetryJob(status: TranslationJobStatus): boolean {
  return status === 'failed';
}

export function benchmarkPayload(provider: string, model: string, maxCases: number) {
  return { provider, model, max_cases: maxCases, dataset_name: 'technical_translation', dataset_version: '2026.08.15', dry_run: true, confirm_live_provider: false };
}

export async function pollUntilTerminal<T extends { status: TranslationJobStatus }>(fetchStatus: () => Promise<T>, options: { signal: AbortSignal; intervalMs?: number; onUpdate?: (value: T) => void }): Promise<T> {
  let current = await fetchStatus();
  options.onUpdate?.(current);
  while (!TERMINAL_JOB_STATUSES.has(current.status)) {
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, options.intervalMs ?? 1000);
      options.signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); }, { once: true });
    });
    if (options.signal.aborted) throw new DOMException('Aborted', 'AbortError');
    current = await fetchStatus();
    options.onUpdate?.(current);
  }
  return current;
}
