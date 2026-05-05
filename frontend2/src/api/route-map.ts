export const BACKEND_ROUTE_MAP = {
  getAuthSession: { method: "GET", path: "/auth/session" },
  loginAuth: { method: "POST", path: "/auth/login" },
  logoutAuth: { method: "POST", path: "/auth/logout" },
  getCurrentActor: { method: "GET", path: "/me" },
  createStoryPreview: { method: "POST", path: "/author/story-previews" },
  createAuthorJob: { method: "POST", path: "/author/jobs" },
  getAuthorJob: { method: "GET", path: "/author/jobs/:job_id" },
  streamAuthorJobEvents: { method: "GET", path: "/author/jobs/:job_id/events" },
  getAuthorJobResult: { method: "GET", path: "/author/jobs/:job_id/result" },
  publishAuthorJob: { method: "POST", path: "/author/jobs/:job_id/publish" },
  listStories: { method: "GET", path: "/stories" },
  getStory: { method: "GET", path: "/stories/:story_id" },
  updateStoryVisibility: { method: "PATCH", path: "/stories/:story_id/visibility" },
  deleteStory: { method: "DELETE", path: "/stories/:story_id" },
  createPlaySession: { method: "POST", path: "/play/sessions" },
  getPlaySession: { method: "GET", path: "/play/sessions/:session_id" },
  getPlaySessionHistory: { method: "GET", path: "/play/sessions/:session_id/history" },
  getPlaySessionReplay: { method: "GET", path: "/play/sessions/:session_id/replay" },
  submitPlayTurn: { method: "POST", path: "/play/sessions/:session_id/turns" },
  listMyWorlds: { method: "GET", path: "/me/worlds" },

  // ---------- Narrative (template/session) ----------
  createNarrativeTemplate: { method: "POST", path: "/narrative/templates" },
  listPublicNarrativeTemplates: { method: "GET", path: "/narrative/templates" },
  getNarrativeTemplate: { method: "GET", path: "/narrative/templates/:template_id" },
  updateNarrativeTemplateVisibility: {
    method: "PATCH",
    path: "/narrative/templates/:template_id/visibility",
  },
  startNarrativeSession: {
    method: "POST",
    path: "/narrative/templates/:template_id/sessions",
  },
  getNarrativeStory: {
    method: "GET",
    path: "/narrative/sessions/:session_id/story",
  },
  advanceNarrativeTurn: {
    method: "POST",
    path: "/narrative/sessions/:session_id/story/turns",
  },
  askNarrativeAdvisor: {
    method: "POST",
    path: "/narrative/sessions/:session_id/advisor",
  },
  getNarrativeAdvisorHistory: {
    method: "GET",
    path: "/narrative/sessions/:session_id/advisor",
  },
  listMyNarrativeTemplates: { method: "GET", path: "/me/narrative/templates" },
  listMyNarrativeSessions: { method: "GET", path: "/me/narrative/sessions" },
} as const

export type BackendRouteKey = keyof typeof BACKEND_ROUTE_MAP
