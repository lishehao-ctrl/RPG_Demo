import { describe, expect, it } from 'vitest';

import { parseArgs, summarizeCases } from './author_play_release_gate.mjs';

describe('author_play_release_gate', () => {
  it('parseArgs keeps defaults and toggles headed', () => {
    const args = parseArgs(['node', 'script', '--headed']);
    expect(args.headed).toBe(true);
    expect(args.baseUrl).toBe('http://127.0.0.1:8173');
    expect(String(args.suiteFile)).toContain('eval_data');
  });

  it('summarizeCases reports partial when mixed', () => {
    const summary = summarizeCases([
      { status: 'passed' },
      { status: 'failed' },
    ]);
    expect(summary.status).toBe('partial');
    expect(summary.case_count).toBe(2);
    expect(summary.passed_case_count).toBe(1);
    expect(summary.failed_case_count).toBe(1);
  });
});
