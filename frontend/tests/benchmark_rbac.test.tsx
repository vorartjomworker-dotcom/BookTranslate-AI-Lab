import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { BenchmarksView } from '../app/components/views';
import type { BenchmarkRun } from '../app/lib/types';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function makeRun(overrides: Partial<BenchmarkRun> = {}): BenchmarkRun {
  return {
    run_id: 'bench-1',
    provider: 'openai',
    model: 'gpt-4o',
    status: 'pending',
    dry_run: true,
    dataset_name: 'technical_translation',
    dataset_version: '1.0.0',
    metrics: {},
    category_metrics: {},
    created_at: null,
    ...overrides,
  };
}

function renderBenchmarks(
  role: 'viewer' | 'editor' | 'admin',
  options: { selectedRun?: BenchmarkRun | null } = {},
) {
  const onCreate = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
  const onResume = vi.fn();
  const onCancel = vi.fn();
  render(
    <BenchmarksView
      runs={options.selectedRun ? [options.selectedRun] : []}
      selectedRun={options.selectedRun ?? null}
      cases={[]}
      form={{ provider: 'openai', model: 'gpt-4o', max_cases: 10 }}
      busy={false}
      role={role}
      detailLoading={false}
      onForm={vi.fn()}
      onCreate={onCreate}
      onRun={vi.fn()}
      onResume={onResume}
      onCancel={onCancel}
      onExport={vi.fn()}
    />,
  );
  return { onCreate, onResume, onCancel };
}

it('allows an editor to start a dry-run benchmark', () => {
  const { onCreate } = renderBenchmarks('editor');
  const button = screen.getByRole('button', { name: /start dry-run/i }) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  fireEvent.click(button);
  expect(onCreate).toHaveBeenCalledTimes(1);
});

it('keeps dry-run benchmark creation disabled for a viewer', () => {
  const { onCreate } = renderBenchmarks('viewer');
  const button = screen.getByRole('button', { name: /editor or admin role required/i }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(onCreate).not.toHaveBeenCalled();
});

it('allows an admin to start a dry-run benchmark', () => {
  const { onCreate } = renderBenchmarks('admin');
  const button = screen.getByRole('button', { name: /start dry-run/i }) as HTMLButtonElement;
  expect(button.disabled).toBe(false);
  fireEvent.click(button);
  expect(onCreate).toHaveBeenCalledTimes(1);
});

it('allows an editor to resume a persisted dry-run benchmark', () => {
  const run = makeRun({ dry_run: true, status: 'pending' });
  const { onResume } = renderBenchmarks('editor', { selectedRun: run });
  const button = screen.getByRole('button', { name: /^resume$/i }) as HTMLButtonElement;
  fireEvent.click(button);
  expect(onResume).toHaveBeenCalledTimes(1);
  expect(onResume).toHaveBeenCalledWith(run);
});

it('hides resume for an editor on a persisted live (non dry-run) benchmark', () => {
  const run = makeRun({ dry_run: false, status: 'pending' });
  const { onResume } = renderBenchmarks('editor', { selectedRun: run });
  expect(screen.queryByRole('button', { name: /^resume$/i })).toBeNull();
  expect(onResume).not.toHaveBeenCalled();
});

it('allows an admin to resume a persisted dry-run benchmark', () => {
  const run = makeRun({ dry_run: true, status: 'pending' });
  const { onResume } = renderBenchmarks('admin', { selectedRun: run });
  const button = screen.getByRole('button', { name: /^resume$/i }) as HTMLButtonElement;
  fireEvent.click(button);
  expect(onResume).toHaveBeenCalledTimes(1);
});

it('allows an admin to resume a persisted live benchmark', () => {
  const run = makeRun({ dry_run: false, status: 'pending' });
  const { onResume } = renderBenchmarks('admin', { selectedRun: run });
  const button = screen.getByRole('button', { name: /^resume$/i }) as HTMLButtonElement;
  fireEvent.click(button);
  expect(onResume).toHaveBeenCalledTimes(1);
});

it('hides resume for a viewer on a persisted dry-run benchmark', () => {
  const run = makeRun({ dry_run: true, status: 'pending' });
  const { onResume } = renderBenchmarks('viewer', { selectedRun: run });
  expect(screen.queryByRole('button', { name: /^resume$/i })).toBeNull();
  expect(onResume).not.toHaveBeenCalled();
});

it('never allows an editor to cancel a benchmark regardless of dry_run', () => {
  const dryRun = makeRun({ dry_run: true, status: 'pending' });
  const { onCancel: onCancelDry } = renderBenchmarks('editor', { selectedRun: dryRun });
  expect(screen.queryByRole('button', { name: /^cancel$/i })).toBeNull();
  cleanup();

  const liveRun = makeRun({ dry_run: false, status: 'pending' });
  const { onCancel: onCancelLive } = renderBenchmarks('editor', { selectedRun: liveRun });
  expect(screen.queryByRole('button', { name: /^cancel$/i })).toBeNull();
  expect(onCancelDry).not.toHaveBeenCalled();
  expect(onCancelLive).not.toHaveBeenCalled();
});

it('keeps cancel available for an admin on an active benchmark', () => {
  const run = makeRun({ dry_run: true, status: 'pending' });
  renderBenchmarks('admin', { selectedRun: run });
  expect(screen.getByRole('button', { name: /^cancel$/i })).not.toBeNull();
});

it('decides editor resume access from persisted run.dry_run, not provider/model/status alone', () => {
  const dryRunSameFields = makeRun({ provider: 'openai', model: 'gpt-4o', status: 'pending', dry_run: true });
  const liveSameFields = makeRun({ provider: 'openai', model: 'gpt-4o', status: 'pending', dry_run: false });

  const { onResume: onResumeDry } = renderBenchmarks('editor', { selectedRun: dryRunSameFields });
  expect(screen.getByRole('button', { name: /^resume$/i })).not.toBeNull();
  cleanup();

  const { onResume: onResumeLive } = renderBenchmarks('editor', { selectedRun: liveSameFields });
  expect(screen.queryByRole('button', { name: /^resume$/i })).toBeNull();
  expect(onResumeDry).not.toHaveBeenCalled();
  expect(onResumeLive).not.toHaveBeenCalled();
});
