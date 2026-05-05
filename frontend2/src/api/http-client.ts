import {
  type AuthLoginRequest,
  type AuthSessionResponse,
  type AuthorJobCreateRequest,
  type AuthorJobEvent,
  type AuthorJobEventName,
  type AuthorJobResultResponse,
  type AuthorJobStatusResponse,
  type AuthorPreviewRequest,
  type AuthorPreviewResponse,
  type CurrentActorResponse,
  type DeleteStoryResponse,
  type FrontendApiError,
  type ListStoriesParams,
  type NarrativeAdvanceTurnRequest,
  type NarrativeAdvanceTurnResponse,
  type NarrativeAdvisorAskRequest,
  type NarrativeAdvisorAskResponse,
  type NarrativeAdvisorHistoryResponse,
  type NarrativeCreateTemplateRequest,
  type NarrativeCreateTemplateResponse,
  type NarrativeSessionListResponse,
  type NarrativeStartSessionResponse,
  type NarrativeStoryHistoryResponse,
  type NarrativeTemplateListResponse,
  type NarrativeTemplateSummary,
  type NarrativeUpdateVisibilityRequest,
  type PlaySessionCreateRequest,
  type PlaySessionHistoryResponse,
  type PlaySessionReplayResponse,
  type PlaySessionSnapshot,
  type PlayTurnRequest,
  type PublishedStoryCard,
  type PublishedStoryDetailResponse,
  type PublishedStoryListResponse,
  type UpdateStoryVisibilityRequest,
} from "./contracts"
import type { FrontendApiClient } from "./client"
import { BACKEND_ROUTE_MAP } from "./route-map"

type RouteParams = Record<string, string | number>

class ApiRequestError extends Error {
  statusCode: number
  errorCode?: string

  constructor(message: string, statusCode: number, errorCode?: string) {
    super(message)
    this.name = "ApiRequestError"
    this.statusCode = statusCode
    this.errorCode = errorCode
  }
}

function resolvePath(template: string, params: RouteParams = {}): string {
  return template.replace(/:([a-z_]+)/gi, (_, key) => encodeURIComponent(String(params[key])))
}

async function readErrorPayload(response: Response): Promise<{ message: string; code?: string }> {
  try {
    const payload = (await response.json()) as FrontendApiError
    if (payload.error?.message) {
      return {
        message: payload.error.message,
        code: payload.error.code,
      }
    }
  } catch {
    return { message: `Request failed with status ${response.status}` }
  }

  return { message: `Request failed with status ${response.status}` }
}

function parseSseEvent(block: string): AuthorJobEvent | null {
  let id = 0
  let event = "stage_changed" as AuthorJobEventName
  const dataLines: string[] = []

  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) {
      continue
    }

    if (line.startsWith("id:")) {
      id = Number(line.slice(3).trim())
      continue
    }

    if (line.startsWith("event:")) {
      event = line.slice(6).trim() as AuthorJobEventName
      continue
    }

    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim())
    }
  }

  if (dataLines.length === 0) {
    return null
  }

  return {
    id,
    event,
    data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>,
  }
}

