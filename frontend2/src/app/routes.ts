import { useEffect, useState } from "react"

export type AppRoute =
  | { name: "home" }
  | { name: "login"; next?: string }
  | { name: "create" }
  | { name: "template"; templateId: string }
  | { name: "play"; sessionId: string }
  | { name: "replay"; sessionId: string }

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
    return { name: "play", sessionId: segments[1] }
  }
  if (segments[0] === "replay" && segments[1]) {
    return { name: "replay", sessionId: segments[1] }
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
      return `#/play/${route.sessionId}`
    case "replay":
      return `#/replay/${route.sessionId}`
  }
}

export function useAppRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener("hashchange", onChange)
    if (!window.location.hash) {
      window.history.replaceState(null, "", buildHash({ name: "home" }))
      setRoute({ name: "home" })
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

  return { route, navigate }
}
