export type ErrorEnvelope = {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    request_id: string | null;
    details?: Record<string, unknown>;
  };
};

export type AdminLoginRequest = {
  email: string;
  password: string;
};

export type AdminUser = {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
};

export type AdminLoginResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_at: string;
  user: AdminUser;
};

export type StorySummary = {
  story_id: string;
  title: string;
  created_at: string;
  has_draft: boolean;
  latest_published_version: number | null;
  latest_published_at: string | null;
};

export type StoryListResponse = {
  stories: StorySummary[];
};

export type StoryDraftResponse = {
  story_id: string;
  title: string;
  created_at: string;
  draft_pack: Record<string, unknown>;
  latest_published_version: number | null;
  latest_published_at: string | null;
};

export type StoryDraftPatchChange = {
  target_type: 'story' | 'beat' | 'scene' | 'npc' | 'opening_guidance';
  field:
    | 'title'
    | 'description'
    | 'style_guard'
    | 'input_hint'
    | 'scene_seed'
    | 'red_line'
    | 'intro_text'
    | 'goal_hint'
    | 'starter_prompt_1'
    | 'starter_prompt_2'
    | 'starter_prompt_3';
  target_id?: string;
  value: string;
};

export type StoryDraftPatchRequest = {
  changes: StoryDraftPatchChange[];
};

export type StoryPublishResponse = {
  story_id: string;
  version: number;
  published_at: string;
};

export type AuthorRunStatus = 'pending' | 'running' | 'review_ready' | 'failed';

export type AuthorRunCreateRequest = {
  raw_brief: string;
};

export type AuthorRunCreateResponse = {
  story_id: string;
  run_id: string;
  status: AuthorRunStatus;
  created_at: string;
};



export type AuthorRunEventPayload = {
  event_id: string;
  node_name: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type AuthorRunEventsResponse = {
  run_id: string;
  events: AuthorRunEventPayload[];
};

export type AuthorRunArtifactSummary = {
  artifact_type: string;
  artifact_key: string;
  payload: Record<string, unknown>;
  updated_at: string;
};

export type AuthorRunGetResponse = {
  run_id: string;
  story_id: string;
  status: AuthorRunStatus;
  current_node: string | null;
  raw_brief: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  artifacts: AuthorRunArtifactSummary[];
};

export type AuthorStoryListItem = {
  story_id: string;
  title: string;
  created_at: string;
  latest_run_id: string | null;
  latest_run_status: string | null;
  latest_run_current_node: string | null;
  latest_run_updated_at: string | null;
  latest_published_version: number | null;
  latest_published_at: string | null;
};

export type AuthorStoryListResponse = {
  stories: AuthorStoryListItem[];
};

export type AuthorStoryGetResponse = {
  story_id: string;
  title: string;
  created_at: string;
  latest_run: AuthorRunGetResponse | null;
  latest_published_version: number | null;
  latest_published_at: string | null;
  draft_pack: Record<string, unknown>;
};

export type SessionPressureValue = {
  value: number;
  label: string;
};

export type SessionCrewSignal = {
  name: string;
  stance: string;
  label: string;
};

export type SessionStateSummary = {
  events: number;
  inventory: number;
  cost_total: number;
  pressure: {
    public_trust: SessionPressureValue;
    resource_stress: SessionPressureValue;
    coordination_noise: SessionPressureValue;
  };
  crew_signals: SessionCrewSignal[];
};

export type OpeningGuidance = {
  intro_text: string;
  goal_hint: string;
  starter_prompts: [string, string, string] | string[];
};

export type SessionCreateRequest = {
  story_id: string;
  version: number;
};

export type SessionCreateResponse = {
  session_id: string;
  story_id: string;
  version: number;
  scene_id: string;
  state_summary: SessionStateSummary;
  opening_guidance: OpeningGuidance;
};

export type SessionMeta = {
  session_id: string;
  scene_id: string;
  beat_progress: Record<string, unknown>;
  ended: boolean;
  state_summary: SessionStateSummary;
  opening_guidance: OpeningGuidance;
  state?: Record<string, unknown> | null;
};

export type SessionUiMove = {
  move_id: string;
  label: string;
  risk_hint: string;
};

export type SessionUi = {
  moves: SessionUiMove[];
  input_hint: string;
};

export type SessionStepRecognized = {
  interpreted_intent: string;
  move_id: string;
  confidence: number;
  route_source: 'button' | 'llm';
  llm_duration_ms?: number | null;
  llm_gateway_mode?: string | null;
};

export type SessionStepResult = {
  result: string;
  costs_summary: string;
  consequences_summary: string;
};

export type SessionStepDebugStance = {
  support: string[];
  oppose: string[];
  contested: string[];
  red_line_hits: string[];
};

export type SessionStepDebug = {
  selected_move: string;
  selected_outcome: string;
  selected_strategy_style: string;
  pressure_recoil_triggered: boolean;
  stance_snapshot: SessionStepDebugStance;
  state: Record<string, unknown>;
  beat_progress: Record<string, number>;
};

export type SessionStepRequest = {
  client_action_id: string;
  input:
    | { type: 'button'; move_id: string }
    | { type: 'text'; text: string };
  dev_mode?: boolean;
};

export type SessionStepResponse = {
  session_id: string;
  version: number;
  scene_id: string;
  narration_text: string;
  recognized: SessionStepRecognized;
  resolution: SessionStepResult;
  ui: SessionUi;
  debug?: SessionStepDebug | null;
};

export type SessionHistoryTurn = {
  turn_index: number;
  scene_id: string;
  narration_text: string;
  recognized: SessionStepRecognized;
  resolution: SessionStepResult;
  ui: SessionUi;
  ended: boolean;
};

export type SessionHistoryResponse = {
  session_id: string;
  history: SessionHistoryTurn[];
};
