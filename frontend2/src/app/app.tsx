import { useEffect } from "react"
import { ApiProvider } from "./api-context"
import { AuthProvider } from "./auth-context"
import { type AppRoute, useAppRoute } from "./routes"
import { HomePage } from "../pages/home/home-page"
import { CreatePage } from "../pages/create/create-page"
import { PlayPage } from "../pages/play/play-page"
import { AboutPage } from "../pages/about/about-page"
import { LoginPage } from "../pages/auth/login-page"
import { ReplayPage } from "../pages/replay/replay-page"
import { TemplateDetailPage } from "../pages/world/world-detail-page"

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
          onOpenCreate={() => navigate({ name: "create" })}
          onOpenTemplate={(templateId) => navigate({ name: "template", templateId })}
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
          onSessionStarted={(sessionId) => navigate({ name: "play", sessionId })}
        />
      )
    case "template":
      return (
        <TemplateDetailPage
          templateId={route.templateId}
          onBackHome={() => navigate({ name: "home" })}
          onOpenCreate={() => navigate({ name: "create" })}
          onSessionStarted={(sessionId) => navigate({ name: "play", sessionId })}
        />
      )
    case "play":
      return (
        <PlayPage
          sessionId={route.sessionId}
          onBackHome={() => navigate({ name: "home" })}
        />
      )
    case "replay":
      return (
        <ReplayPage
          sessionId={route.sessionId}
          onBackHome={() => navigate({ name: "home" })}
          onOpenTemplate={(templateId) => navigate({ name: "template", templateId })}
        />
      )
    case "about":
      return (
        <AboutPage
          onBackHome={() => navigate({ name: "home" })}
          onOpenCreate={() => navigate({ name: "create" })}
        />
      )
  }
  return <NotFoundRedirect navigate={navigate} />
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
