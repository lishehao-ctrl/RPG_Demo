export type FrontendApiError = {
  error: {
    code: string
    message: string
  }
}

export type AuthUserResponse = {
  user_id: string
  display_name: string
}

export type AuthSessionResponse = {
  authenticated: boolean
  user: AuthUserResponse | null
}

export type AuthLoginRequest = {
  username: string
}

export type CurrentActorResponse = {
  user_id: string
  display_name: string
  is_default: boolean
}

export type StoryShellId =
  | "wealth_families"
  | "entertainment_scandal"
  | "office_power"
  | "campus_romance"
  | "urban_supernatural"

export type PlayLengthPreset = "5_8" | "10_12" | "12_15" | "15_20" | "20_25" | "30_45"
export type TargetGenderPref = "male" | "female"
export type SeedFitMode = "direct_fit" | "soft_fit" | "out_of_range"

export type FocusedBrief = {
  story_kernel: string
  setting_signal: string
  core_conflict: string
  tone_signal: string
  hard_constraints: string[]
  forbidden_tones: string[]
}

export type NormalizedSeedPacket = {
  accepted_shell: StoryShellId
  fit_mode: SeedFitMode
  relationship_hook: string
  secret_hook: string
  surface_signal_ids: string[]
  surface_signal_summary: string
  target_visibility_summary: string
  rewritten_seed: string
  rewrite_reason: string
}

export type AuthorPreviewFlashcard = {
  card_id: string
  kind: "stable" | "draft"
  label: string
  value: string
}

export type AuthorLoadingCard = {
  card_id:
    | "theme"
    | "tone"
    | "structure"
    | "story_premise"
    | "story_stakes"
    | "cast_count"
    | "cast_anchor"
    | "beat_count"
    | "working_title"
    | "opening_beat"
    | "final_beat"
    | "generation_status"
    | "token_budget"
  emphasis: "stable" | "draft" | "live"
  label: string
  value: string
}

export type AuthorPreviewTheme = {
  primary_theme: string
  modifiers: string[]
  router_reason: string
}

export type AuthorPreviewStrategies = {
  story_frame_strategy: string
  cast_strategy: string
  beat_plan_strategy: string
}

export type AuthorPreviewStructure = {
  cast_topology: string
  expected_npc_count: number
  expected_beat_count: number
}

export type AuthorPreviewStory = {
  title: string
  premise: string
  tone: string
  stakes: string
  route_fantasy?: string | null
}

export type AuthorPreviewCastSlotSummary = {
  slot_label: string
  public_role: string
}

export type AuthorPreviewBeatSummary = {
  title: string
  goal: string
  milestone_kind: string
}

export type AuthorPreviewRequest = {
  prompt_seed: string
  random_seed?: number | null
  play_length_preset?: PlayLengthPreset | null
  target_gender_pref?: TargetGenderPref | null
}

export type AuthorPreviewResponse = {
  preview_id: string
  prompt_seed: string
  play_length_preset?: PlayLengthPreset | null
  normalized_seed?: NormalizedSeedPacket | null
  story_shell_id?: StoryShellId | null
  relationship_hook?: string | null
  secret_hook?: string | null
  surface_signal_ids: string[]
  surface_signal_summary?: string | null
  target_visibility_summary?: string | null
  focused_brief: FocusedBrief
  theme: AuthorPreviewTheme
  strategies: AuthorPreviewStrategies
  structure: AuthorPreviewStructure
  story: AuthorPreviewStory
  cast_slots: AuthorPreviewCastSlotSummary[]
  beats: AuthorPreviewBeatSummary[]
  flashcards: AuthorPreviewFlashcard[]
  stage: string
}

export type AuthorJobProgress = {
  stage: string
  stage_index: number
  stage_total: number
}

export type AuthorJobProgressSnapshot = {
  stage: string
  stage_label: string
  stage_index: number
  stage_total: number
  completion_ratio: number
  primary_theme: string
  cast_topology: string
  expected_npc_count: number
  expected_beat_count: number
  preview_title: string
  preview_premise: string
  flashcards: AuthorPreviewFlashcard[]
  loading_cards: AuthorLoadingCard[]
}

