import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import { useAuthorStoryStore } from '@/shared/store/authorStoryStore';
import type { ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Field } from '@/shared/ui/Field';
import { Panel } from '@/shared/ui/Panel';
import { Pill } from '@/shared/ui/Pill';
import { formatDateTime } from '@/shared/lib/format';

export function AuthorStoriesPage() {
  const navigate = useNavigate();
  const { stories, setStories } = useAuthorStoryStore();
  const [promptText, setPromptText] = useState('Design a political fantasy thriller about a forest city under ritual siege.');
  const [seedText, setSeedText] = useState('');
  const [style, setStyle] = useState('tense, cinematic, strategic');
  const [targetMinutes, setTargetMinutes] = useState(10);
  const [npcCount, setNpcCount] = useState(4);
  const [loadingStories, setLoadingStories] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [errorContext, setErrorContext] = useState<ErrorPresentationContext>('author-stories-load');

  async function loadStories() {
    setLoadingStories(true);
    try {
      const response = await apiService.listStories();
      setStories(response.stories);
    } catch (caught) {
      setErrorContext('author-stories-load');
      setError(caught as ApiClientError | Error);
    } finally {
      setLoadingStories(false);
    }
  }

  useEffect(() => {
    void loadStories();
  }, []);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      const response = await apiService.generateStory({
        prompt_text: promptText.trim() || undefined,
        seed_text: seedText.trim() || undefined,
        target_minutes: targetMinutes,
        npc_count: npcCount,
        style: style.trim() || undefined,
        publish: false,
      });
      await loadStories();
      navigate(`/author/stories/${response.story_id}`);
    } catch (caught) {
      setErrorContext('author-generate');
      setError(caught as ApiClientError | Error);
    } finally {
      setGenerating(false);
    }
  }

  const publishedCount = useMemo(
    () => stories.filter((story) => story.latest_published_version !== null).length,
    [stories],
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
      <Panel
        eyebrow="Author Flow"
        title="Forge a new story draft"
        subtitle="Generate a DB-backed story draft with the real LLM pipeline, then publish it when it looks ready."
      >
        <div className="space-y-5">
          <Field
            label="Prompt Brief"
            multiline
            value={promptText}
            onChange={(event) => setPromptText(event.target.value)}
            hint="Preferred path for author generation. If prompt is blank, seed text can drive generation instead."
          />
          <Field
            label="Seed Text"
            value={seedText}
            onChange={(event) => setSeedText(event.target.value)}
            hint="Optional. Use when you want a simpler seed-driven generation path."
          />
          <div className="grid gap-4 md:grid-cols-2">
            <Field
              label="Style"
              value={style}
              onChange={(event) => setStyle(event.target.value)}
            />
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Minutes"
                type="number"
                min={8}
                max={12}
                value={String(targetMinutes)}
                onChange={(event) => setTargetMinutes(Number(event.target.value))}
              />
              <Field
                label="NPC Count"
                type="number"
                min={3}
                max={5}
                value={String(npcCount)}
                onChange={(event) => setNpcCount(Number(event.target.value))}
              />
            </div>
          </div>

          <ErrorBanner error={error} context={errorContext} />

          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleGenerate} disabled={generating || (!promptText.trim() && !seedText.trim())}>
              {generating ? 'Generating Draft...' : 'Generate Draft'}
            </Button>
            <Button variant="secondary" onClick={() => void loadStories()} disabled={loadingStories}>
              Refresh Story Index
            </Button>
          </div>
        </div>
      </Panel>

      <Panel
        eyebrow="Story Index"
        title="Drafts and published versions"
        subtitle="Author mode tracks story supply. Drafts stay here until you explicitly publish them for Play."
      >
        <div className="mb-5 flex flex-wrap gap-2">
          <Pill tone="neutral">{stories.length.toString().padStart(2, '0')} total</Pill>
          <Pill tone="success">{publishedCount.toString().padStart(2, '0')} published</Pill>
        </div>

        {loadingStories ? (
          <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
            Reading story index...
          </div>
        ) : stories.length === 0 ? (
          <EmptyState
            title="No drafts in the forge"
            body="Generate your first story draft from the left panel. Published stories will later feed the Play library."
          />
        ) : (
          <div className="space-y-4">
            {stories.map((story) => (
              <article
                key={story.story_id}
                className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5"
              >
                <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-[var(--text-dim)]">Created {formatDateTime(story.created_at)}</p>
                    <h3 className="mt-2 font-[var(--font-title)] text-xl tracking-[0.06em] text-[var(--text-ivory)]">
                      {story.title}
                    </h3>
                    <p className="mt-2 break-all text-sm leading-6 text-[var(--text-dim)]">{story.story_id}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill tone={story.has_draft ? 'medium' : 'neutral'}>{story.has_draft ? 'Draft Ready' : 'No Draft'}</Pill>
                    {story.latest_published_version !== null ? (
                      <Pill tone="success">Published v{story.latest_published_version}</Pill>
                    ) : (
                      <Pill tone="neutral">Unpublished</Pill>
                    )}
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap gap-3">
                  <Button variant="secondary" onClick={() => navigate(`/author/stories/${story.story_id}`)}>
                    Open Detail
                  </Button>
                  {story.latest_published_version !== null ? (
                    <Button variant="secondary" onClick={() => navigate('/play/library')}>
                      Open Play Library
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
