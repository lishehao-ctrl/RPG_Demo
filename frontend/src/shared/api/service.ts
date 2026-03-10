import { apiClient } from '@/shared/api/client';
import type {
  AdminLoginRequest,
  AdminLoginResponse,
  AuthorRunCreateRequest,
  AuthorRunCreateResponse,
  AuthorRunEventsResponse,
  AuthorRunGetResponse,
  AuthorStoryGetResponse,
  AuthorStoryListResponse,
  SessionCreateRequest,
  SessionCreateResponse,
  SessionHistoryResponse,
  SessionMeta,
  SessionStepRequest,
  SessionStepResponse,
  StoryDraftPatchRequest,
  StoryDraftResponse,
  StoryListResponse,
  StoryPublishResponse,
} from '@/shared/api/types';

export const apiService = {
  login: (payload: AdminLoginRequest) =>
    apiClient.post<AdminLoginResponse>('/admin/auth/login', payload, { skipAuth: true }),
  listStories: () => apiClient.get<StoryListResponse>('/stories'),
  listAuthorStories: () => apiClient.get<AuthorStoryListResponse>('/author/stories'),
  getAuthorStory: (storyId: string) => apiClient.get<AuthorStoryGetResponse>(`/author/stories/${storyId}`),
  createAuthorRun: (payload: AuthorRunCreateRequest) => apiClient.post<AuthorRunCreateResponse>('/author/runs', payload),
  getAuthorRun: (runId: string) => apiClient.get<AuthorRunGetResponse>(`/author/runs/${runId}`),
  getAuthorRunEvents: (runId: string) => apiClient.get<AuthorRunEventsResponse>(`/author/runs/${runId}/events`),
  rerunAuthorStory: (storyId: string, payload: AuthorRunCreateRequest) => apiClient.post<AuthorRunCreateResponse>(`/author/stories/${storyId}/runs`, payload),
  getStoryDraft: (storyId: string) => apiClient.get<StoryDraftResponse>(`/stories/${storyId}/draft`),
  patchStoryDraft: (storyId: string, payload: StoryDraftPatchRequest) => apiClient.patch<StoryDraftResponse>(`/stories/${storyId}/draft`, payload),
  publishStory: (storyId: string) => apiClient.post<StoryPublishResponse>(`/stories/${storyId}/publish`, {}),
  createSession: (payload: SessionCreateRequest) => apiClient.post<SessionCreateResponse>('/sessions', payload),
  getSession: (sessionId: string, devMode = false) =>
    apiClient.get<SessionMeta>(`/sessions/${sessionId}${devMode ? '?dev_mode=true' : ''}`),
  getSessionHistory: (sessionId: string) => apiClient.get<SessionHistoryResponse>(`/sessions/${sessionId}/history`),
  stepSession: (sessionId: string, payload: SessionStepRequest) =>
    apiClient.post<SessionStepResponse>(`/sessions/${sessionId}/step`, payload),
};
