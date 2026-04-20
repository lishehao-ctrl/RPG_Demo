import { useEffect, useMemo, useState } from "react"
import { getDefaultApiClient } from "./config/api-client"
import { AuthProvider, useAuth } from "./providers/auth-provider"
import { ApiClientProvider } from "./providers/api-client-provider"
import { buildHash, type AppRoute, useAppRoute } from "./routes"
import type { PublishedStoryListView } from "../index"
import { LandingPage } from "../pages/landing/landing-page"
import { AuthPage } from "../pages/auth/auth-page"
import { CreateStoryPage } from "../pages/authoring/create-story-page"
import { AuthorLoadingPage } from "../pages/authoring/author-loading-page"
import { StoryLibraryPage } from "../pages/play/story-library-page"
import { StoryDetailPage } from "../pages/play/story-detail-page"
import { PlaySessionPage } from "../pages/play/play-session-page"
import { ConceptAuthorPage } from "../pages/concepts/concept-author-page"
import { ConceptPlayPage } from "../pages/concepts/concept-play-page"
import { AppShell } from "../shared/ui/app-shell"
import { AppHeader } from "../widgets/chrome/app-header"

function AppScene({
  route,
  navigate,
  librarySearchQuery,
  libraryTheme,
  libraryView,
  openLibrary,
  onLibraryThemeChange,
  onLibraryViewChange,
  authenticated,
  onRequireAuth,
  onResolveAuth,
}: {
  route: AppRoute
  navigate: (nextRoute: AppRoute) => void
  librarySearchQuery: string
  libraryTheme: string | null
  libraryView: PublishedStoryListView
  openLibrary: (selectedStoryId?: string, options?: { preserveFilters?: boolean }) => void
  onLibraryThemeChange: (theme: string | null) => void
  onLibraryViewChange: (view: PublishedStoryListView) => void
  authenticated: boolean
  onRequireAuth: (nextHash: string, mode?: "login" | "register") => void
  onResolveAuth: (nextHash?: string) => void
}) {
  switch (route.name) {
    case "landing":
      return (
        <LandingPage
          authenticated={authenticated}
          onOpenCreateStory={() => navigate({ name: "create-story" })}
          onOpenLibrary={() => openLibrary(undefined, { preserveFilters: true })}
          onOpenPlaySession={(sessionId) => navigate({ name: "play-session", sessionId })}
          onOpenStoryDetail={(storyId) => navigate({ name: "story-detail", storyId })}
        />
      )

    case "auth":
      return (
        <AuthPage
          mode={route.mode ?? "login"}
          nextHash={route.next}
          onOpenLibrary={() => openLibrary(undefined, { preserveFilters: true })}
          onResolveAuth={onResolveAuth}
        />
      )

    case "create-story":
      return (
        <CreateStoryPage
          onOpenAuthorJob={(jobId) => navigate({ name: "author-loading", jobId })}
          onOpenLibrary={() => openLibrary(undefined, { preserveFilters: true })}
        />
      )

    case "author-loading":
      return (
        <AuthorLoadingPage
          jobId={route.jobId}
          onOpenCreateStory={() => navigate({ name: "create-story" })}
          onOpenLibrary={(storyId) => openLibrary(storyId, { preserveFilters: false })}
        />
      )

    case "concept-author":
      return (
        <ConceptAuthorPage
          onOpenPlayConcept={(variant) => navigate({ name: "concept-play", variant })}
          onSelectStage={(stage) => navigate({ name: "concept-author", variant: route.variant, stage })}
          onSelectVariant={(variant) => navigate({ name: "concept-author", variant, stage: route.stage })}
          stage={route.stage}
          variant={route.variant}
        />
      )

    case "concept-play":
      return (
        <ConceptPlayPage
          onOpenAuthorConcept={(variant) => navigate({ name: "concept-author", variant, stage: "create" })}
          onSelectVariant={(variant) => navigate({ name: "concept-play", variant })}
          variant={route.variant}
        />
      )

    case "story-library":
      return (
        <StoryLibraryPage
          authenticated={authenticated}
          initialStoryId={route.selectedStoryId}
          searchQuery={librarySearchQuery}
          selectedTheme={libraryTheme}
          selectedView={libraryView}
          onOpenCreateStory={() => navigate({ name: "create-story" })}
          onRequireAuth={() => onRequireAuth(buildHash({ name: "create-story" }))}
          onOpenStoryDetail={(storyId) => navigate({ name: "story-detail", storyId })}
          onThemeChange={onLibraryThemeChange}
          onViewChange={onLibraryViewChange}
        />
      )

    case "story-detail":
      return (
        <StoryDetailPage
          isAuthenticated={authenticated}
          storyId={route.storyId}
          onOpenLibrary={(storyId) => openLibrary(storyId, { preserveFilters: true })}
          onDeleteToLibrary={() => openLibrary(undefined, { preserveFilters: true })}
          onOpenPlaySession={(sessionId) => navigate({ name: "play-session", sessionId })}
          onRequireAuth={() => onRequireAuth(buildHash({ name: "story-detail", storyId: route.storyId }))}
        />
      )

    case "play-session":
      return (
        <PlaySessionPage
          sessionId={route.sessionId}
          onOpenLibrary={(storyId) => openLibrary(storyId, { preserveFilters: true })}
        />
      )
  }
}