export type AuthorCacheMetrics = {
  session_cache_enabled: boolean
  cache_path_used: boolean
  total_call_count: number
  previous_response_call_count: number
  total_input_characters: number
  estimated_input_tokens_from_chars: number
  provider_usage: Record<string, number>
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  reasoning_tokens?: number | null
  cached_input_tokens?: number | null
  cache_hit_tokens?: number | null
  cache_write_tokens?: number | null
  cache_creation_input_tokens?: number | null
  cache_type?: string | null
  billing_type?: string | null
  cache_metrics_source: string
}

export type AuthorJobCreateRequest = {
  prompt_seed: string
  random_seed?: number | null
  preview_id?: string | null
  play_length_preset?: PlayLengthPreset | null
}

export type AuthorJobStatus = "queued" | "running" | "completed" | "failed"

export type AuthorJobStatusResponse = {
  job_id: string
  status: AuthorJobStatus
  prompt_seed: string
  preview: AuthorPreviewResponse
  progress: AuthorJobProgress
  progress_snapshot?: AuthorJobProgressSnapshot | null
  cache_metrics?: AuthorCacheMetrics | null
  error?: { code: string; message: string } | null
}

export type AuthorStorySummary = {
  title: string
  one_liner: string
  premise: string
  tone: string
  theme: string
  npc_count: number
  beat_count: number
}

export type AuthorJobResultResponse = {
  job_id: string
  status: AuthorJobStatus
  summary?: AuthorStorySummary | null
  bundle?: Record<string, unknown> | null
  progress_snapshot?: AuthorJobProgressSnapshot | null
  cache_metrics?: AuthorCacheMetrics | null
}

export type StoryVisibility = "private" | "unlisted" | "public"

export type PublishedStoryCard = {
  story_id: string
  title: string
  one_liner: string
  premise: string
  theme: string
  tone: string
  npc_count: number
  beat_count: number
  topology: string
  visibility: StoryVisibility
  viewer_can_manage: boolean
  published_at: string
  play_count: number
  unique_player_count: number
  ending_distribution: Record<string, number>
}

export type PublishedStoryListSort = "published_at_desc" | "relevance" | "play_count_desc"
export type PublishedStoryListView = "accessible" | "mine" | "public"

export type ListStoriesParams = {
  q?: string | null
  theme?: string | null
  view?: PublishedStoryListView | null
  limit?: number
  cursor?: string | null
  sort?: PublishedStoryListSort | null
}

export type PublishedStoryThemeFacet = {
  theme: string
  count: number
}

export type PublishedStoryListMeta = {
  query?: string | null
  theme?: string | null
  view: PublishedStoryListView
  sort: PublishedStoryListSort
  limit: number
  next_cursor?: string | null
  has_more: boolean
  total: number
}

export type PublishedStoryListFacets = {
  themes: PublishedStoryThemeFacet[]
}

export type PublishedStoryListResponse = {
  stories: PublishedStoryCard[]
  meta?: PublishedStoryListMeta | null
  facets?: PublishedStoryListFacets | null
}

export type PublishedStoryPresentation = {
  dossier_ref: string
  status: "open_for_play"
  status_label: string
  classification_label: string
  engine_label: string
  visibility: StoryVisibility
  viewer_can_manage: boolean
}

export type UpdateStoryVisibilityRequest = {
  visibility: StoryVisibility
}

export type DeleteStoryResponse = {
  story_id: string
  deleted: true
}

export type PublishedStoryPlayOverview = {
  protagonist: PlayProtagonist
  opening_narration: string
  runtime_profile: string
  runtime_profile_label: string
  play_length_preset?: PlayLengthPreset | null
  max_turns: number
}

export type PublishedStoryDetailResponse = {
  story: PublishedStoryCard
  preview: AuthorPreviewResponse
  presentation?: PublishedStoryPresentation | null
  play_overview?: PublishedStoryPlayOverview | null
}

export type PlayStoryMode = "legacy_civic" | "relationship_drama"
export type ControlTargetKind = "kind" | "event" | "character"
export type LatentEventKind = "relationship_debt" | "public_wave" | "secret_pressure" | "npc_action"
export type LatentRadarTrend = "rising" | "steady" | "cooling" | "triggered"

export type PlaySessionCreateRequest = {
  story_id: string
}

export type PlayTurnRequest = {
  input_text: string
  selected_suggestion_id?: string | null
  selected_story_action_id?: string | null
  selected_control_action_id?: string | null
  control_action?: "press" | "redirect" | "detonate" | "none"
  control_target_kind?: LatentEventKind | null
  control_target_id?: string | null
  control_target_mode?: ControlTargetKind | null
}

