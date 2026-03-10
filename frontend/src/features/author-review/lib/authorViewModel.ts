import type { AuthorRunGetResponse, AuthorRunStatus, AuthorStoryGetResponse, AuthorStoryListItem } from '@/shared/api/types';

export function authorRunStatusLabel(status: AuthorRunStatus | string | null | undefined) {
  if (status === 'failed') return 'Run failed';
  if (status === 'review_ready') return 'Review ready';
  if (status === 'running') return 'Graph running';
  if (status === 'pending') return 'Queued';
  return 'No run';
}

export function authorRunTone(status: AuthorRunStatus | string | null | undefined) {
  if (status === 'failed') return 'high' as const;
  if (status === 'review_ready') return 'success' as const;
  if (status === 'pending' || status === 'running') return 'medium' as const;
  return 'neutral' as const;
}

export function shouldUseRunShell(status: AuthorRunStatus | string | null | undefined) {
  return status === 'pending' || status === 'running' || status === 'failed';
}

export function storyIndexSummary(story: { latest_run_status: string | null; latest_run_current_node: string | null; latest_published_version: number | null }) {
  if (story.latest_published_version !== null) {
    return `Published for Play as version ${story.latest_published_version}.`;
  }
  if (story.latest_run_status === 'failed') {
    return `Workflow stopped${story.latest_run_current_node ? ` at ${story.latest_run_current_node}` : ''}. Re-run before review or publish.`;
  }
  if (story.latest_run_status === 'review_ready') {
    return 'Draft is review-ready and waiting for publish.';
  }
  if (story.latest_run_status === 'pending' || story.latest_run_status === 'running') {
    return `Author workflow still running${story.latest_run_current_node ? ` at ${story.latest_run_current_node}` : ''}.`;
  }
  return 'Draft shell exists, but no completed author run is attached yet.';
}

export function authorStoryCardClasses(status: AuthorRunStatus | string | null | undefined) {
  if (status === 'failed') {
    return 'border-[rgba(239,126,69,0.28)] bg-[rgba(239,126,69,0.08)] hover:border-[rgba(239,126,69,0.45)] hover:bg-[rgba(239,126,69,0.12)]';
  }
  if (status === 'review_ready') {
    return 'border-[rgba(120,192,156,0.24)] bg-[rgba(120,192,156,0.07)] hover:border-[rgba(120,192,156,0.4)] hover:bg-[rgba(120,192,156,0.1)]';
  }
  return 'border-[var(--line)] bg-[rgba(255,248,229,0.05)] hover:border-[var(--line-strong)] hover:bg-[rgba(255,248,229,0.08)]';
}

export function authorStoryTarget(story: Pick<AuthorStoryListItem, 'story_id' | 'latest_run_id' | 'latest_run_status'> | Pick<AuthorStoryGetResponse, 'story_id' | 'latest_run'>) {
  const runId = 'latest_run_id' in story ? story.latest_run_id : story.latest_run?.run_id ?? null;
  const status = 'latest_run_status' in story ? story.latest_run_status : story.latest_run?.status ?? null;
  if (runId && shouldUseRunShell(status)) {
    return `/author/runs/${runId}`;
  }
  return `/author/stories/${story.story_id}/review`;
}

export function authorRunShellTitle(run: AuthorRunGetResponse) {
  if (run.status === 'failed') return 'Run diagnostics';
  if (run.status === 'review_ready') return 'Run completed';
  if (run.status === 'running') return 'Author workflow running';
  if (run.status === 'pending') return 'Run queued';
  return 'Workflow run';
}

export function authorRunShellSubtitle(run: AuthorRunGetResponse) {
  if (run.status === 'failed') {
    return `The workflow failed${run.current_node ? ` at ${run.current_node}` : ''}. Review artifacts and rerun from the brief when ready.`;
  }
  if (run.status === 'review_ready') {
    return 'This run reached review_ready. Open the review workspace to inspect and publish the draft.';
  }
  if (run.status === 'running') {
    return `The workflow is still executing${run.current_node ? ` at ${run.current_node}` : ''}. Watch node progress and artifacts below.`;
  }
  if (run.status === 'pending') {
    return 'This run is queued and waiting for the workflow to start.';
  }
  return 'Inspect the latest author workflow state.';
}
