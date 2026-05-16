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

// ---------------------------------------------------------------------------
// Narrative — template/session architecture
// ---------------------------------------------------------------------------

export type NarrativeNPCLeverageOverNPC = {
  target_npc_id: string
  leverage: string
}

export type NarrativeCastMember = {
  character_id: string
  display_name: string
  role: string
  relation_to_protagonist: string
  hidden_objective?: string | null
  leverage_over_player?: string | null
  leverages_over_other_npcs?: NarrativeNPCLeverageOverNPC[]
}

export type NarrativePlayerGoal = {
  goal: string
  stakes: string
}

export type NarrativeFailureCondition = {
  label: string
  description: string
}

export type NarrativePlayerLeverageOverNPC = {
  npc_id: string
  leverage: string
}

export type NarrativePlayerRole = {
  role_id: string
  label: string
  public_persona: string
  hidden_objective: string
  leverages_over_npcs: NarrativePlayerLeverageOverNPC[]
  starting_assets: string[]
}

export type NarrativeNPCShift = "warmer" | "colder" | "steady" | "wary" | "broken"

export type NarrativeNPCPulse = {
  npc_id: string
  state: string
  shift: NarrativeNPCShift
  reason?: string | null
}

export type NarrativeStoryOption = {
  label: string
  hint: string
  // Short "memory handle" — 2-6 chars distilling the action so a
  // player can say "I picked X that turn" months later. Mirrors
  // backend `StoryOption.handle`. May be empty string when LLM
  // didn't emit one (older templates / failed parse).
  handle?: string
}

export type NarrativeStoryRole = "narrator" | "player"

export type NarrativeInventoryDelta = {
  added: string[]
  removed: string[]
  reason: string
}

export type NarrativeStoryMessage = {
  ord: number
  role: NarrativeStoryRole
  content: string
  options: NarrativeStoryOption[]
  chosen_option_index: number | null
  npc_pulse?: NarrativeNPCPulse[]
  inventory_delta?: NarrativeInventoryDelta | null
  diary?: string | null
}

export type NarrativeDifficulty = "story" | "gauntlet"
export type NarrativeEndingTier = "victory" | "compromised" | "collapsed"

export type NarrativeAdvisorRole = "player" | "advisor"

export type NarrativeAdvisorMessage = {
  ord: number
  role: NarrativeAdvisorRole
  content: string
}

export type NarrativeTemplateVisibility = "private" | "unlisted" | "public"

// Locale a template's narration / NPC dialogue is generated in. Set at
// template creation, immutable thereafter. Mirrors the backend
// `TemplateLanguage` literal in `rpg_backend/narrative/contracts.py`.
export type NarrativeTemplateLanguage = "zh" | "en"

export type NarrativeTemplateSummary = {
  template_id: string
  owner_user_id: string
  seed: string
  title: string
  cast: NarrativeCastMember[]
  advisor_persona: string
  player_goals?: NarrativePlayerGoal[]
  failure_conditions?: NarrativeFailureCondition[]
  player_role_options?: NarrativePlayerRole[]
  visibility: NarrativeTemplateVisibility
  language?: NarrativeTemplateLanguage
  play_count: number
  created_at: string
  is_owner: boolean
}

export type NarrativeSessionSummary = {
  session_id: string
  template_id: string
  template_title: string
  template_seed: string
  player_user_id: string
  turn_count: number
  turn_budget: number
  difficulty?: NarrativeDifficulty
  player_role?: NarrativePlayerRole | null
  ending_label: string | null
  ending_subtitle: string | null
  ending_tier?: NarrativeEndingTier | null
  early_terminated?: boolean
  created_at: string
  last_active_at: string
}

export type NarrativeHighlight = {
  beat_ord: number
  headline: string
  body_excerpt: string
  why_pivotal: string
}

export type NarrativeBranchHypothetical = {
  pivot_beat_ord: number
  chosen_path_summary: string
  alternate_path_summary: string
  alternate_ending_label: string
  alternate_ending_tier: NarrativeEndingTier
  rationale: string
}

export type NarrativeEnding = {
  label: string
  subtitle: string
  passage: string
  tier?: NarrativeEndingTier
  early_terminated?: boolean
  failure_trigger?: string | null
  highlights?: NarrativeHighlight[]
  branches?: NarrativeBranchHypothetical[]
}

export type NarrativeEndingDistributionEntry = {
  label: string
  count: number
}

export type NarrativeEndingDistributionResponse = {
  template_id: string
  total_completed: number
  entries: NarrativeEndingDistributionEntry[]
}

export type NarrativePublicReplayResponse = {
  session_id: string
  template_id: string
  template_forkable: boolean
  template_title: string
  template_seed: string
  cast: NarrativeCastMember[]
  advisor_persona: string
  player_goals?: NarrativePlayerGoal[]
  player_role?: NarrativePlayerRole | null
  turn_budget: number
  turn_count: number
  difficulty?: NarrativeDifficulty
  completed: boolean
  ending: NarrativeEnding | null
  messages: NarrativeStoryMessage[]
  advisor_messages: NarrativeAdvisorMessage[]
  created_at: string
}

export type NarrativeCreateTemplateRequest = {
  seed: string
  visibility?: NarrativeTemplateVisibility
  turn_budget?: number
  difficulty?: NarrativeDifficulty
  language?: NarrativeTemplateLanguage
}

export type NarrativeStartSessionRequest = {
  turn_budget?: number
  difficulty?: NarrativeDifficulty
  player_role_index?: number | null
}

export type NarrativeCreateTemplateResponse = {
  template: NarrativeTemplateSummary
  session: NarrativeSessionSummary
  opening: NarrativeStoryMessage
}

export type NarrativeStartSessionResponse = {
  template: NarrativeTemplateSummary
  session: NarrativeSessionSummary
  opening: NarrativeStoryMessage
}

export type NarrativeTemplateListResponse = {
  items: NarrativeTemplateSummary[]
}

export type NarrativeSessionListResponse = {
  items: NarrativeSessionSummary[]
}

export type NarrativeUpdateVisibilityRequest = {
  visibility: NarrativeTemplateVisibility
}

export type NarrativeStoryHistoryResponse = {
  template: NarrativeTemplateSummary
  session: NarrativeSessionSummary
  messages: NarrativeStoryMessage[]
}

export type NarrativeAdvanceTurnRequest = {
  chosen_option_index?: number | null
  free_input?: string | null
  diary?: string | null
}

export type NarrativeAdvanceTurnResponse = {
  player_message: NarrativeStoryMessage
  narrator_message: NarrativeStoryMessage
  ending: NarrativeEnding | null
  is_complete: boolean
}

export type NarrativeAdvisorAskRequest = {
  question: string
  oracle_mode?: boolean
}

export type NarrativeAdvisorAskResponse = {
  player_message: NarrativeAdvisorMessage
  advisor_message: NarrativeAdvisorMessage
  turn_budget_after?: number | null
  oracle_used?: boolean
}

export type NarrativeAdvisorHistoryResponse = {
  persona: string
  messages: NarrativeAdvisorMessage[]
}
