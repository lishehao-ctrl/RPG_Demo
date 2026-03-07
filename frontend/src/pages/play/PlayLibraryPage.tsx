import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import { usePlayLibraryStore } from '@/shared/store/playLibraryStore';
import type { ErrorPresentationContext } from '@/shared/lib/apiErrorPresentation';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Panel } from '@/shared/ui/Panel';
import { Pill } from '@/shared/ui/Pill';
import { formatDateTime } from '@/shared/lib/format';

export function PlayLibraryPage() {
  const navigate = useNavigate();
  const { stories, setStories } = usePlayLibraryStore();
  const [loading, setLoading] = useState(true);
  const [creatingStoryId, setCreatingStoryId] = useState<string | null>(null);
  const [error, setError] = useState<ApiClientError | Error | null>(null);
  const [errorContext, setErrorContext] = useState<ErrorPresentationContext>('play-library-load');

  async function loadStories() {
    setLoading(true);
    try {
      const response = await apiService.listStories();
      setStories(response.stories.filter((story) => story.latest_published_version !== null));
    } catch (caught) {
      setErrorContext('play-library-load');
      setError(caught as ApiClientError | Error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStories();
  }, []);

  async function handleCreateSession(storyId: string, version: number) {
    setCreatingStoryId(storyId);
    setError(null);
    try {
      const response = await apiService.createSession({ story_id: storyId, version });
      navigate(`/play/sessions/${response.session_id}`);
    } catch (caught) {
      setErrorContext('play-create-session');
      setError(caught as ApiClientError | Error);
    } finally {
      setCreatingStoryId(null);
    }
  }

  const publishedCount = useMemo(() => stories.length, [stories.length]);

  return (
    <Panel
      eyebrow="Play Entry"
      title="Published story library"
      subtitle="Play mode only consumes published versions. Author drafts stay on the other rail until they are released."
    >
      <div className="mb-5 flex flex-wrap gap-2">
        <Pill tone="success">{publishedCount.toString().padStart(2, '0')} published</Pill>
      </div>

      <ErrorBanner error={error} context={errorContext} />

      {loading ? (
        <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
          Loading published stories...
        </div>
      ) : stories.length === 0 ? (
        <EmptyState
          title="Nothing is playable yet"
          body="Go back to Author Mode, generate a story, and publish it before returning to the Play library."
          action={<Button variant="secondary" onClick={() => navigate('/author/stories')}>Open Author Mode</Button>}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {stories.map((story) => (
            <article key={story.story_id} className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.05)] p-5">
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="success">Published v{story.latest_published_version}</Pill>
                <Pill tone="neutral">Updated {story.latest_published_at ? formatDateTime(story.latest_published_at) : 'unknown'}</Pill>
              </div>
              <h3 className="mt-4 break-words font-[var(--font-title)] text-2xl tracking-[0.06em] text-[var(--text-ivory)]">{story.title}</h3>
              <p className="mt-3 break-all text-sm leading-6 text-[var(--text-dim)]">{story.story_id}</p>
              <div className="mt-5 flex flex-wrap gap-3">
                <Button
                  onClick={() => void handleCreateSession(story.story_id, story.latest_published_version!)}
                  disabled={creatingStoryId === story.story_id}
                >
                  {creatingStoryId === story.story_id ? 'Opening Session...' : 'Start Play Session'}
                </Button>
                <Button variant="secondary" onClick={() => navigate(`/author/stories/${story.story_id}`)}>
                  View Author Detail
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
