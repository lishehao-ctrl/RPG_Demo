import { useEffect } from "react"
import { ApiProvider } from "./api-context"
import { AuthProvider } from "./auth-context"
import { type AppRoute, useAppRoute } from "./routes"
import { HomePage } from "../pages/home/home-page"
import { CreatePage } from "../pages/create/create-page"
import { GeneratingPage } from "../pages/generating/generating-page"
import { PlayPage } from "../pages/play/play-page"
import { LoginPage } from "../pages/auth/login-page"
import { WorldDetailPage } from "../pages/world/world-detail-page"
import { ReplayPage } from "../pages/play/replay-page"

function NotFoundRedirect({ navigate }: { navigate: (next: AppRoute) => void }) {
  useEffect(() => {
    navigate({ name: "home" })
  }, [navigate])
  return null
}

function Router() {
  const { route, navigate } = useAppRoute()

  switch (route.name) {
    case "home":
      return (
        <HomePage
          initialOpenStoryId={route.openStoryId}
          onOpenCreate={() => navigate({ name: "create" })}
          onOpenPlay={(sessionId) => navigate({ name: "play", sessionId })}
        />
      )
    case "login":
      return (
        <LoginPage
          next={route.next}
          onBackHome={() => navigate({ name: "home" })}
          onOpenCreate={() => navigate({ name: "create" })}
          onLoggedIn={(next) => {
            if (next === "create") navigate({ name: "create" })
            else navigate({ name: "home" })
          }}
        />
      )
    case "create":
      return (
        <CreatePage
          onBackHome={() => navigate({ name: "home" })}
          onJobCreated={(jobId) => navigate({ name: "generating", jobId })}
        />
      )
    case "generating":
      return (
        <GeneratingPage
          jobId={route.jobId}
          onBackHome={() => navigate({ name: "home" })}
          onOpenWorld={(storyId) => navigate({ name: "world", storyId })}
        />
      )
    case "play":
      return (
        <PlayPage
          sessionId={route.sessionId}
          onBackHome={() => navigate({ name: "home" })}
        />
      )
    case "world":
      return (
        <WorldDetailPage
          storyId={route.storyId}
          onBackHome={() => navigate({ name: "home" })}
          onOpenCreate={() => navigate({ name: "create" })}
          onOpenPlay={(sessionId) => navigate({ name: "play", sessionId })}
        />
      )
    case "replay":
      return (
        <ReplayPage
          sessionId={route.sessionId}
          onBackHome={() => navigate({ name: "home" })}
          onOpenCreate={() => navigate({ name: "create" })}
        />
      )
  }
}

export default function App() {
  return (
    <ApiProvider>
      <AuthProvider>
        <Router />
      </AuthProvider>
    </ApiProvider>
  )
}