export type PlayStateBar = {
  bar_id: string
  label: string
  category: "axis" | "stance" | "global" | "relationship"
  current_value: number
  min_value: number
  max_value: number
}

export type PlaySuggestedAction = {
  suggestion_id: string
  action_type?: "story" | "control"
  label: string
  prompt: string
}

export type PlayControlAction = {
  action_id: string
  action_type: "press" | "redirect" | "detonate" | "none"
  target_mode?: ControlTargetKind | null
  target_kind?: LatentEventKind | null
  target_id?: string | null
  label: string
  prompt: string
}

export type PlayEnding = {
  ending_id: string
  label: string
  summary: string
}

export type PlayProtagonist = {
  title: string
  mandate: string
  identity_summary: string
  role_label?: string | null
  core_desire?: string | null
  hidden_risk?: string | null
}

export type PlaySuccessLedger = {
  proof_progress: number
  coalition_progress: number
  order_progress: number
  settlement_progress: number
}

export type PlayCostLedger = {
  public_cost: number
  relationship_cost: number
  procedural_cost: number
  coercion_cost: number
}

export type PlayFeedback = {
  ledgers: PlayLedgerSnapshot
  last_turn_axis_deltas: Record<string, number>
  last_turn_stance_deltas: Record<string, number>
  last_turn_global_deltas: Record<string, number>
  last_turn_relationship_deltas: Record<string, Record<string, number>>
  last_turn_tags: string[]
  last_turn_consequences: string[]
  last_turn_revealed_secret_ids: string[]
}

export type PlayLedgerSnapshot = {
  success: PlaySuccessLedger
  cost: PlayCostLedger
}

export type PlaySessionHistoryEntry = {
  speaker: "gm" | "player"
  text: string
  created_at: string
  turn_index: number
}

export type PlaySessionHistoryResponse = {
  session_id: string
  story_id: string
  entries: PlaySessionHistoryEntry[]
}

export type PlaySessionReplayResponse = {
  session_id: string
  story_id: string
  story_title: string
  completed: boolean
  completed_at: string | null
  final_narration: string
  ending: PlayEnding | null
  entries: PlaySessionHistoryEntry[]
}

export type PlaySessionProgress = {
  completed_beats: number
  total_beats: number
  current_beat_progress: number
  current_beat_goal: number
  turn_index: number
  max_turns: number
  completion_ratio: number
  display_percent: number
}

export type PlaySupportSurface = {
  enabled: boolean
  disabled_reason?: string | null
}

export type PlaySupportSurfaces = {
  inventory: PlaySupportSurface
  map: PlaySupportSurface
}

export type PlayLatentRadarItem = {
  kind: LatentEventKind
  pressure: number
  trend: LatentRadarTrend
  note: string
}

export type PlayRelationshipTargetState = {
  character_id: string
  name: string
  affection: number
  trust: number
  tension: number
  suspicion: number
  dependency: number
  is_route_focus: boolean
}

export type PlayRelationshipStateSnapshot = {
  scene_heat: number
  public_image: number
  secret_exposure: number
  route_lock: number
  current_route_target_id?: string | null
  targets: PlayRelationshipTargetState[]
}

export type PlaySessionSnapshot = {
  session_id: string
  story_id: string
  story_mode: PlayStoryMode
  story_shell_id?: StoryShellId | null
  status: "active" | "completed" | "expired"
  turn_index: number
  beat_index: number
  beat_title: string
  story_title: string
  narration: string
  protagonist?: PlayProtagonist | null
  feedback?: PlayFeedback | null
  progress?: PlaySessionProgress | null
  support_surfaces?: PlaySupportSurfaces | null
  state_bars: PlayStateBar[]
  current_route_target_id?: string | null
  relationship_state?: PlayRelationshipStateSnapshot | null
  suggested_actions: PlaySuggestedAction[]
  story_actions?: PlaySuggestedAction[]
  control_actions?: PlayControlAction[]
  latent_radar: PlayLatentRadarItem[]
  ending?: PlayEnding | null
}

export type AuthorJobEventName =
  | "job_created"
  | "job_started"
  | "stage_changed"
  | "job_completed"
  | "job_failed"

export type AuthorJobEvent = {
  id: number
  event: AuthorJobEventName
  data: Record<string, unknown>
}
