import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import type { ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';
import { useAuthorStoryStore } from '@/features/author-review/store/authorStoryStore';
import {
  applyEditableStoryDraft,
  buildEditableStoryDraftState,
  buildStoryDraftPatchChanges,
  hasEditableStoryDraftChanges,
  type EditableStoryDraftState,
} from '@/features/author-review/lib/storyDraftEditing';
import { buildStoryPackReviewModel, type ReviewIssue, type StoryPackBeat, type StoryPackMove, type StoryPackScene } from '@/features/author-review/lib/storyPackReview';
import { isAuthorRunReviewReady } from '@/features/author-review/lib/authorStatus';
import { authorStoryTarget } from '@/features/author-review/lib/authorViewModel';
import { cn } from '@/shared/lib/cn';
import { formatDateTime, titleCase } from '@/shared/lib/format';
import { Button } from '@/shared/ui/Button';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Field } from '@/shared/ui/Field';
import { Panel } from '@/shared/ui/Panel';
import { Pill } from '@/shared/ui/Pill';

type ReviewTab = 'overview' | 'cast' | 'beats' | 'scenes' | 'moves' | 'raw';

function matchesSearch(query: string, ...parts: Array<string | string[] | null | undefined>) {
  if (!query) return true;
  const haystack = parts
    .flatMap((part) => (Array.isArray(part) ? part : [part ?? '']))
    .join(' ')
    .toLowerCase();
  return haystack.includes(query);
}

function issueTone(severity: ReviewIssue['severity']) {
  if (severity === 'blocking') return 'high';
  if (severity === 'warning') return 'medium';
  return 'success';
}

function tabForIssue(issue: ReviewIssue): ReviewTab {
  if (issue.target_type === 'beat') return 'beats';
  if (issue.target_type === 'scene') return 'scenes';
  if (issue.target_type === 'move') return 'moves';
  return 'overview';
}

function MiniActionButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-[var(--line)] px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-[var(--text-mist)] transition hover:border-[var(--line-strong)] hover:text-[var(--text-ivory)]"
    >
      {label}
    </button>
  );
}

