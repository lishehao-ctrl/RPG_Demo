import type {
  AuthLoginRequest,
  AuthSessionResponse,
  AuthorJobEvent,
  AuthorJobCreateRequest,
  AuthorJobResultResponse,
  AuthorJobStatusResponse,
  AuthorPreviewRequest,
  AuthorPreviewResponse,
  CurrentActorResponse,
  DeleteStoryResponse,
  ListStoriesParams,
  NarrativeAdvanceTurnRequest,
  NarrativeAdvanceTurnResponse,
  NarrativeAdvisorAskRequest,
  NarrativeAdvisorAskResponse,
  NarrativeAdvisorHistoryResponse,
  NarrativeCreateTemplateRequest,
  NarrativeCreateTemplateResponse,
  NarrativeEnding,
  NarrativeEndingDistributionResponse,
  NarrativePublicReplayResponse,
  NarrativeSessionListResponse,
  NarrativeStartSessionResponse,
  NarrativeStoryHistoryResponse,
  NarrativeTemplateListResponse,
  NarrativeTemplateSummary,
  NarrativeUpdateVisibilityRequest,
  PlaySessionCreateRequest,
  PlaySessionHistoryResponse,
  PlaySessionReplayResponse,
  PlaySessionSnapshot,
  PlayTurnRequest,
  PublishedStoryCard,
  PublishedStoryDetailResponse,
  PublishedStoryListResponse,
  StoryVisibility,
  UpdateStoryVisibilityRequest,
} from "./contracts"

export type FrontendApiClient = {
  getAuthSession(): Promise<AuthSessionResponse>
  loginAuth(request: AuthLoginRequest): Promise<AuthSessionResponse>
  logoutAuth(): Promise<void>
  getCurrentActor(): Promise<CurrentActorResponse>
  createStoryPreview(request: AuthorPreviewRequest): Promise<AuthorPreviewResponse>
  createAuthorJob(request: AuthorJobCreateRequest): Promise<AuthorJobStatusResponse>
  getAuthorJob(jobId: string): Promise<AuthorJobStatusResponse>
  streamAuthorJobEvents(jobId: string, lastEventId?: number): AsyncGenerator<AuthorJobEvent, void, void>
  getAuthorJobResult(jobId: string): Promise<AuthorJobResultResponse>
  publishAuthorJob(jobId: string, visibility?: StoryVisibility): Promise<PublishedStoryCard>
  listStories(params?: ListStoriesParams): Promise<PublishedStoryListResponse>
  listMyWorlds(params?: { limit?: number; cursor?: string | null }): Promise<PublishedStoryListResponse>
  getStory(storyId: string): Promise<PublishedStoryDetailResponse>
  updateStoryVisibility(storyId: string, request: UpdateStoryVisibilityRequest): Promise<PublishedStoryCard>
  deleteStory(storyId: string): Promise<DeleteStoryResponse>
  createPlaySession(request: PlaySessionCreateRequest): Promise<PlaySessionSnapshot>
  getPlaySession(sessionId: string): Promise<PlaySessionSnapshot>
  getPlaySessionHistory(sessionId: string): Promise<PlaySessionHistoryResponse>
  getPlaySessionReplay(sessionId: string): Promise<PlaySessionReplayResponse>
  submitPlayTurn(sessionId: string, request: PlayTurnRequest): Promise<PlaySessionSnapshot>

  // ---------- Narrative (template/session) ----------
  createNarrativeTemplate(request: NarrativeCreateTemplateRequest): Promise<NarrativeCreateTemplateResponse>
  listPublicNarrativeTemplates(): Promise<NarrativeTemplateListResponse>
  getNarrativeTemplate(templateId: string): Promise<NarrativeTemplateSummary>
  updateNarrativeTemplateVisibility(
    templateId: string,
    request: NarrativeUpdateVisibilityRequest,
  ): Promise<NarrativeTemplateSummary>
  startNarrativeSession(templateId: string): Promise<NarrativeStartSessionResponse>
  getNarrativeStory(sessionId: string): Promise<NarrativeStoryHistoryResponse>
  advanceNarrativeTurn(
    sessionId: string,
    request: NarrativeAdvanceTurnRequest,
  ): Promise<NarrativeAdvanceTurnResponse>
  askNarrativeAdvisor(
    sessionId: string,
    request: NarrativeAdvisorAskRequest,
  ): Promise<NarrativeAdvisorAskResponse>
  getNarrativeAdvisorHistory(sessionId: string): Promise<NarrativeAdvisorHistoryResponse>
  listMyNarrativeTemplates(): Promise<NarrativeTemplateListResponse>
  listMyNarrativeSessions(): Promise<NarrativeSessionListResponse>
  getNarrativeSessionEnding(sessionId: string): Promise<NarrativeEnding | null>
  getNarrativeEndingDistribution(
    templateId: string,
  ): Promise<NarrativeEndingDistributionResponse>
  getNarrativePublicReplay(sessionId: string): Promise<NarrativePublicReplayResponse>
}
