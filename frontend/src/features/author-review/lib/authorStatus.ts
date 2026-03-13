import type { AuthorRunStatus } from '@/shared/api/types';

export const AUTHOR_RUN_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  REVIEW_READY: 'review_ready',
  FAILED: 'failed',
} as const satisfies Record<string, AuthorRunStatus>;

export type AuthorRunStatusLike = AuthorRunStatus | string | null | undefined;

export function normalizeAuthorRunStatus(status: AuthorRunStatusLike): AuthorRunStatus | null {
  if (status === AUTHOR_RUN_STATUS.PENDING) return AUTHOR_RUN_STATUS.PENDING;
  if (status === AUTHOR_RUN_STATUS.RUNNING) return AUTHOR_RUN_STATUS.RUNNING;
  if (status === AUTHOR_RUN_STATUS.REVIEW_READY) return AUTHOR_RUN_STATUS.REVIEW_READY;
  if (status === AUTHOR_RUN_STATUS.FAILED) return AUTHOR_RUN_STATUS.FAILED;
  return null;
}

export function isAuthorRunPending(status: AuthorRunStatusLike) {
  return normalizeAuthorRunStatus(status) === AUTHOR_RUN_STATUS.PENDING;
}

export function isAuthorRunRunning(status: AuthorRunStatusLike) {
  return normalizeAuthorRunStatus(status) === AUTHOR_RUN_STATUS.RUNNING;
}

export function isAuthorRunReviewReady(status: AuthorRunStatusLike) {
  return normalizeAuthorRunStatus(status) === AUTHOR_RUN_STATUS.REVIEW_READY;
}

export function isAuthorRunFailed(status: AuthorRunStatusLike) {
  return normalizeAuthorRunStatus(status) === AUTHOR_RUN_STATUS.FAILED;
}

export function isAuthorRunActive(status: AuthorRunStatusLike) {
  return isAuthorRunPending(status) || isAuthorRunRunning(status);
}

export function shouldUseAuthorRunShell(status: AuthorRunStatusLike) {
  return isAuthorRunPending(status) || isAuthorRunRunning(status) || isAuthorRunFailed(status);
}
