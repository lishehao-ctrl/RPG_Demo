import { useEffect, useState } from "react"
import type { PublishedStoryListView } from "../index"
import { normalizeAuthorConceptStage, normalizeConceptVariant, type AuthorConceptStage, type ConceptVariant } from "../shared/lib/concept-review-types"

export type AppRoute =
  | { name: "landing" }
  | { name: "auth"; mode?: "login" | "register"; next?: string }
  | { name: "create-story" }
  | { name: "author-loading"; jobId: string }
  | { name: "concept-author"; variant: ConceptVariant; stage: AuthorConceptStage }
  | { name: "concept-play"; variant: ConceptVariant }
  | { name: "story-library"; selectedStoryId?: string; q?: string; theme?: string; view?: PublishedStoryListView }
  | { name: "story-detail"; storyId: string }
  | { name: "play-session"; sessionId: string }

function parseRoute(hash: string): AppRoute {
  const raw = hash.replace(/^#/, "") || "/"
  const [pathname, search = ""] = raw.split("?")
  const segments = pathname.split("/").filter(Boolean)
  const params = new URLSearchParams(search)

  if (segments.length === 0 || segments[0] === "landing") {
    return { name: "landing" }
  }

  if (segments[0] === "auth") {
    const mode = params.get("mode")
    return {
      name: "auth",
      mode: mode === "register" ? "register" : "login",
      next: params.get("next") ?? undefined,
    }
  }

  if (segments[0] === "create-story") {
    return { name: "create-story" }
  }

  if (segments[0] === "author-jobs" && segments[1]) {
    return { name: "author-loading", jobId: segments[1] }
  }

  if (segments[0] === "concept" && segments[1] === "author") {
    return {
      name: "concept-author",
      variant: normalizeConceptVariant(params.get("variant")),
      stage: normalizeAuthorConceptStage(params.get("stage")),
    }
  }

  if (segments[0] === "concept" && segments[1] === "play") {
    return {
      name: "concept-play",
      variant: normalizeConceptVariant(params.get("variant")),
    }
  }

  if (segments[0] === "stories" && segments[1]) {
    return { name: "story-detail", storyId: segments[1] }
  }

  if (segments[0] === "stories") {
    return {
      name: "story-library",
      selectedStoryId: params.get("story") ?? undefined,
      q: params.get("q") ?? undefined,
      theme: params.get("theme") ?? undefined,
      view: (params.get("view") as PublishedStoryListView | null) ?? undefined,
    }
  }

  if (segments[0] === "play" && segments[1] === "sessions" && segments[2]) {
    return { name: "play-session", sessionId: segments[2] }
  }

  return { name: "landing" }
}

export function buildHash(route: AppRoute): string {
  switch (route.name) {
    case "landing":
      return "#/"

    case "auth": {
      const params = new URLSearchParams()
      if (route.mode) {
        params.set("mode", route.mode)
      }
      if (route.next) {
        params.set("next", route.next)
      }
      const query = params.toString()
      return query ? `#/auth?${query}` : "#/auth"
    }

    case "author-loading":
      return `#/author-jobs/${route.jobId}`

    case "concept-author": {
      const params = new URLSearchParams()
      params.set("variant", route.variant)
      params.set("stage", route.stage)
      return `#/concept/author?${params.toString()}`
    }

    case "concept-play": {
      const params = new URLSearchParams()
      params.set("variant", route.variant)
      return `#/concept/play?${params.toString()}`
    }

    case "story-library": {
      const params = new URLSearchParams()
      if (route.selectedStoryId) {
        params.set("story", route.selectedStoryId)
      }
      if (route.q) {
        params.set("q", route.q)
      }
      if (route.theme) {
        params.set("theme", route.theme)
      }
      if (route.view) {
        params.set("view", route.view)
      }
      const query = params.toString()
      return query ? `#/stories?${query}` : "#/stories"
    }

    case "story-detail":
      return `#/stories/${route.storyId}`

    case "play-session":
      return `#/play/sessions/${route.sessionId}`

    case "create-story":
      return "#/create-story"
  }
}

export function useAppRoute() {
  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const handleHashChange = () => {
      setRoute(parseRoute(window.location.hash))
    }

    window.addEventListener("hashchange", handleHashChange)

    if (!window.location.hash) {
      window.history.replaceState(null, "", buildHash({ name: "landing" }))
      setRoute({ name: "landing" })
    }

    return () => {
      window.removeEventListener("hashchange", handleHashChange)
    }
  }, [])

  const navigate = (nextRoute: AppRoute) => {
    const nextHash = buildHash(nextRoute)
    if (window.location.hash === nextHash) {
      setRoute(nextRoute)
      return
    }
    window.location.hash = nextHash
  }

  return { route, navigate }
}
