import { useEffect } from "react"
import { AnimatePresence, motion } from "motion/react"
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
import { pageTransition, pageVariants } from "../shared/lib/motion-presets"

function NotFoundRedirect({ navigate }: { navigate: (next: AppRoute) => void }) {
  useEffect(() => {
    navigate({ name: "home" })
  }, [navigate])
  return null
}

function renderRoute(route: AppRoute, navigate: (next: AppRoute) => void) {
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

function routeKey(route: AppRoute): string {
  switch (route.name) {
    case "home": return "home"
    case "login": return "login"
    case "create": return "create"
    case "about": return "about"
    case "template": return `template:${route.templateId}`
    case "play": return `play:${route.sessionId}`
    case "replay": return `replay:${route.sessionId}`
  }
}

function Router() {
  const { route, navigate } = useAppRoute()
  const key = routeKey(route)
  // Reset scroll on every navigation. AnimatePresence handles the
  // mount/unmount choreography but doesn't touch window scroll, so
  // routes can land on a non-zero scroll position from the previous
  // page and feel jarring. Keying on routeKey runs once per real
  // route change, not on every render of the same page.
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" })
  }, [key])
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={key}
        variants={pageVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={pageTransition}
      >
        {renderRoute(route, navigate)}
      </motion.div>
    </AnimatePresence>
  )
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