function DetailsCard({
  title,
  subtitle,
  actions,
  children,
  defaultOpen = false,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details open={defaultOpen} className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-4">
      <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="break-words font-[var(--font-title)] text-lg tracking-[0.04em] text-[var(--text-ivory)]">{title}</div>
          {subtitle ? <div className="mt-1 break-words text-sm text-[var(--text-dim)]">{subtitle}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </summary>
      <div className="mt-4 space-y-4">{children}</div>
    </details>
  );
}

function buildEditableStateFromResponse(response: { draft_pack: Record<string, unknown> }): EditableStoryDraftState {
  return buildEditableStoryDraftState(buildStoryPackReviewModel(response.draft_pack as Record<string, unknown>));
}

export function AuthorStoryReviewPage() {
  const { storyId = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { currentStory, setCurrentStory } = useAuthorStoryStore();
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [errorContext, setErrorContext] = useState<ErrorPresentationContext>('author-draft-load');
  const [activeTab, setActiveTab] = useState<ReviewTab>('overview');
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedLabel, setCopiedLabel] = useState<string | null>(null);
  const [editableDraft, setEditableDraft] = useState<EditableStoryDraftState | null>(null);

  async function loadStory() {
    if (!storyId) {
      navigate('/author/stories');
      return;
    }
    setLoading(true);
    try {
      const response = await apiService.getAuthorStory(storyId);
      setCurrentStory(response);
    } catch (caught) {
      setErrorContext('author-draft-load');
      setError(caught as ApiClientError | Error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStory();
  }, [storyId]);


  const originalReviewModel = useMemo(
    () => buildStoryPackReviewModel((currentStory?.draft_pack ?? {}) as Record<string, unknown>),
    [currentStory],
  );

  useEffect(() => {
    if (currentStory) {
      setEditableDraft(buildEditableStateFromResponse(currentStory));
    } else {
      setEditableDraft(null);
    }
  }, [currentStory]);

  useEffect(() => {
    if (!currentStory) return;
    const target = authorStoryTarget(currentStory);
    if (target !== location.pathname) {
      navigate(target, { replace: true });
    }
  }, [currentStory, location.pathname, navigate]);

  const editableDraftPack = useMemo(() => {
    if (!currentStory || !editableDraft) {
      return (currentStory?.draft_pack ?? {}) as Record<string, unknown>;
    }
    return applyEditableStoryDraft(currentStory.draft_pack as Record<string, unknown>, editableDraft);
  }, [currentStory, editableDraft]);

  const reviewModel = useMemo(() => buildStoryPackReviewModel(editableDraftPack), [editableDraftPack]);

  const isDirty = useMemo(
    () => (editableDraft ? hasEditableStoryDraftChanges(originalReviewModel, editableDraft) : false),
    [editableDraft, originalReviewModel],
  );
  const latestRun = currentStory?.latest_run ?? null;
  const latestRunStatus = latestRun?.status ?? null;
  const isReviewReady = isAuthorRunReviewReady(latestRunStatus);
  const canPublish = !publishing && !saving && !isDirty && (!latestRun || isReviewReady);


  async function handlePublish() {
    if (!storyId) {
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      await apiService.publishStory(storyId);
      await loadStory();
    } catch (caught) {
      setErrorContext('author-publish');
      setError(caught as ApiClientError | Error);
    } finally {
      setPublishing(false);
    }
  }

  async function handleSaveDraftChanges() {
    if (!storyId || !currentStory || !editableDraft) {
      return;
    }
    const changes = buildStoryDraftPatchChanges(originalReviewModel, editableDraft);
    if (changes.length === 0) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await apiService.patchStoryDraft(storyId, { changes });
      setEditableDraft(buildEditableStateFromResponse(response));
      await loadStory();
    } catch (caught) {
      setErrorContext('author-draft-save');
      setError(caught as ApiClientError | Error);
    } finally {
      setSaving(false);
    }
  }

  function handleDiscardChanges() {
    if (!currentStory) {
      return;
    }
    setEditableDraft(buildEditableStateFromResponse(currentStory));
  }

  async function copyText(label: string, value: string) {
    if (!value || typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }
    await navigator.clipboard.writeText(value);
    setCopiedLabel(label);
    window.setTimeout(() => setCopiedLabel((current) => (current === label ? null : current)), 1400);
  }

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredBeats = useMemo(
    () => reviewModel.beats.filter((beat) => matchesSearch(normalizedQuery, beat.id, beat.title, beat.entrySceneId, beat.requiredEvents)),
    [reviewModel.beats, normalizedQuery],
  );
  const filteredScenes = useMemo(
    () =>
      reviewModel.scenes.filter((scene) =>
        matchesSearch(
          normalizedQuery,
          scene.id,
          scene.beatId,
          scene.sceneSeed,
          scene.presentNpcs,
          scene.enabledMoves,
          scene.alwaysAvailableMoves,
          scene.exitConditions.flatMap((condition) => [condition.id, condition.key, condition.value, condition.nextSceneId]),
        ),
      ),
    [reviewModel.scenes, normalizedQuery],
  );
  const filteredMoves = useMemo(
    () => reviewModel.moves.filter((move) => matchesSearch(normalizedQuery, move.id, move.label, move.strategyStyle, move.intents, move.outcomes.map((outcome) => outcome.result))),
    [reviewModel.moves, normalizedQuery],
  );
  const filteredCast = useMemo(
    () => reviewModel.cast.filter((member) => matchesSearch(normalizedQuery, member.name, member.redLine, member.conflictTags)),
    [reviewModel.cast, normalizedQuery],
  );

  const groupedIssues = useMemo(
    () => ({
      blocking: reviewModel.issues.filter((issue) => issue.severity === 'blocking'),
      warning: reviewModel.issues.filter((issue) => issue.severity === 'warning'),
      info: reviewModel.issues.filter((issue) => issue.severity === 'info'),
    }),
    [reviewModel.issues],
  );

  const tabItems: Array<{ id: ReviewTab; label: string }> = [
    { id: 'overview', label: 'Overview' },
    { id: 'cast', label: 'Cast' },
    { id: 'beats', label: 'Beats' },
    { id: 'scenes', label: 'Scenes' },
    { id: 'moves', label: 'Moves' },
    { id: 'raw', label: 'Raw Payload' },
  ];

  const renderBeatCard = (beat: StoryPackBeat) => (
    <DetailsCard
      key={beat.id}
      title={beat.id || 'Unknown Beat'}
      subtitle={`Entry ${beat.entrySceneId || 'unknown'} • Step budget ${beat.stepBudget ?? '—'}`}
      actions={<MiniActionButton label={copiedLabel === `beat-${beat.id}` ? 'Copied' : 'Copy ID'} onClick={() => void copyText(`beat-${beat.id}`, beat.id)} />}
      defaultOpen
    >
      <Field
        label="Beat Title"
        value={editableDraft?.beats[beat.id]?.title ?? beat.title}
        onChange={(event) =>
          setEditableDraft((current) =>
            current
              ? {
                  ...current,
                  beats: {
                    ...current.beats,
                    [beat.id]: { title: event.target.value },
                  },
                }
              : current,
          )
        }
      />
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">NPC Quota</div>
          <div className="mt-2 text-sm text-[var(--text-ivory)]">{beat.npcQuota ?? '—'}</div>
        </div>
        <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Required Events</div>
          <div className="mt-2 break-words text-sm text-[var(--text-ivory)]">{beat.requiredEvents.length ? beat.requiredEvents.join(', ') : 'None'}</div>
        </div>
      </div>
    </DetailsCard>
  );

  const renderSceneCard = (scene: StoryPackScene) => (
    <DetailsCard
      key={scene.id}
      title={scene.id || 'Unknown Scene'}
      subtitle={`Beat ${scene.beatId || 'unknown'} • ${scene.presentNpcs.length} active NPCs • ${scene.exitConditions.length} exits`}
      actions={
        <>
          <MiniActionButton label={copiedLabel === `scene-${scene.id}` ? 'Copied' : 'Copy ID'} onClick={() => void copyText(`scene-${scene.id}`, scene.id)} />
          <MiniActionButton label={copiedLabel === `scene-path-${scene.id}` ? 'Copied' : 'Copy JSON Path'} onClick={() => void copyText(`scene-path-${scene.id}`, `$.scenes[?(@.id==\"${scene.id}\")]`)} />
        </>
      }
    >
      <Field
        label="Scene Seed"
        multiline
        value={editableDraft?.scenes[scene.id]?.scene_seed ?? scene.sceneSeed}
        onChange={(event) =>
          setEditableDraft((current) =>
            current
              ? {
                  ...current,
                  scenes: {
                    ...current.scenes,
                    [scene.id]: { scene_seed: event.target.value },
                  },
                }
              : current,
          )
        }
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4">
          <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Present NPCs</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {scene.presentNpcs.length ? scene.presentNpcs.map((npc) => <Pill key={npc} tone="neutral">{npc}</Pill>) : <span className="text-sm text-[var(--text-dim)]">None</span>}
          </div>
        </div>
        <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4">
          <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Always Available Moves</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {scene.alwaysAvailableMoves.length ? scene.alwaysAvailableMoves.map((moveId) => <Pill key={moveId} tone="low">{moveId}</Pill>) : <span className="text-sm text-[var(--text-dim)]">None</span>}
          </div>
        </div>
      </div>

      <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4">
        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Enabled Moves</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {scene.enabledMoves.length ? scene.enabledMoves.map((moveId) => <Pill key={moveId} tone="medium">{moveId}</Pill>) : <span className="text-sm text-[var(--text-dim)]">No enabled moves</span>}
        </div>
      </div>

      <div className="space-y-3">
        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Exit Conditions</div>
        {scene.exitConditions.length ? (
          scene.exitConditions.map((condition) => (
            <div key={condition.id || `${scene.id}-${condition.nextSceneId}`} className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4 text-sm text-[var(--text-mist)]">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone={condition.endStory ? 'neutral' : 'medium'}>{condition.conditionKind || 'always'}</Pill>
                {condition.nextSceneId ? <Pill tone="neutral">next {condition.nextSceneId}</Pill> : null}
                {condition.endStory ? <Pill tone="high">end_story</Pill> : null}
              </div>
              <p className="mt-3 break-words leading-7">
                {condition.id || 'Unnamed condition'}
                {condition.key ? ` • ${condition.key}` : ''}
                {condition.value ? ` = ${condition.value}` : ''}
              </p>
            </div>
          ))
        ) : (
          <div className="rounded-[18px] border border-dashed border-[var(--line)] px-4 py-4 text-sm text-[var(--text-dim)]">No exit conditions defined.</div>
        )}
      </div>
    </DetailsCard>
  );

  const renderMoveCard = (move: StoryPackMove) => (
    <DetailsCard
      key={move.id}
      title={move.label || move.id}
      subtitle={`${move.id || 'unknown'} • ${titleCase(move.strategyStyle || 'unknown')}`}
      actions={
        <>
          <MiniActionButton label={copiedLabel === `move-${move.id}` ? 'Copied' : 'Copy ID'} onClick={() => void copyText(`move-${move.id}`, move.id)} />
          <MiniActionButton label={copiedLabel === `move-path-${move.id}` ? 'Copied' : 'Copy JSON Path'} onClick={() => void copyText(`move-path-${move.id}`, `$.moves[?(@.id==\"${move.id}\")]`)} />
        </>
      }
    >
      <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4">
        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Intents</div>
        <p className="mt-3 break-words text-sm leading-7 text-[var(--text-mist)]">{move.intents.length ? move.intents.join(', ') : 'No intents declared.'}</p>
      </div>
      <div className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-4 py-4">
        <div className="text-xs uppercase tracking-[0.16em] text-[var(--text-dim)]">Outcomes</div>
        <div className="mt-3 flex flex-wrap gap-2">
          {move.outcomes.length ? move.outcomes.map((outcome) => <Pill key={outcome.id} tone="neutral">{outcome.result || outcome.id}</Pill>) : <span className="text-sm text-[var(--text-dim)]">No outcomes</span>}
        </div>
      </div>
    </DetailsCard>
  );

  return (
    <div className="space-y-4">
      <Panel
        eyebrow="Story Review"
        title={currentStory?.title ?? 'Loading draft'}
        subtitle={currentStory ? `Draft created ${formatDateTime(currentStory.created_at)}. Review the pack structure, make light edits, then publish the approved draft to Play Mode.` : 'Loading draft payload from the author API.'}
      >
        <ErrorBanner error={error} context={errorContext} />

        {loading || !currentStory || !editableDraft ? (
          <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
            Loading draft detail...
          </div>
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              <Pill tone="medium">Review Workspace</Pill>
              {latestRun ? <Pill tone={isReviewReady ? 'success' : 'neutral'}>{isReviewReady ? 'Run ready' : `Run ${latestRunStatus}`}</Pill> : null}
              {currentStory.latest_published_version !== null ? <Pill tone="success">Published v{currentStory.latest_published_version}</Pill> : <Pill tone="neutral">Unpublished</Pill>}
              <Pill tone="neutral">{reviewModel.counts.scenes} scenes</Pill>
              <Pill tone="neutral">{reviewModel.counts.moves} moves</Pill>
              <Pill tone="neutral">{reviewModel.counts.beats} beats</Pill>
              {isDirty ? <Pill tone="high">Unsaved Changes</Pill> : <Pill tone="success">Saved</Pill>}
            </div>

            {isDirty ? (
              <div className="rounded-[24px] border border-[rgba(245,179,111,0.24)] bg-[rgba(245,179,111,0.08)] p-4">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Draft changes pending</div>
                    <p className="mt-2 break-words text-sm leading-7 text-[var(--text-mist)]">
                      You have local edits in this review workspace. Save them explicitly before publish; leaving the page will discard unsaved changes.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-3">
                    <Button onClick={() => void handleSaveDraftChanges()} disabled={saving}>
                      {saving ? 'Saving...' : 'Save Draft Changes'}
                    </Button>
                    <Button variant="secondary" onClick={handleDiscardChanges} disabled={saving}>
                      Discard Changes
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}

            {latestRun ? (
              <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Latest workflow</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Pill tone={isReviewReady ? 'success' : 'neutral'}>{latestRunStatus ?? 'detached'}</Pill>
                  {latestRun.current_node ? <Pill tone="neutral">{latestRun.current_node}</Pill> : null}
                </div>
                <p className="mt-3 break-words text-sm leading-7 text-[var(--text-mist)]">
                  {latestRun.raw_brief || 'No raw brief recorded for this story.'}
                </p>
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-3">
              <div className={`rounded-[22px] border px-4 py-4 ${isReviewReady ? 'border-[rgba(120,192,156,0.24)] bg-[rgba(120,192,156,0.08)]' : 'border-[var(--line)] bg-[rgba(255,248,229,0.05)]'}`}>
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Run state</div>
                <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{latestRun ? (isReviewReady ? 'Ready' : titleCase(latestRunStatus || 'no linked run')) : 'No linked run'}</div>
                <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{latestRun?.current_node ? `Current node: ${latestRun.current_node}` : 'No workflow node is attached to this review shell.'}</p>
              </div>
              <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Publish state</div>
                <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{currentStory.latest_published_version !== null ? 'Published' : 'Pending'}</div>
                <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{currentStory.latest_published_version !== null ? `Version ${currentStory.latest_published_version} is live for Play.` : 'Publish becomes available once this review-ready draft is approved.'}</p>
              </div>
              <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Draft shape</div>
                <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{reviewModel.counts.beats} beats</div>
                <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">{reviewModel.counts.scenes} scenes · {reviewModel.counts.moves} moves · structured pack review</p>
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)]">
              <div className="min-w-0 space-y-4">
                <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Story ID</div>
                  <div className="mt-2 break-words text-sm leading-7 text-[var(--text-mist)]">{currentStory.story_id}</div>
                </div>
                <div className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Review posture</div>
                  <p className="mt-2 break-words text-sm leading-7 text-[var(--text-mist)]">
                    Structured review is the primary view. Only a small set of high-value string fields are editable here; raw JSON remains read-only.
                  </p>
                </div>
              </div>

              <div className="min-w-0 rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-4">
                <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Publish rail</div>
                <p className="mt-2 text-sm leading-7 text-[var(--text-mist)]">
                  {currentStory.latest_published_version !== null
                    ? 'This draft is already live for Play. Open the library to launch sessions, or keep reviewing before a future version publish.'
                    : isDirty
                      ? 'Save draft changes before publish so Play consumes the reviewed version.'
                      : 'Publish the currently saved draft when it is ready for Play.'}
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  {currentStory.latest_published_version === null ? (
                    <Button onClick={handlePublish} disabled={!canPublish}>
                      {publishing ? 'Publishing...' : 'Publish For Play'}
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={() => navigate('/play/library')}>
                      Open Play Library
                    </Button>
                  )}
                  <Button variant="ghost" onClick={() => navigate('/author/stories')}>
                    Back to Story Index
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </Panel>

      {!loading && currentStory && editableDraft ? (
        <Panel
          eyebrow="Review Signals"
          title="Structural review at a glance"
          subtitle="These are review findings derived from the locally edited draft. Blocking findings can exist while you work, but publish will still enforce the backend lint gate."
        >
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-[22px] border border-[rgba(239,126,69,0.3)] bg-[rgba(239,126,69,0.08)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Blocking</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{groupedIssues.blocking.length}</div>
            </div>
            <div className="rounded-[22px] border border-[rgba(245,179,111,0.24)] bg-[rgba(245,179,111,0.08)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Needs attention</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{groupedIssues.warning.length}</div>
            </div>
            <div className="rounded-[22px] border border-[rgba(120,192,156,0.24)] bg-[rgba(120,192,156,0.08)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Looks healthy</div>
              <div className="mt-2 font-[var(--font-title)] text-2xl text-[var(--text-ivory)]">{groupedIssues.info.length}</div>
            </div>
          </div>

          <div className="mt-5 grid gap-3 lg:grid-cols-2">
            {reviewModel.issues.map((issue) => (
              <button
                key={`${issue.severity}-${issue.target_type}-${issue.target_id}-${issue.title}`}
                type="button"
                onClick={() => {
                  setActiveTab(tabForIssue(issue));
                  if (issue.target_id && issue.target_id !== 'pack') {
                    setSearchQuery(issue.target_id);
                  }
                }}
                className="rounded-[22px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-4 text-left transition hover:border-[var(--line-strong)] hover:bg-[rgba(255,248,229,0.08)]"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Pill tone={issueTone(issue.severity)}>{issue.severity}</Pill>
                  <Pill tone="neutral">{issue.target_type}</Pill>
                </div>
                <div className="mt-3 break-words font-semibold text-[var(--text-ivory)]">{issue.title}</div>
                <p className="mt-2 break-words text-sm leading-7 text-[var(--text-mist)]">{issue.message}</p>
              </button>
            ))}
          </div>
        </Panel>
      ) : null}

      {!loading && currentStory && editableDraft ? (
        <Panel
          eyebrow="Review Workspace"
          title="Read the pack by structure, not by raw JSON"
          subtitle="Search within the current review tab, edit only the approved fields, and save explicitly when the draft looks ready."
        >
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              {tabItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setActiveTab(item.id)}
                  className={cn(
                    'rounded-full px-4 py-2 text-sm font-semibold transition',
                    activeTab === item.id
                      ? 'bg-[linear-gradient(135deg,rgba(239,126,69,0.26),rgba(245,179,111,0.14))] text-[var(--text-ivory)]'
                      : 'border border-[var(--line)] bg-[rgba(255,248,229,0.04)] text-[var(--text-dim)] hover:text-[var(--text-ivory)]',
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>

            <label className="block space-y-2">
              <span className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Section Search</span>
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search scene id, beat title, move label, NPC name..."
                className="w-full rounded-full border border-[var(--line)] bg-[rgba(255,248,229,0.05)] px-4 py-3 text-[var(--text-ivory)] outline-none transition placeholder:text-[var(--text-dim)] focus:border-[rgba(239,126,69,0.62)] focus:bg-[rgba(255,248,229,0.08)]"
              />
            </label>

            {activeTab === 'overview' ? (
              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
                  <Field
                    label="Title"
                    value={editableDraft.story.title}
                    onChange={(event) =>
                      setEditableDraft((current) =>
                        current
                          ? {
                              ...current,
                              story: { ...current.story, title: event.target.value },
                            }
                          : current,
                      )
                    }
                  />
                </div>
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
                  <Field
                    label="Input Hint"
                    multiline
                    value={editableDraft.story.input_hint}
                    onChange={(event) =>
                      setEditableDraft((current) =>
                        current
                          ? {
                              ...current,
                              story: { ...current.story, input_hint: event.target.value },
                            }
                          : current,
                      )
                    }
                  />
                </div>
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5 lg:col-span-2">
                  <Field
                    label="Description"
                    multiline
                    value={editableDraft.story.description}
                    onChange={(event) =>
                      setEditableDraft((current) =>
                        current
                          ? {
                              ...current,
                              story: { ...current.story, description: event.target.value },
                            }
                          : current,
                      )
                    }
                  />
                </div>
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
                  <Field
                    label="Style Guard"
                    multiline
                    value={editableDraft.story.style_guard}
                    onChange={(event) =>
                      setEditableDraft((current) =>
                        current
                          ? {
                              ...current,
                              story: { ...current.story, style_guard: event.target.value },
                            }
                          : current,
                      )
                    }
                  />
                </div>
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
                  <div className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Published Status</div>
                  <p className="mt-3 break-words text-sm leading-7 text-[var(--text-mist)]">
                    {currentStory.latest_published_version !== null
                      ? `Published version ${currentStory.latest_published_version}${currentStory.latest_published_at ? ` on ${formatDateTime(currentStory.latest_published_at)}` : ''}.`
                      : 'Draft only. Not published yet.'}
                  </p>
                </div>
                <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5 lg:col-span-2">
                  <div className="mb-4 text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Opening Guidance</div>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <div className="lg:col-span-2">
                      <Field
                        label="Opening Intro"
                        multiline
                        value={editableDraft.openingGuidance.intro_text}
                        onChange={(event) =>
                          setEditableDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  openingGuidance: { ...current.openingGuidance, intro_text: event.target.value },
                                }
                              : current,
                          )
                        }
                      />
                    </div>
                    <div className="lg:col-span-2">
                      <Field
                        label="Goal Hint"
                        multiline
                        value={editableDraft.openingGuidance.goal_hint}
                        onChange={(event) =>
                          setEditableDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  openingGuidance: { ...current.openingGuidance, goal_hint: event.target.value },
                                }
                              : current,
                          )
                        }
                      />
                    </div>
                    <Field
                      label="Observe Prompt"
                      multiline
                      value={editableDraft.openingGuidance.starter_prompt_1}
                      onChange={(event) =>
                        setEditableDraft((current) =>
                          current
                            ? {
                                ...current,
                                openingGuidance: { ...current.openingGuidance, starter_prompt_1: event.target.value },
                              }
                            : current,
                        )
                      }
                    />
                    <Field
                      label="Ask Prompt"
                      multiline
                      value={editableDraft.openingGuidance.starter_prompt_2}
                      onChange={(event) =>
                        setEditableDraft((current) =>
                          current
                            ? {
                                ...current,
                                openingGuidance: { ...current.openingGuidance, starter_prompt_2: event.target.value },
                              }
                            : current,
                        )
                      }
                    />
                    <div className="lg:col-span-2">
                      <Field
                        label="Act Prompt"
                        multiline
                        value={editableDraft.openingGuidance.starter_prompt_3}
                        onChange={(event) =>
                          setEditableDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  openingGuidance: { ...current.openingGuidance, starter_prompt_3: event.target.value },
                                }
                              : current,
                          )
                        }
                      />
                    </div>
                  </div>
                </div>
              </div>
            ) : null}

            {activeTab === 'cast' ? (
              filteredCast.length ? (
                <div className="grid gap-4 lg:grid-cols-2">
                  {filteredCast.map((member) => (
                    <div key={member.name} className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="break-words font-[var(--font-title)] text-xl text-[var(--text-ivory)]">{member.name}</h3>
                        <MiniActionButton label={copiedLabel === `cast-${member.name}` ? 'Copied' : 'Copy ID'} onClick={() => void copyText(`cast-${member.name}`, member.name)} />
                      </div>
                      <Field
                        label="Red Line"
                        multiline
                        value={editableDraft.npcs[member.name]?.red_line ?? member.redLine}
                        onChange={(event) =>
                          setEditableDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  npcs: {
                                    ...current.npcs,
                                    [member.name]: { red_line: event.target.value },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <div className="mt-4 text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Conflict Tags</div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {member.conflictTags.length ? member.conflictTags.map((tag) => <Pill key={tag} tone="neutral">{tag}</Pill>) : <span className="text-sm text-[var(--text-dim)]">No conflict tags</span>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-[24px] border border-dashed border-[var(--line)] px-5 py-6 text-sm text-[var(--text-dim)]">No cast members match the current search.</div>
              )
            ) : null}

            {activeTab === 'beats' ? (filteredBeats.length ? <div className="space-y-4">{filteredBeats.map(renderBeatCard)}</div> : <div className="rounded-[24px] border border-dashed border-[var(--line)] px-5 py-6 text-sm text-[var(--text-dim)]">No beats match the current search.</div>) : null}
            {activeTab === 'scenes' ? (filteredScenes.length ? <div className="space-y-4">{filteredScenes.map(renderSceneCard)}</div> : <div className="rounded-[24px] border border-dashed border-[var(--line)] px-5 py-6 text-sm text-[var(--text-dim)]">No scenes match the current search.</div>) : null}
            {activeTab === 'moves' ? (filteredMoves.length ? <div className="space-y-4">{filteredMoves.map(renderMoveCard)}</div> : <div className="rounded-[24px] border border-dashed border-[var(--line)] px-5 py-6 text-sm text-[var(--text-dim)]">No moves match the current search.</div>) : null}
            {activeTab === 'raw' ? (
              <pre className="custom-scrollbar max-h-[72vh] overflow-auto rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] p-4 text-xs leading-6 text-[var(--text-mist)]">
                {JSON.stringify(editableDraftPack, null, 2)}
              </pre>
            ) : null}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