function AppInner() {
  const auth = useAuth()
  const client = useMemo(() => getDefaultApiClient(), [])
  const { route, navigate } = useAppRoute()
  const conceptRoute = route.name === "concept-author" || route.name === "concept-play"
  const [librarySearchQuery, setLibrarySearchQuery] = useState(route.name === "story-library" ? route.q ?? "" : "")
  const [libraryTheme, setLibraryTheme] = useState<string | null>(route.name === "story-library" ? route.theme ?? null : null)
  const [libraryView, setLibraryView] = useState<PublishedStoryListView>(route.name === "story-library" ? route.view ?? (auth.authenticated ? "accessible" : "public") : (auth.authenticated ? "accessible" : "public"))
  const effectiveLibraryView: PublishedStoryListView = auth.authenticated ? libraryView : "public"

  useEffect(() => {
    if (route.name !== "story-library") {
      return
    }
    setLibrarySearchQuery(route.q ?? "")
    setLibraryTheme(route.theme ?? null)
    setLibraryView(route.view ?? (auth.authenticated ? "accessible" : "public"))
  }, [auth.authenticated, route])

  useEffect(() => {
    if (auth.loading || auth.authenticated) {
      return
    }
    if (route.name === "create-story" || route.name === "author-loading" || route.name === "play-session") {
      navigate({
        name: "auth",
        mode: "login",
        next: buildHash(route),
      })
    }
  }, [auth.authenticated, auth.loading, navigate, route])

  const openLibrary = (selectedStoryId?: string, options?: { preserveFilters?: boolean }) => {
    const preserveFilters = options?.preserveFilters ?? true
    navigate({
      name: "story-library",
      selectedStoryId,
      q: preserveFilters ? librarySearchQuery.trim() || undefined : undefined,
      theme: preserveFilters ? libraryTheme ?? undefined : undefined,
      view: preserveFilters ? effectiveLibraryView : (auth.authenticated ? "accessible" : "public"),
    })
  }

  const openLanding = () => {
    navigate({ name: "landing" })
  }

  const openAuth = (mode: "login" | "register", nextHash?: string) => {
    navigate({
      name: "auth",
      mode,
      next: nextHash,
    })
  }

  const resolveAuth = (nextHash?: string) => {
    window.location.hash = nextHash || buildHash({ name: "story-library", view: "accessible" })
  }

  const handleLibrarySearchChange = (value: string) => {
    setLibrarySearchQuery(value)
    const normalizedQuery = value.trim()
    const nextTheme = libraryTheme ?? undefined
    navigate({
      name: "story-library",
      q: normalizedQuery || undefined,
      theme: nextTheme,
      view: effectiveLibraryView,
    })
  }

  const handleLibraryThemeChange = (theme: string | null) => {
    setLibraryTheme(theme)
    navigate({
      name: "story-library",
      q: librarySearchQuery.trim() || undefined,
      theme: theme ?? undefined,
      view: effectiveLibraryView,
    })
  }

  const handleLibraryViewChange = (view: PublishedStoryListView) => {
    if (!auth.authenticated) {
      setLibraryView("public")
      navigate({
        name: "story-library",
        q: librarySearchQuery.trim() || undefined,
        theme: libraryTheme ?? undefined,
        view: "public",
      })
      return
    }
    setLibraryView(view)
    navigate({
      name: "story-library",
      q: librarySearchQuery.trim() || undefined,
      theme: libraryTheme ?? undefined,
      view,
    })
  }

  const handleOpenCreateStory = () => {
    if (auth.authenticated) {
      navigate({ name: "create-story" })
      return
    }
    openAuth("login", buildHash({ name: "create-story" }))
  }

  const handleLogout = async () => {
    await auth.logout()
    if (route.name === "create-story" || route.name === "author-loading" || route.name === "play-session") {
      openLibrary(undefined, { preserveFilters: false })
    }
  }

  return (
    <ApiClientProvider client={client}>
      <AppShell>
        {conceptRoute ? null : (
          <AppHeader
            authenticated={auth.authenticated}
            authLoading={auth.loading}
            user={auth.user}
            onLogout={() => {
              void handleLogout()
            }}
            onOpenLanding={openLanding}
            onOpenAuth={openAuth}
            routeName={route.name}
            onOpenCreateStory={handleOpenCreateStory}
            onOpenLibrary={() => openLibrary(undefined, { preserveFilters: true })}
            onSearchChange={handleLibrarySearchChange}
            searchEnabled={
              route.name === "story-library" ||
              route.name === "story-detail" ||
              route.name === "play-session"
            }
            searchValue={librarySearchQuery}
          />
        )}
        <AppScene
          authenticated={auth.authenticated}
          librarySearchQuery={librarySearchQuery}
          libraryTheme={libraryTheme}
          libraryView={effectiveLibraryView}
          navigate={navigate}
          onLibraryThemeChange={handleLibraryThemeChange}
          onLibraryViewChange={handleLibraryViewChange}
          onRequireAuth={(nextHash, mode = "login") => openAuth(mode, nextHash)}
          onResolveAuth={resolveAuth}
          openLibrary={openLibrary}
          route={route}
        />
      </AppShell>
    </ApiClientProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppInner />
    </AuthProvider>
  )
}
