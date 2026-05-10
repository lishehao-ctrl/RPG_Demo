import { useEffect, useRef, useState } from "react"

export type AppRoute =
  | { name: "home" }
  | { name: "login"; next?: string }
  | { name: "create" }
  | { name: "template"; templateId: string }
  | { name: "play"; sessionId: string; reviewer?: boolean }
  | { name: "replay"; sessionId: string }
  | { name: "portfolio" }
  | { name: "reviewer" }
  | { name: "about" }

export type NavDirection = "forward" | "backward"

// Where each route sits in the conceptual depth tree. The router
// uses this to decide whether a transition is "going deeper" (forward
// = slide-up) or "going back" (backward = slide-down). Without this,
// every page transition was the same y: 8 nudge regardless of where
// the user was heading.
const ROUTE_DEPTH: Record<AppRoute["name"], number> = {
  home: 0,
  about: 1,
  login: 1,
  create: 1,
  replay: 1,
  portfolio: 1,
  reviewer: 1,
  template: 1,
  play: 2,
}

function depthOf(route: AppRoute): number {
  return ROUTE_DEPTH[route.name] ?? 0
}

function parseRoute(hash: string): AppRoute {
  const raw = hash.replace(/^#/, "") || "/"
  const [pathname, search = ""] = raw.split("?")
  const segments = pathname.split("/").filter(Boolean)
  const params = new URLSearchParams(search)

  if (segments.length === 0) {
    return { name: "home" }
  }
  if (segments[0] === "login") {
    return { name: "login", next: params.get("next") ?? undefined }
  }
  if (segments[0] === "create") {
    return { name: "create" }
  }
  if (segments[0] === "template" && segments[1]) {
    return { name: "template", templateId: segments[1] }
  }
  if (segments[0] === "play" && segments[1]) {
    return { name: "play", sessionId: segments[1], reviewer: params.get("reviewer") === "1" }
  }
  if (segments[0] === "replay" && segments[1]) {
    return { name: "replay", sessionId: segments[1] }
  }
  if (segments[0] === "portfolio") {
    return { name: "portfolio" }
  }
  if (segments[0] === "reviewer") {
    return { name: "reviewer" }
  }
  if (segments[0] === "about") {
    return { name: "about" }
  }
  return { name: "home" }
}

export function buildHash(route: AppRoute): string {
  switch (route.name) {
    case "home":
      return "#/"
    case "login": {
      if (route.next) {
        const params = new URLSearchParams({ next: route.next })
        return `#/login?${params.toString()}`
      }
      return "#/login"
    }
    case "create":
      return "#/create"
    case "template":
      return `#/template/${route.templateId}`
    case "play":
      return route.reviewer
        ? `#/play/${route.sessionId}?reviewer=1`
        : `#/play/${route.sessionId}`
    case "replay":
      return `#/replay/${route.sessionId}`
    case "portfolio":
      return "#/portfolio"
    case "reviewer":
      return "#/reviewer"
    case "about":
      return "#/about"
  }
}

export function useAppRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.hash))
  const [direction, setDirection] = useState<NavDirection>("forward")
  const prevRouteRef = useRef<AppRoute>(route)

  useEffect(() => {
    const onChange = () => {
      const next = parseRoute(window.location.hash)
      const prev = prevRouteRef.current
      // Same-name navigation (e.g. play/A → play/B) reads as
      // "forward" — switching sessions feels like a step into a
      // new run, not a step back.
      if (depthOf(next) >= depthOf(prev)) {
        setDirection("forward")
      } else {
        setDirection("backward")
      }
      prevRouteRef.current = next
      setRoute(next)
    }
    window.addEventListener("hashchange", onChange)
    if (!window.location.hash) {
      window.history.replaceState(null, "", buildHash({ name: "home" }))
      setRoute({ name: "home" })
      prevRouteRef.current = { name: "home" }
    }
    return () => window.removeEventListener("hashchange", onChange)
  }, [])

  const navigate = (next: AppRoute) => {
    const nextHash = buildHash(next)
    if (window.location.hash === nextHash) {
      setRoute(next)
      return
    }
    window.location.hash = nextHash
  }

  return { route, navigate, direction }
}
