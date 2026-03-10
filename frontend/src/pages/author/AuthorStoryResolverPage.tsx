import { useEffect, useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { apiService } from '@/shared/api/service';
import { ApiClientError } from '@/shared/api/client';
import { authorStoryTarget } from '@/features/author-review/lib/authorViewModel';
import { ErrorBanner } from '@/shared/ui/ErrorBanner';
import { Panel } from '@/shared/ui/Panel';

export function AuthorStoryResolverPage() {
  const { storyId = '' } = useParams();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState<ApiClientError | Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const story = await apiService.getAuthorStory(storyId);
        if (!cancelled) {
          setTarget(authorStoryTarget(story));
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught as ApiClientError | Error);
        }
      }
    }
    if (storyId) {
      void load();
    }
    return () => {
      cancelled = true;
    };
  }, [storyId]);

  if (target) {
    return <Navigate to={target} replace />;
  }

  return (
    <Panel eyebrow="Story Route" title="Routing author shell" subtitle="Choosing the correct Forge / Run / Review shell for the latest author state.">
      <ErrorBanner error={error} context="author-stories-load" />
      {!error ? (
        <div className="rounded-[24px] border border-[var(--line)] bg-[rgba(255,248,229,0.04)] px-5 py-10 text-center text-[var(--text-mist)]">
          Loading story route...
        </div>
      ) : null}
    </Panel>
  );
}