export function createHttpApiClient(baseUrl: string): FrontendApiClient {
  const normalizedBaseUrl = baseUrl.replace(/\/$/, "")

  async function requestJson<TResponse>(
    routeKey: keyof typeof BACKEND_ROUTE_MAP,
    options: {
      params?: RouteParams
      body?: unknown
      query?: Record<string, string | number | undefined>
    } = {},
  ): Promise<TResponse> {
    const route = BACKEND_ROUTE_MAP[routeKey]
    const url = new URL(resolvePath(route.path, options.params), `${normalizedBaseUrl}/`)

    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value))
      }
    }

    const response = await fetch(url.toString(), {
      method: route.method,
      credentials: "include",
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    })

    if (!response.ok) {
      const errorPayload = await readErrorPayload(response)
      throw new ApiRequestError(errorPayload.message, response.status, errorPayload.code)
    }

    if (response.status === 204) {
      return undefined as TResponse
    }

    return (await response.json()) as TResponse
  }

  return {
    getAuthSession() {
      return requestJson<AuthSessionResponse>("getAuthSession")
    },

    loginAuth(request: AuthLoginRequest) {
      return requestJson<AuthSessionResponse>("loginAuth", { body: request })
    },

    async logoutAuth() {
      const route = BACKEND_ROUTE_MAP.logoutAuth
      const url = new URL(resolvePath(route.path), `${normalizedBaseUrl}/`)
      const response = await fetch(url.toString(), {
        method: route.method,
        credentials: "include",
      })
      if (!response.ok) {
        const errorPayload = await readErrorPayload(response)
        throw new ApiRequestError(errorPayload.message, response.status, errorPayload.code)
      }
    },

    getCurrentActor() {
      return requestJson<CurrentActorResponse>("getCurrentActor")
    },

    createStoryPreview(request: AuthorPreviewRequest) {
      return requestJson<AuthorPreviewResponse>("createStoryPreview", { body: request })
    },

    createAuthorJob(request: AuthorJobCreateRequest) {
      return requestJson<AuthorJobStatusResponse>("createAuthorJob", { body: request })
    },

    getAuthorJob(jobId: string) {
      return requestJson<AuthorJobStatusResponse>("getAuthorJob", { params: { job_id: jobId } })
    },

    async *streamAuthorJobEvents(jobId: string, lastEventId = 0) {
      const route = BACKEND_ROUTE_MAP.streamAuthorJobEvents
      const url = new URL(resolvePath(route.path, { job_id: jobId }), `${normalizedBaseUrl}/`)
      if (lastEventId > 0) {
        url.searchParams.set("last_event_id", String(lastEventId))
      }

      const response = await fetch(url.toString(), {
        credentials: "include",
        headers: {
          Accept: "text/event-stream",
        },
      })

      if (!response.ok) {
        const errorPayload = await readErrorPayload(response)
        throw new ApiRequestError(errorPayload.message, response.status, errorPayload.code)
      }

      if (!response.body) {
        return
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { value, done } = await reader.read()
        if (done) {
          break
        }

        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split("\n\n")
        buffer = blocks.pop() ?? ""

        for (const block of blocks) {
          const event = parseSseEvent(block.trim())
          if (event) {
            yield event
          }
        }
      }

      const trailingEvent = parseSseEvent(buffer.trim())
      if (trailingEvent) {
        yield trailingEvent
      }
    },

    getAuthorJobResult(jobId: string) {
      return requestJson<AuthorJobResultResponse>("getAuthorJobResult", { params: { job_id: jobId } })
    },

    publishAuthorJob(jobId: string, visibility = "private") {
      return requestJson<PublishedStoryCard>("publishAuthorJob", {
        params: { job_id: jobId },
        query: {
          visibility,
        },
      })
    },

    listStories(params: ListStoriesParams = {}) {
      return requestJson<PublishedStoryListResponse>("listStories", {
        query: {
          q: params.q ?? undefined,
          theme: params.theme ?? undefined,
          view: params.view ?? undefined,
          limit: params.limit ?? undefined,
          cursor: params.cursor ?? undefined,
          sort: params.sort ?? undefined,
        },
      })
    },

    listMyWorlds(params: { limit?: number; cursor?: string | null } = {}) {
      return requestJson<PublishedStoryListResponse>("listMyWorlds", {
        query: {
          limit: params.limit ?? undefined,
          cursor: params.cursor ?? undefined,
        },
      })
    },

    getStory(storyId: string) {
      return requestJson<PublishedStoryDetailResponse>("getStory", { params: { story_id: storyId } })
    },

    updateStoryVisibility(storyId: string, request: UpdateStoryVisibilityRequest) {
      return requestJson<PublishedStoryCard>("updateStoryVisibility", {
        params: { story_id: storyId },
        body: request,
      })
    },

    deleteStory(storyId: string) {
      return requestJson<DeleteStoryResponse>("deleteStory", {
        params: { story_id: storyId },
      })
    },

    createPlaySession(request: PlaySessionCreateRequest) {
      return requestJson<PlaySessionSnapshot>("createPlaySession", { body: request })
    },

    getPlaySession(sessionId: string) {
      return requestJson<PlaySessionSnapshot>("getPlaySession", { params: { session_id: sessionId } })
    },

    getPlaySessionHistory(sessionId: string) {
      return requestJson<PlaySessionHistoryResponse>("getPlaySessionHistory", {
        params: { session_id: sessionId },
      })
    },

    getPlaySessionReplay(sessionId: string) {
      return requestJson<PlaySessionReplayResponse>("getPlaySessionReplay", {
        params: { session_id: sessionId },
      })
    },

    submitPlayTurn(sessionId: string, request: PlayTurnRequest) {
      return requestJson<PlaySessionSnapshot>("submitPlayTurn", {
        params: { session_id: sessionId },
        body: request,
      })
    },

    // ---------- Narrative ----------

    createNarrativeTemplate(request: NarrativeCreateTemplateRequest) {
      return requestJson<NarrativeCreateTemplateResponse>("createNarrativeTemplate", {
        body: request,
      })
    },

    listPublicNarrativeTemplates() {
      return requestJson<NarrativeTemplateListResponse>("listPublicNarrativeTemplates")
    },

    getNarrativeTemplate(templateId: string) {
      return requestJson<NarrativeTemplateSummary>("getNarrativeTemplate", {
        params: { template_id: templateId },
      })
    },

    updateNarrativeTemplateVisibility(
      templateId: string,
      request: NarrativeUpdateVisibilityRequest,
    ) {
      return requestJson<NarrativeTemplateSummary>("updateNarrativeTemplateVisibility", {
        params: { template_id: templateId },
        body: request,
      })
    },

    startNarrativeSession(templateId: string) {
      return requestJson<NarrativeStartSessionResponse>("startNarrativeSession", {
        params: { template_id: templateId },
      })
    },

    getNarrativeStory(sessionId: string) {
      return requestJson<NarrativeStoryHistoryResponse>("getNarrativeStory", {
        params: { session_id: sessionId },
      })
    },

    advanceNarrativeTurn(sessionId: string, request: NarrativeAdvanceTurnRequest) {
      return requestJson<NarrativeAdvanceTurnResponse>("advanceNarrativeTurn", {
        params: { session_id: sessionId },
        body: request,
      })
    },

    askNarrativeAdvisor(sessionId: string, request: NarrativeAdvisorAskRequest) {
      return requestJson<NarrativeAdvisorAskResponse>("askNarrativeAdvisor", {
        params: { session_id: sessionId },
        body: request,
      })
    },

    getNarrativeAdvisorHistory(sessionId: string) {
      return requestJson<NarrativeAdvisorHistoryResponse>("getNarrativeAdvisorHistory", {
        params: { session_id: sessionId },
      })
    },

    listMyNarrativeTemplates() {
      return requestJson<NarrativeTemplateListResponse>("listMyNarrativeTemplates")
    },

    listMyNarrativeSessions() {
      return requestJson<NarrativeSessionListResponse>("listMyNarrativeSessions")
    },
  }
}
