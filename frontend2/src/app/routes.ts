import { useEffect, useState } from "react"

export type AppRoute =
  | { name: "home"; openStoryId?: string }
  | { name: "login"; next?: string }
  | { name: "create" }
  | { name: "generating"; jobId: string }
  | { name: "world"; storyId: string }
  | { name: "play"; sessionId: string }
  | { name: "replay"; sessionId: string }

function parseRoute(hash: string): AppRoute {
  const raw = hash.replace(/^#/, "") || "/"
  const [pathname, search = ""] = raw.split("?")
  const segments = pathname.split("/").filter(Boolean)
  const params = new URLSearchParams(search)

  if (segments.length === 0) {
    return { name: "home", openStoryId: params.get("story") ?? undefined }
  }
  if (segments[0] === "login") {
    return { name: "login", next: params.get("next") ?? undefined }
  }
  if (segments[0] === "create") {
    return { name: "create" }
  }
  if (segments[0] === "generating" && segments[1]) {
    return { name: "generating", jobId: segments[1] }
  }
  if (segments[0] === "world" && segments[1]) {
    return { name: "world", storyId: segments[1] }
  }
  if (segments[0] === "play" && segments[1]) {
    if (segments[2] === "replay") {
      return { name: "replay", sessionId: segments[1] }
    }
    return { name: "play", sessionId: segments[1] }
  }
  return { name: "home" }
}

export function buildHash(route: AppRoute): string {
  switch (route.name) {
    case "home": {
      if (route.openStoryId) {
        const params = new URLSearchParams({ story: route.openStoryId })
        return `#/?${params.toString()}`
      }
      return "#/"
    }
    case "login": {
      if (route.next) {
        const params = new URLSearchParams({ next: route.next })
        return `#/login?${params.toString()}`
      }
      return "#/login"
    }
    case "create":
      return "#/create"
    case "generating":
      return `#/generating/${route.jobId}`
    case "world":
      return `#/world/${route.storyId}`
    case "play":
      return `#/play/${route.sessionId}`
    case "replay":
      return `#/play/${route.sessionId}/replay`
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
