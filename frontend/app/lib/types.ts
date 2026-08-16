export type Paginated<T> = { items: T[]; total?: number; page?: number; page_size?: number };

export type Book = {
  id: number;
  title: string;
  author: string | null;
  description: string | null;
  file_path: string;
  file_type: string;
  language: string;
  status: string;
};

export type Chapter = {
  id: number;
  book_id: number;
  chapter_number: number;
  title: string;
  content: string | null;
  status: string;
};

export type Segment = {
  id: number;
  chapter_id: number;
  segment_number: number;
  original_text: string;
  translated_text: string | null;
  confidence: number;
  model_used: string | null;
  status: string;
  qa_score: number;
  qa_status: string | null;
  qa_comment: string | null;
  translation_profile: string;
  tokens_used: number;
  latency_ms: number;
};

export type TranslationJobStatus = 'pending_enqueue' | 'queued' | 'running' | 'completed' | 'failed';
export type TranslationJob = {
  id: number;
  segment_id: number;
  provider: string;
  model: string | null;
  status: TranslationJobStatus;
  attempt: number;
  max_attempts: number;
  retry_of_id: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  request_id: string | null;
};

export type QualityIssue = { code: string; severity: string; message: string; field: string | null; expected: string | null; actual: string | null; score_impact: number };
export type QualityReport = {
  id: number;
  segment_id: number;
  translation_job_id: number | null;
  evaluator_version: string;
  mode: string;
  deterministic_score: number;
  ai_score: number | null;
  overall_score: number;
  evaluator_error_code: string | null;
  score: number;
  status: string;
  summary: string;
  provider: string | null;
  model: string | null;
  source_language: string | null;
  target_language: string | null;
  ai_evaluated: boolean;
  issues: QualityIssue[];
  created_at: string | null;
  updated_at: string | null;
};

export type QualitySummary = { book_id: number; total_segments: number; translated_segments: number; checked_segments: number; passed: number; needs_review: number; failed: number; stale_reports: number; average_score: number | null };

export type BenchmarkRun = { run_id: string; provider: string; model: string; status: string; dataset_name: string; dataset_version: string; metrics: Record<string, number | string>; category_metrics: Record<string, Record<string, number | string>>; created_at: string | null };
export type BenchmarkCase = { id: number; case_id: string; category: string; status: string; attempt_count: number; latency_ms: number; total_tokens: number; estimated_cost_usd: number; qa_score: number; qa_passed: boolean; error_code: string | null; error_message: string | null };

export type HealthResponse = { status: 'ok' | 'degraded'; database: boolean; redis: boolean };
