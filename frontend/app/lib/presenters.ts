import type { Book, QualityReport, TranslationJob } from './types';

export function bookRowLabel(book: Book): string {
  return `${book.title} - ${book.author || 'Unknown author'} - ${book.language.toUpperCase()}`;
}

export function failedJobMessage(job: TranslationJob): string {
  return job.status === 'failed' ? 'The provider reported a failure.' : '';
}

export function qualityIssueCount(report: QualityReport): number {
  return report.issues.length;
}
