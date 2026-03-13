import type { AuthorRunGetResponse, AuthorRunStatus, AuthorStoryGetResponse, AuthorStoryListItem } from '@/shared/api/types';
import {
  AUTHOR_RUN_STATUS,
  isAuthorRunActive,
  isAuthorRunFailed,
  isAuthorRunPending,
  isAuthorRunReviewReady,
  isAuthorRunRunning,
  normalizeAuthorRunStatus,
  shouldUseAuthorRunShell,
} from '@/features/author-review/lib/authorStatus';

export function authorRunStatusLabel(status: AuthorRunStatus | string | null | undefined) {
  const normalized = normalizeAuthorRunStatus(status);
  if (normalized === AUTHOR_RUN_STATUS.FAILED) return 'Run failed';
  if (normalized === AUTHOR_RUN_STATUS.REVIEW_READY) return 'Review ready';
  if (normalized === AUTHOR_RUN_STATUS.RUNNING) return 'Graph running';
  if (normalized === AUTHOR_RUN_STATUS.PENDING) return 'Queued';
  return 'No run';
}

export function authorRunTone(status: AuthorRunStatus | string | null | undefined) {
  if (isAuthorRunFailed(status)) return 'high' as const;
  if (isAuthorRunReviewReady(status)) return 'success' as const;
  if (isAuthorRunActive(status)) return 'medium' as const;
  return 'neutral' as const;
}

export function shouldUseRunShell(status: AuthorRunStatus | string | null | undefined) {
  return shouldUseAuthorRunShell(status);
}

export function storyIndexSummary(story: { latest_run_status: string | null; latest_run_current_node: string | null; latest_published_version: number | null }) {
  if (story.latest_published_version !== null) {
    return `Published for Play as version ${story.latest_published_version}.`;
  }
  if (isAuthorRunFailed(story.latest_run_status)) {
    return `Workflow stopped${story.latest_run_current_node ? ` at ${story.latest_run_current_node}` : ''}. Re-run before review or publish.`;
  }
  if (isAuthorRunReviewReady(story.latest_run_status)) {
    return 'Draft is review-ready and waiting for publish.';
  }
  if (isAuthorRunActive(story.latest_run_status)) {
    return `Author workflow still running${story.latest_run_current_node ? ` at ${story.latest_run_current_node}` : ''}.`;
  }
  return 'No completed author run is attached yet. Start or rerun the workflow before review.';
}

export function authorStoryCardClasses(status: AuthorRunStatus | string | null | undefined) {
  if (isAuthorRunFailed(status)) {
    return 'border-[rgba(239,126,69,0.28)] bg-[rgba(239,126,69,0.08)] hover:border-[rgba(239,126,69,0.45)] hover:bg-[rgba(239,126,69,0.12)]';
  }
  if (isAuthorRunReviewReady(status)) {
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
  if (isAuthorRunFailed(run.status)) return 'Run diagnostics';
  if (isAuthorRunReviewReady(run.status)) return 'Run completed';
  if (isAuthorRunRunning(run.status)) return 'Author workflow running';
  if (isAuthorRunPending(run.status)) return 'Run queued';
  return 'Workflow run';
}

export function authorRunShellSubtitle(run: AuthorRunGetResponse) {
  if (isAuthorRunFailed(run.status)) {
    return `The workflow failed${run.current_node ? ` at ${run.current_node}` : ''}. Review artifacts and rerun from the brief when ready.`;
  }
  if (isAuthorRunReviewReady(run.status)) {
    return 'This run reached review-ready. Open the review workspace to inspect and publish the draft.';
  }
  if (isAuthorRunRunning(run.status)) {
    return `The workflow is still executing${run.current_node ? ` at ${run.current_node}` : ''}. Watch node progress and artifacts below.`;
  }
  if (isAuthorRunPending(run.status)) {
    return 'This run is queued and waiting for the workflow to start.';
  }
  return 'Inspect the latest author workflow state.';
}
