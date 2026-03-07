import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import { deriveRecommendedMoves } from '@/shared/lib/sessionRecommendations';
import { cn } from '@/shared/lib/cn';
import { useSessionStore } from '@/shared/store/sessionStore';
import type { ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Field } from '@/shared/ui/Field';
import { Panel } from '@/shared/ui/Panel';
import { Pill } from '@/shared/ui/Pill';

type RiskTone = 'low' | 'medium' | 'high';
type MobileView = 'now' | 'history';

function normalizeRisk(value: string): RiskTone {
  const lower = value.toLowerCase();
  if (lower.includes('low')) return 'low';
  if (lower.includes('high')) return 'high';
  return 'medium';
}

function summarizeRiskHint(value: string) {
  const lower = value.toLowerCase();
  if (lower.includes('low')) return 'Low Risk';
  if (lower.includes('high')) return 'High Risk';
  if (lower.includes('medium')) return 'Medium Risk';
  if (lower.includes('fast but dirty')) return 'Fast / Risky';
  if (lower.includes('steady but slow')) return 'Steady';
  if (lower.includes('politically safe')) return 'Safe / Costly';
  return 'Suggested';
}

export function PlaySessionPage() {
  const { sessionId = '' } = useParams();
  const navigate = useNavigate();
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const [textInput, setTextInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [errorContext, setErrorContext] = useState<ErrorPresentationContext>('play-session-load');
  const [mobileView, setMobileView] = useState<MobileView>('now');
  const { sessionMeta, history, submitting, setSessionMeta, setHistoryResponse, setSubmitting, reset } = useSessionStore();

  async function loadSession() {
    if (!sessionId) {
      navigate('/play/library');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [meta, historyResponse] = await Promise.all([
        apiService.getSession(sessionId),
        apiService.getSessionHistory(sessionId),
      ]);
      setSessionMeta(meta);
      setHistoryResponse(historyResponse);
    } catch (caught) {
      setErrorContext('play-session-load');
      setError(caught as ApiClientError | Error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reset();
    setMobileView('now');
    void loadSession();
  }, [sessionId]);

  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTo({ top: timelineRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [history.length]);

  const latestTurn = useMemo(() => history[history.length - 1] ?? null, [history]);
  const latestActions = latestTurn?.ui.moves ?? [];
  const recommendedMoves = useMemo(() => deriveRecommendedMoves(latestActions, 3), [latestActions]);
  const hiddenActionCount = Math.max(0, latestActions.length - recommendedMoves.length);
  const isComplete = Boolean(sessionMeta?.ended || latestTurn?.ended);

  async function submitButton(moveId: string) {
    if (!sessionId) return;
    setSubmitting(true);
    setError(null);
    setMobileView('now');
    try {
      await apiService.stepSession(sessionId, {
        client_action_id: `btn-${Date.now()}`,
        input: { type: 'button', move_id: moveId },
        dev_mode: false,
      });
      await loadSession();
    } catch (caught) {
      setErrorContext('play-session-step');
      setError(caught as ApiClientError | Error);
    } finally {
      setSubmitting(false);
    }
  }

  async function submitText(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = textInput.trim();
    if (!trimmed || !sessionId) return;
    setSubmitting(true);
    setError(null);
    setMobileView('now');
    try {
      await apiService.stepSession(sessionId, {
        client_action_id: `txt-${Date.now()}`,
        input: { type: 'text', text: trimmed },
        dev_mode: false,
      });
      setTextInput('');
      await loadSession();
    } catch (caught) {
      setErrorContext('play-session-step');
      setError(caught as ApiClientError | Error);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="xl:hidden">
        <div className="flex flex-wrap gap-2">
          {(['now', 'history'] as MobileView[]).map((view) => (
            <button
              key={view}
              type="button"
              onClick={() => setMobileView(view)}
              className={cn(
                'rounded-full px-4 py-2 text-sm font-semibold transition',
                mobileView === view
                  ? 'bg-[linear-gradient(135deg,rgba(239,126,69,0.26),rgba(245,179,111,0.14))] text-[var(--text-ivory)]'
                  : 'border border-[var(--line)] bg-[rgba(255,248,229,0.04)] text-[var(--text-dim)] hover:text-[var(--text-ivory)]',
              )}
            >
              {view === 'now' ? 'Now' : 'History'}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.08fr_0.92fr] xl:items-start">
        <div className={cn(mobileView === 'history' ? 'block' : 'hidden', 'xl:block')}>
          <Panel
            eyebrow="Play Runtime"
            title={sessionMeta ? `Session ${sessionMeta.session_id.slice(0, 8)}` : 'Loading session'}
            subtitle="History remains fully available, but mobile now defaults to the live control surface so you can act without scrolling past the transcript."
            className="min-h-[48vh] xl:min-h-[72vh]"
          >
            <ErrorBanner error={error} context={errorContext} />
            <div ref={timelineRef} className="custom-scrollbar mt-4 max-h-[62vh] space-y-4 overflow-y-auto pr-2">
              {loading ? (
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
                  Rebuilding runtime history...
                </div>
              ) : history.length === 0 ? (
                <EmptyState
                  title="Session ready to ignite"
                  body="No turns yet. Kick off the first step from the control surface."
                />
              ) : (
                history.map((turn) => (
                  <article key={turn.turn_index} className="rounded-[26px] border border-[var(--line)] bg-[linear-gradient(180deg,rgba(255,248,229,0.07),rgba(255,248,229,0.03))] p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Turn {turn.turn_index}</p>
                        <h3 className="mt-2 break-words font-[var(--font-title)] text-lg tracking-[0.05em] text-[var(--text-ivory)]">
                          {turn.recognized.interpreted_intent}
                        </h3>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Pill tone={turn.ended ? 'neutral' : 'success'}>{turn.ended ? 'Ended' : 'Active'}</Pill>
                        <Pill tone="neutral">{turn.recognized.route_source}</Pill>
                      </div>
                    </div>
                    <p className="mt-5 whitespace-pre-wrap break-words text-base leading-8 text-[var(--text-ivory)]">{turn.narration_text}</p>
                    <div className="mt-5 grid gap-3 md:grid-cols-2">
                      <div className="rounded-[20px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] p-4">
                        <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Resolution</div>
                        <div className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{turn.resolution.result}</div>
                      </div>
                      <div className="rounded-[20px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] p-4">
                        <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Scene</div>
                        <div className="mt-2 break-all text-sm leading-7 text-[var(--text-mist)]">{turn.scene_id}</div>
                      </div>
                    </div>
                  </article>
                ))
              )}
            </div>
          </Panel>
        </div>

        <div className={cn(mobileView === 'now' ? 'block' : 'hidden', 'xl:block xl:sticky xl:top-4')}>
          <Panel
            eyebrow="Recommended Follow-ups"
            title={isComplete ? 'Session sealed' : 'Drive the next turn'}
            subtitle={isComplete ? 'This session has ended.' : 'Free input is the primary control. Suggested moves are intentionally limited to the top recommendations.'}
          >
            {sessionMeta ? <Pill tone={sessionMeta.ended ? 'neutral' : 'success'}>{sessionMeta.ended ? 'Completed' : 'Active'}</Pill> : null}

            <div className="mt-5 space-y-5">
              {latestTurn ? (
                <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Current Turn State</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Pill tone="neutral">Scene {latestTurn.scene_id}</Pill>
                    <Pill tone={latestTurn.ended ? 'neutral' : 'success'}>{latestTurn.resolution.result}</Pill>
                    <Pill tone="neutral">{latestTurn.recognized.route_source}</Pill>
                  </div>
                </div>
              ) : null}

              <form className="space-y-4" onSubmit={(event) => void submitText(event)}>
                <Field
                  label="Free Text Directive"
                  multiline
                  placeholder="Describe what the player attempts next..."
                  value={textInput}
                  onChange={(event) => setTextInput(event.target.value)}
                  hint={latestTurn?.ui.input_hint ?? 'Free input is the fastest way to steer the story, ask for nuance, or try tactics outside the recommended list.'}
                />
                <div className="flex flex-wrap gap-3">
                  <Button type="submit" disabled={submitting || isComplete || !textInput.trim()}>
                    {submitting ? 'Sending...' : 'Send Directive'}
                  </Button>
                  <Button variant="secondary" type="button" onClick={() => navigate('/play/library')}>
                    Back to Play Library
                  </Button>
                </div>
              </form>

              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Suggested Moves</div>
                    <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">
                      {hiddenActionCount > 0
                        ? `Showing ${recommendedMoves.length} suggested moves. ${hiddenActionCount} additional surfaced actions are intentionally hidden so free input stays primary.`
                        : 'Only the top suggested moves are shown here. Use free input for everything else.'}
                    </p>
                  </div>
                </div>

                {recommendedMoves.length > 0 ? (
                  <div className="space-y-3">
                    {recommendedMoves.map((move) => (
                      <button
                        key={move.move_id}
                        type="button"
                        onClick={() => void submitButton(move.move_id)}
                        disabled={submitting || isComplete}
                        className="w-full rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4 text-left transition hover:border-[rgba(239,126,69,0.36)] hover:bg-[rgba(239,126,69,0.08)] disabled:cursor-not-allowed disabled:opacity-45"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="break-words font-[var(--font-title)] text-lg tracking-[0.05em] text-[var(--text-ivory)]">{move.label}</div>
                            <div className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{move.risk_hint}</div>
                          </div>
                          <Pill tone={normalizeRisk(move.risk_hint)}>{summarizeRiskHint(move.risk_hint)}</Pill>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[22px] border border-dashed border-[var(--line)] px-4 py-5 text-sm text-[var(--text-dim)]">
                    No recommended buttons yet. Use free text to begin or continue the session.
                  </div>
                )}
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
