import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import { BenchmarksView } from '../app/components/views';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderBenchmarks(role: 'viewer' | 'editor' | 'admin') {
  const onCreate = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
  render(
    <BenchmarksView
      runs={[]}
      selectedRun={null}
      cases={[]}
      form={{ provider: 'openai', model: 'gpt-4o', max_cases: 10 }}
      busy={false}
      role={role}
      detailLoading={false}
      onForm={vi.fn()}
      onCreate={onCreate}
      onRun={vi.fn()}
      onResume={vi.fn()}
      onCancel={vi.fn()}
      onExport={vi.fn()}
    />,
  );
  return { onCreate };
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
