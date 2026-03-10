import { Navigate, Outlet, createBrowserRouter } from 'react-router-dom';
import { AuthorStoriesPage } from '@/pages/author/AuthorStoriesPage';
import { AuthorRunDetailPage } from '@/pages/author/AuthorRunDetailPage';
import { AuthorStoryReviewPage } from '@/pages/author/AuthorStoryReviewPage';
import { AuthorStoryResolverPage } from '@/pages/author/AuthorStoryResolverPage';
import { LoginPage } from '@/pages/LoginPage';
import { PlayLibraryPage } from '@/pages/play/PlayLibraryPage';
import { PlaySessionPage } from '@/pages/play/PlaySessionPage';
import { AppShell } from '@/shared/ui/AppShell';
import { useAuthStore } from '@/shared/store/authStore';

function HydrationGate() {
  return (
    <div className="page-shell flex min-h-screen items-center justify-center text-sm uppercase tracking-[0.22em] text-[var(--text-dim)]">
      Syncing command state...
    </div>
  );
}

function RootRedirect() {
  const token = useAuthStore((state) => state.token);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <HydrationGate />;
  }

  return <Navigate to={token ? '/author/stories' : '/login'} replace />;
}

function ProtectedLayout({ mode }: { mode: 'author' | 'play' }) {
  const token = useAuthStore((state) => state.token);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <HydrationGate />;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  const shellProps =
    mode === 'author'
      ? {
          eyebrow: 'Ember Command / Author Suite',
          title: 'Story Forge',
          modeLabel: 'Author Mode',
          navItems: [
            { label: 'Stories', href: '/author/stories' },
            { label: 'Play Library', href: '/play/library' },
          ],
        }
      : {
          eyebrow: 'Ember Command / Play Suite',
          title: 'Runtime Chamber',
          modeLabel: 'Play Mode',
          navItems: [
            { label: 'Play Library', href: '/play/library' },
            { label: 'Author Stories', href: '/author/stories' },
          ],
        };

  return (
    <AppShell {...shellProps}>
      <Outlet />
    </AppShell>
  );
}

function GuestOnlyRoute() {
  const token = useAuthStore((state) => state.token);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) {
    return <HydrationGate />;
  }

  if (token) {
    return <Navigate to="/author/stories" replace />;
  }

  return <LoginPage />;
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <RootRedirect />,
  },
  {
    path: '/login',
    element: <GuestOnlyRoute />,
  },
  {
    path: '/author',
    element: <ProtectedLayout mode="author" />,
    children: [
      { index: true, element: <Navigate to="/author/stories" replace /> },
      { path: 'stories', element: <AuthorStoriesPage /> },
      { path: 'runs/:runId', element: <AuthorRunDetailPage /> },
      { path: 'stories/:storyId', element: <AuthorStoryResolverPage /> },
      { path: 'stories/:storyId/review', element: <AuthorStoryReviewPage /> },
    ],
  },
  {
    path: '/play',
    element: <ProtectedLayout mode="play" />,
    children: [
      { index: true, element: <Navigate to="/play/library" replace /> },
      { path: 'library', element: <PlayLibraryPage /> },
      { path: 'sessions/:sessionId', element: <PlaySessionPage /> },
    ],
  },
]);
