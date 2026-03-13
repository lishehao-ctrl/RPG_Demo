import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import type { ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';
import type { AuthorRunArtifactSummary, AuthorRunEventPayload, AuthorRunGetResponse } from '@/shared/api/types';
import { authorRunShellSubtitle, authorRunShellTitle, authorRunStatusLabel, authorRunTone, authorStoryTarget } from '@/features/author-review/lib/authorViewModel';
import { isAuthorRunReviewReady } from '@/features/author-review/lib/authorStatus';
import { formatDateTime } from '@/shared/lib/format';
import { Button } from '@/shared/ui/Button';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Panel } from '@/shared/ui/Panel';
import { Pill } from '@/shared/ui/Pill';

function safeJsonPreview(payload: Record<string, unknown>) {
  const text = JSON.stringify(payload, null, 2);
  return text.length > 1800 ? `${text.slice(0, 1800)}\n…` : text;
}

function ArtifactCard({ artifact }: { artifact: AuthorRunArtifactSummary }) {
  return (
    <details className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-4" open>
      <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">{artifact.artifact_type}</div>
          <div className="mt-2 text-sm font-semibold text-[var(--text-ivory)]">{artifact.artifact_key || 'artifact'}</div>
        </div>
        <div className="text-sm text-[var(--text-dim)]">Updated {formatDateTime(artifact.updated_at)}</div>
      </summary>
      <pre className="mt-4 overflow-x-auto rounded-[18px] border border-[var(--line)] bg-[rgba(6,8,16,0.42)] p-4 text-xs leading-6 text-[var(--text-mist)]">{safeJsonPreview(artifact.payload)}</pre>
    </details>
  );
}

function EventRow({ event }: { event: AuthorRunEventPayload }) {
  return (
    <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Pill tone="neutral">{event.node_name}</Pill>
          <Pill tone="neutral">{event.event_type}</Pill>
        </div>
        <div className="text-sm text-[var(--text-dim)]">{formatDateTime(event.created_at)}</div>
      </div>
      {Object.keys(event.payload ?? {}).length > 0 ? (
        <pre className="mt-3 overflow-x-auto rounded-[14px] border border-[var(--line)] bg-[rgba(6,8,16,0.32)] p-3 text-xs leading-6 text-[var(--text-mist)]">{safeJsonPreview(event.payload)}</pre>
      ) : null}
    </div>
  );
}

export function AuthorRunDetailPage() {
  const { runId = '' } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<AuthorRunGetResponse | null>(null);
  const [events, setEvents] = useState<AuthorRunEventPayload[]>([]);
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState(false);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [errorContext, setErrorContext] = useState<ErrorPresentationContext>('author-stories-load');

  async function load() {
    if (!runId) return;
    setLoading(true);
    setError(null);
    try {
      const [nextRun, nextEvents] = await Promise.all([
        apiService.getAuthorRun(runId),
        apiService.getAuthorRunEvents(runId),
      ]);
      setRun(nextRun);
      setEvents(nextEvents.events);
    } catch (caught) {
      setErrorContext('author-stories-load');
      setError(caught as ApiClientError | Error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [runId]);

  const orderedArtifacts = useMemo(() => [...(run?.artifacts ?? [])].sort((a, b) => a.updated_at.localeCompare(b.updated_at)), [run]);

  async function handleRerun() {
    if (!run) return;
    setRerunning(true);
    setError(null);
    try {
      const created = await apiService.rerunAuthorStory(run.story_id, { raw_brief: run.raw_brief });
      navigate(`/author/runs/${created.run_id}`);
    } catch (caught) {
      setErrorContext('author-generate');
      setError(caught as ApiClientError | Error);
    } finally {
      setRerunning(false);
    }
  }

  return (
    <Panel
      eyebrow="Run Detail"
      title={run ? authorRunShellTitle(run) : 'Loading author run'}
      subtitle={run ? authorRunShellSubtitle(run) : 'Loading workflow diagnostics and artifacts.'}
    >
      <ErrorBanner error={error} context={errorContext} />

      {loading || !run ? (
        <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
          Loading run detail...
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              <Pill tone={authorRunTone(run.status)}>{authorRunStatusLabel(run.status)}</Pill>
              {run.current_node ? <Pill tone="neutral">{run.current_node}</Pill> : null}
              {run.error_code ? <Pill tone="neutral">{run.error_code}</Pill> : null}
            </div>
            <div className="flex flex-wrap gap-3">
              {isAuthorRunReviewReady(run.status) ? (
                <Button onClick={() => navigate(authorStoryTarget({ story_id: run.story_id, latest_run: run }))}>Open Review Workspace</Button>
              ) : null}
              <Button variant="secondary" onClick={() => void load()} disabled={loading}>Refresh</Button>
              <Button variant="secondary" onClick={() => navigate('/author/stories')}>Back to Story Index</Button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Run state</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{authorRunStatusLabel(run.status)}</div>
              <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{run.current_node ? `Current node: ${run.current_node}` : 'No node recorded yet.'}</p>
            </div>
            <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Created</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{formatDateTime(run.created_at)}</div>
              <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">Updated {formatDateTime(run.updated_at)}</p>
            </div>
            <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Next action</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{isAuthorRunReviewReady(run.status) ? 'Review' : 'Rerun'}</div>
              <div className="mt-3">
                {isAuthorRunReviewReady(run.status) ? (
                  <Button onClick={() => navigate(authorStoryTarget({ story_id: run.story_id, latest_run: run }))}>Open Review Workspace</Button>
                ) : (
                  <Button onClick={() => void handleRerun()} disabled={rerunning}>{rerunning ? 'Starting...' : 'Re-run Author Workflow'}</Button>
                )}
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
            <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Raw Brief</div>
            <p className="mt-3 break-words text-sm leading-7 text-[var(--text-mist)]">{run.raw_brief}</p>
            {run.error_message ? (
              <div className="mt-4 rounded-[18px] border border-[rgba(239,126,69,0.28)] bg-[rgba(239,126,69,0.08)] p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Workflow error</div>
                <p className="mt-2 break-words text-sm leading-7 text-[var(--text-mist)]">{run.error_message}</p>
              </div>
            ) : null}
          </div>

          <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
            <div className="space-y-3">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Timeline</div>
              {events.length === 0 ? (
                <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-8 text-center text-[var(--text-mist)]">No run events recorded yet.</div>
              ) : (
                <div className="space-y-3">{events.map((event) => <EventRow key={event.event_id} event={event} />)}</div>
              )}
            </div>
            <div className="space-y-3">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Artifacts</div>
              {orderedArtifacts.length === 0 ? (
                <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-8 text-center text-[var(--text-mist)]">No artifacts recorded yet.</div>
              ) : (
                <div className="space-y-3">{orderedArtifacts.map((artifact) => <ArtifactCard key={`${artifact.artifact_type}:${artifact.artifact_key}:${artifact.updated_at}`} artifact={artifact} />)}</div>
              )}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}
