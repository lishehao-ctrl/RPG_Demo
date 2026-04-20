import {
  AuthLoginRequest,
  AuthRegisterRequest,
  AuthSessionResponse,
  AuthorJobCreateRequest,
  AuthorJobEvent,
  AuthorJobProgressSnapshot,
  AuthorJobResultResponse,
  AuthorJobStatusResponse,
  AuthorLoadingCard,
  AuthorPreviewRequest,
  AuthorPreviewResponse,
  AuthorPreviewFlashcard,
  AuthorStorySummary,
  CurrentActorResponse,
  DeleteStoryResponse,
  ListStoriesParams,
  PlayEnding,
  PlayFeedback,
  PlayLengthPreset,
  PlayProtagonist,
  PlaySessionHistoryEntry,
  PlaySessionHistoryResponse,
  PlaySessionProgress,
  PlaySessionCreateRequest,
  PlaySessionSnapshot,
  PlayStateBar,
  StoryShellId,
  PlaySuggestedAction,
  PlaySupportSurfaces,
  PlayTurnRequest,
  PublishedStoryCard,
  PublishedStoryDetailResponse,
  PublishedStoryListResponse,
  PublishedStoryListSort,
  PublishedStoryListView,
  TargetGenderPref,
  UpdateStoryVisibilityRequest,
} from "./contracts"
import type { FrontendApiClient } from "./client"

type PlaceholderActor = {
  user_id: string
  display_name: string
  email: string
  password: string
}

const AUTHOR_STAGE_FLOW = [
  "queued",
  "running",
  "brief_parsed",
  "brief_classified",
  "story_frame_ready",
  "theme_confirmed",
  "cast_planned",
  "cast_ready",
  "beat_plan_ready",
  "route_ready",
  "ending_ready",
  "completed",
] as const

const STAGE_LABELS: Record<(typeof AUTHOR_STAGE_FLOW)[number], string> = {
  queued: "等待开始",
  running: "正在编译",
  brief_parsed: "种子已解析",
  brief_classified: "案卷已归档",
  story_frame_ready: "故事骨架已成形",
  theme_confirmed: "主题已确认",
  cast_planned: "人物已规划",
  cast_ready: "角色已就位",
  beat_plan_ready: "章节已排布",
  route_ready: "路线已就绪",
  ending_ready: "结局已成形",
  completed: "已完成",
}

const THEME_LABELS: Record<string, string> = {
  wealth_families: "豪门丑闻",
  entertainment_scandal: "热搜失控",
  office_power: "董事会修罗场",
  campus_romance: "校园修罗场",
  urban_supernatural: "夜色契约",
}

const DEMO_STORIES: PublishedStoryCard[] = [
  {
    story_id: "demo-story-1",
    title: "华丽陷阱",
    one_liner: "在顶层酒会上，未婚夫、旧爱和掌握遗嘱的人同时逼她站队。",
    premise: "在城市天际线之上，一场豪门联姻正在变成所有人都会失控的公开试炼。",
    theme: "豪门丑闻",
    tone: "都市绯闻黑色戏",
    npc_count: 5,
    beat_count: 4,
    topology: "5-figure scandal web",
    visibility: "public",
    viewer_can_manage: false,
    published_at: new Date().toISOString(),
  },
  {
    story_id: "demo-story-2",
    title: "谁先失控",
    one_liner: "董事会前夜，黑账、暧昧和站队把所有体面都逼到边缘。",
    premise: "在落地窗后的会议室里，最危险的从来不是并购，而是谁会先在公开场合失控。",
    theme: "董事会修罗场",
    tone: "都市高压关系戏",
    npc_count: 5,
    beat_count: 4,
    topology: "4-route power ring",
    visibility: "public",
    viewer_can_manage: false,
    published_at: new Date().toISOString(),
  },
]

type PlaceholderAuthorJob = {
  jobId: string
  promptSeed: string
  preview: AuthorPreviewResponse
  createdAtMs: number
  publishedStoryId?: string
}

type PlaceholderPlaySession = {
  sessionId: string
  storyId: string
  storyTitle: string
  storyShellId: StoryShellId | null
  ownerUserId: string
  turnIndex: number
  beatIndex: number
  history: PlaySessionHistoryEntry[]
  protagonist: PlayProtagonist
  feedback: PlayFeedback
  stateBars: PlayStateBar[]
  suggestedActions: PlaySuggestedAction[]
  narration: string
  ending: PlayEnding | null
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
}

function relevanceScore(story: PublishedStoryCard, query: string): number {
  const lowered = query.toLowerCase()
  const fields = [
    { value: story.title, weight: 6 },
    { value: story.one_liner, weight: 4 },
    { value: story.premise, weight: 3 },
    { value: story.theme, weight: 2 },
    { value: story.tone, weight: 1 },
  ]
  return fields.reduce((score, field) => {
    return score + (field.value.toLowerCase().includes(lowered) ? field.weight : 0)
  }, 0)
}

function listStoriesResponse(
  stories: PublishedStoryCard[],
  params: ListStoriesParams = {},
): PublishedStoryListResponse {
  const query = params.q?.trim() || null
  const theme = params.theme?.trim() || null
  const view: PublishedStoryListView = params.view ?? "accessible"
  const limit = params.limit ?? 20
  const sort: PublishedStoryListSort = params.sort ?? (query ? "relevance" : "published_at_desc")
  const offset = Number.parseInt(params.cursor ?? "0", 10)
  const normalizedOffset = Number.isFinite(offset) && offset > 0 ? offset : 0

  let filteredStories = [...stories]
  if (query) {
    filteredStories = filteredStories.filter((story) =>
      [story.title, story.one_liner, story.premise, story.theme, story.tone].some((value) =>
        value.toLowerCase().includes(query.toLowerCase()),
      ),
    )
  }

  const themeFacets = Array.from(
    filteredStories.reduce((counts, story) => {
      counts.set(story.theme, (counts.get(story.theme) ?? 0) + 1)
      return counts
    }, new Map<string, number>()),
  )
    .map(([facetTheme, count]) => ({ theme: facetTheme, count }))
    .sort((left, right) => right.count - left.count || left.theme.localeCompare(right.theme))

  if (theme) {
    filteredStories = filteredStories.filter((story) => story.theme.toLowerCase() === theme.toLowerCase())
  }

  filteredStories.sort((left, right) => {
    if (sort === "relevance" && query) {
      const scoreDelta = relevanceScore(right, query) - relevanceScore(left, query)
      if (scoreDelta !== 0) {
        return scoreDelta
      }
    }
    return new Date(right.published_at).getTime() - new Date(left.published_at).getTime()
  })

  const total = filteredStories.length
  const pageStories = filteredStories.slice(normalizedOffset, normalizedOffset + limit)
  const nextCursor = normalizedOffset + limit < total ? String(normalizedOffset + limit) : null

  return {
    stories: pageStories,
    meta: {
      query,
      theme,
      view,
      sort,
      limit,
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
      total,
    },
    facets: {
      themes: themeFacets,
    },
  }
}

function classifyTheme(seed: string): { id: string; label: string } {
  const haystack = seed.toLowerCase()
  if (/(豪门|继承|婚礼|订婚|家宴|遗嘱|heir|wedding|gala)/.test(haystack)) {
    return { id: "wealth_families", label: THEME_LABELS.wealth_families }
  }
  if (/(直播|热搜|顶流|经纪人|celebrity|livestream|scandal)/.test(haystack)) {
    return { id: "entertainment_scandal", label: THEME_LABELS.entertainment_scandal }
  }
  if (/(董事会|并购|上司|秘书|法务|boardroom|office|merger)/.test(haystack)) {
    return { id: "office_power", label: THEME_LABELS.office_power }
  }
  if (/(校庆|奖学金|社团|前任|campus|graduation|student)/.test(haystack)) {
    return { id: "campus_romance", label: THEME_LABELS.campus_romance }
  }
  return { id: "urban_supernatural", label: THEME_LABELS.urban_supernatural }
}

function genderPrefLabel(targetGenderPref?: TargetGenderPref | null): string | null {
  if (targetGenderPref === "male") {
    return "男性角色优先"
  }
  if (targetGenderPref === "female") {
    return "女性角色优先"
  }
  return null
}

function buildPreview(
  seed: string,
  playLengthPreset: PlayLengthPreset = "12_15",
  targetGenderPref?: TargetGenderPref | null,
): AuthorPreviewResponse {
  const theme = classifyTheme(seed)
  const previewId = crypto.randomUUID()
  const title =
    theme.id === "wealth_families"
      ? "华丽陷阱"
      : theme.id === "entertainment_scandal"
        ? "热搜之前"
        : theme.id === "office_power"
          ? "谁先失控"
          : theme.id === "campus_romance"
            ? "风口恋人"
            : "夜色契约"
  const premise =
    theme.id === "wealth_families"
      ? "在顶层酒会和家族体面之间，她必须在联姻、旧爱和继承秘密之间做出会毁掉所有关系的选择。"
      : theme.id === "entertainment_scandal"
        ? "在镜头和热搜同时逼近的夜里，隐恋、黑料和事业版图正在争夺同一场失控。"
        : theme.id === "office_power"
          ? "董事会前夜，黑账、暧昧和职位交易让每一句安慰都可能变成公开站队。"
          : theme.id === "campus_romance"
            ? "校庆晚会之前，奖学金、前任回归和旧录音把所有青涩都逼成名利场试炼。"
            : "城市夜色之下，危险契约、旧债和诱人的知情者让体面逐渐脱轨。"
  const tone =
    theme.id === "office_power"
      ? "都市高压关系戏"
      : theme.id === "entertainment_scandal"
        ? "奢华绯闻漩涡"
        : "都市绯闻黑色戏"
  const routeFantasy =
    theme.id === "wealth_families"
      ? "卷入联姻、继承与旧爱回归的豪门修罗场。"
      : theme.id === "entertainment_scandal"
        ? "在热搜、偷拍与绯闻发酵中站队、心动与反转。"
        : theme.id === "office_power"
          ? "在权力、暧昧和背刺之间选边站队。"
          : theme.id === "campus_romance"
            ? "在心动、误会与公开站队里推进一段校园关系失控。"
            : "在都市异能与危险秘密里推进关系反转和命运锁定。"
  const relationshipHook =
    theme.id === "wealth_families"
      ? "订婚夜上，旧爱与现任都试图逼你先给出站队信号。"
      : theme.id === "entertainment_scandal"
        ? "镜头外的暧昧关系正在追上镜头里的体面人设。"
        : theme.id === "office_power"
          ? "升职、暧昧与黑账让每一句示好都像勒索。"
          : theme.id === "campus_romance"
            ? "奖学金、旧录音和回归前任把心动推向公开修罗场。"
            : "危险契约把亲密和求生绑在同一根线上。"
  const secretHook =
    theme.id === "wealth_families"
      ? "遗嘱和旧情的重叠，让每个人都知道今晚会有人失态。"
      : theme.id === "entertainment_scandal"
        ? "偷拍视频一旦流出，任何保护都可能反过来变成实锤。"
        : theme.id === "office_power"
          ? "有人握着黑账，也有人握着你真正不敢公开的关系。"
          : theme.id === "campus_romance"
            ? "那份旧录音会把每个人真正的欲望一把拖到台前。"
            : "契约条款和旧债一起逼近，秘密迟早要挑一个先爆。"
  const surfaceSignalIds =
    theme.id === "wealth_families"
      ? ["heir", "gala", "legacy"]
      : theme.id === "entertainment_scandal"
        ? ["hot_search", "camera", "agency"]
        : theme.id === "office_power"
          ? ["boardroom", "audit", "merger"]
          : theme.id === "campus_romance"
            ? ["campus", "scholarship", "recording"]
            : ["contract", "night_city", "secret"]
  const surfaceSignalSummary =
    theme.id === "wealth_families"
      ? "豪门、遗嘱、家宴和旧爱回潮构成这份案卷的公开表层。"
      : theme.id === "entertainment_scandal"
        ? "热搜、偷拍视频、经纪约和失控公关构成这份案卷的表层噪音。"
        : theme.id === "office_power"
          ? "董事会、并购、法务与暧昧站队构成这份案卷的高压表层。"
          : theme.id === "campus_romance"
            ? "校庆、奖学金、社团站队和旧录音构成这份案卷的校园表层。"
            : "夜色、契约、异能与旧债构成这份案卷的危险表层。"
  const targetVisibilitySummary =
    theme.id === "wealth_families"
      ? "适合在高可见、高社交压力的场域中推进关系失控。"
      : theme.id === "entertainment_scandal"
        ? "适合在镜头、舆论和公开误读持续放大的场域中推进剧情。"
        : theme.id === "office_power"
          ? "适合在办公室、会议室和权力边界模糊的场域中推进剧情。"
          : theme.id === "campus_romance"
            ? "适合在校园半公开关系网络里逐步放大误会与站队。"
            : "适合在夜色和秘密空间交替切换的场域中推进命运转折。"
  const flashcards: AuthorPreviewFlashcard[] = [
    { card_id: "theme", kind: "stable", label: "Theme", value: theme.label },
    { card_id: "tone", kind: "stable", label: "Tone", value: tone },
    {
      card_id: "npc_count",
      kind: "stable",
      label: "NPC Count",
      value: playLengthPreset === "30_45" ? "7" : playLengthPreset === "20_25" ? "6" : "5",
    },
    {
      card_id: "beat_count",
      kind: "stable",
      label: "Beat Count",
      value: playLengthPreset === "30_45" ? "8" : playLengthPreset === "20_25" ? "6" : playLengthPreset === "15_20" ? "5" : "4",
    },
    { card_id: "cast_topology", kind: "stable", label: "Cast Structure", value: theme.id === "office_power" ? "4-route power ring" : "5-figure scandal web" },
    { card_id: "route_fantasy", kind: "draft", label: "路线幻想", value: routeFantasy },
    { card_id: "title", kind: "draft", label: "Working Title", value: title },
    { card_id: "conflict", kind: "draft", label: "Core Conflict", value: seed.slice(0, 140) },
  ]
  const genderPreference = genderPrefLabel(targetGenderPref)
  if (genderPreference) {
    flashcards.splice(2, 0, {
      card_id: "target_gender_pref",
      kind: "stable",
      label: "角色偏好",
      value: genderPreference,
    })
  }
  return {
    preview_id: previewId,
    prompt_seed: seed,
    play_length_preset: playLengthPreset,
    normalized_seed: {
      accepted_shell: theme.id as StoryShellId,
      fit_mode: "soft_fit",
      relationship_hook: relationshipHook,
      secret_hook: secretHook,
      surface_signal_ids: surfaceSignalIds,
      surface_signal_summary: surfaceSignalSummary,
      target_visibility_summary: targetVisibilitySummary,
      rewritten_seed: seed,
      rewrite_reason: "placeholder_relationship_drama_router",
    },
    story_shell_id: theme.id as StoryShellId,
    relationship_hook: relationshipHook,
    secret_hook: secretHook,
    surface_signal_ids: surfaceSignalIds,
    surface_signal_summary: surfaceSignalSummary,
    target_visibility_summary: targetVisibilitySummary,
    focused_brief: {
      story_kernel: seed.slice(0, 120),
      setting_signal: surfaceSignalSummary,
      core_conflict: relationshipHook,
      tone_signal: tone,
      hard_constraints: [],
      forbidden_tones: [],
    },
    theme: {
      primary_theme: theme.id,
      modifiers: targetGenderPref ? [playLengthPreset, targetGenderPref] : [playLengthPreset],
      router_reason: "placeholder_relationship_drama_router",
    },
    strategies: {
      story_frame_strategy: "placeholder_issue_story",
      cast_strategy: "placeholder_issue_cast",
      beat_plan_strategy: "placeholder_issue_beats",
    },
    structure: {
      cast_topology: theme.id === "office_power" ? "four_route_ring" : "five_figure_web",
      expected_npc_count: playLengthPreset === "30_45" ? 7 : playLengthPreset === "20_25" ? 6 : 5,
      expected_beat_count: playLengthPreset === "30_45" ? 8 : playLengthPreset === "20_25" ? 6 : playLengthPreset === "15_20" ? 5 : 4,
    },
    story: {
      title,
      premise,
      tone,
      stakes: "如果这间屋子在公众面前彻底失控，体面、欲望和筹码都会一起坍塌。",
      route_fantasy: routeFantasy,
    },
    cast_slots: [
      { slot_label: "苏清", public_role: "被所有人盯着的体面中心" },
      { slot_label: "陆衍", public_role: "握着筹码却仍想护住她的人" },
      { slot_label: "陈维", public_role: "知道太多、也最会逼人失态的对手" },
      { slot_label: "赵夫人", public_role: "一句话就能让整个房间改风向的人" },
      ...(playLengthPreset === "20_25" ? [{ slot_label: "江野", public_role: "只要开口，就能把所有人一起拖下水的见证者" }] : []),
      ...(playLengthPreset === "30_45"
        ? [
            { slot_label: "江野", public_role: "只要开口，就能把所有人一起拖下水的见证者" },
            { slot_label: "周岚", public_role: "在沉默里改写局势顺位的终盘变量" },
            { slot_label: "韩砚", public_role: "握着旧案补证、随时改写叙事归因的迟到仲裁者" },
          ]
        : []),
    ],
    beats: [
      { title: "暗流初起", goal: "先看清谁已经悄悄把背叛写进表情里。", milestone_kind: "reveal" },
      { title: "公众压力", goal: "别让这间屋子太早变成公开羞辱的现场。", milestone_kind: "containment" },
      { title: "秘密转折", goal: "逼那份一直躲在暗处的筹码见光。", milestone_kind: "commitment" },
      ...(playLengthPreset !== "5_8" ? [{ title: "最终引爆", goal: "决定谁能带着筹码离场，谁又要独自烧毁。", milestone_kind: "exposure" }] : []),
      ...(playLengthPreset === "30_45"
        ? [
            { title: "误判放大", goal: "让错判在公开语境里滚成第一轮损耗。", milestone_kind: "misread" },
            { title: "连段压迫", goal: "把让步成本和拒绝升级写成连续账本。", milestone_kind: "pressure" },
            { title: "反手回收", goal: "在高压段里完成一次可见的权柄换手。", milestone_kind: "reversal" },
            { title: "终盘结算", goal: "公开结算谁付代价、谁拿控制权。", milestone_kind: "resolution" },
          ]
        : []),
    ],
    flashcards,
    stage: "brief_parsed",
  }
}

function progressSnapshot(preview: AuthorPreviewResponse, stage: string, stageIndex: number): AuthorJobProgressSnapshot {
  const normalizedStage = stage as (typeof AUTHOR_STAGE_FLOW)[number]
  const loadingCards: AuthorLoadingCard[] = [
    { card_id: "theme", emphasis: "stable", label: "Theme", value: THEME_LABELS[preview.theme.primary_theme] ?? preview.theme.primary_theme },
    { card_id: "structure", emphasis: "stable", label: "Story Shape", value: preview.structure.cast_topology.replace(/_/g, " ") },
  ]
  if (stageIndex >= 5) {
    loadingCards.push(
      { card_id: "working_title", emphasis: "draft", label: "Working Title", value: preview.story.title },
      { card_id: "tone", emphasis: "stable", label: "Tone", value: preview.story.tone },
      { card_id: "story_premise", emphasis: "draft", label: "Story Premise", value: preview.story.premise },
      { card_id: "story_stakes", emphasis: "draft", label: "Story Stakes", value: preview.story.stakes },
    )
  }
  if (stageIndex >= 7) {
    loadingCards.push(
      { card_id: "cast_count", emphasis: "stable", label: "NPC Count", value: `已编入 ${preview.structure.expected_npc_count} 位人物` },
      { card_id: "cast_anchor", emphasis: "draft", label: "Cast Anchor", value: `${preview.cast_slots[0]?.slot_label ?? "苏清"} · ${preview.cast_slots[0]?.public_role ?? "人物锚点"}` },
    )
  }
  if (stageIndex >= 9) {
    loadingCards.push(
      { card_id: "beat_count", emphasis: "stable", label: "Beat Count", value: `已编排 ${preview.structure.expected_beat_count} 章` },
      { card_id: "opening_beat", emphasis: "draft", label: "Opening Beat", value: `${preview.beats[0]?.title ?? "暗流初起"}：${preview.beats[0]?.goal ?? "先看清谁已经悄悄把背叛写进表情里。"}` },
      {
        card_id: "final_beat",
        emphasis: "draft",
        label: "Final Beat",
        value: `${preview.beats[preview.beats.length - 1]?.title ?? "最终引爆"}：${preview.beats[preview.beats.length - 1]?.goal ?? "决定谁能带着筹码离场，谁又要独自烧毁。"}`,
      },
    )
  }
  const totalTokens = 1200 + stageIndex * 420
  const estimatedUsd = (0.000141 * (totalTokens / 300)).toFixed(6)
  loadingCards.push(
    { card_id: "generation_status", emphasis: "live", label: "Generation Status", value: STAGE_LABELS[normalizedStage] ?? stage },
    { card_id: "token_budget", emphasis: "live", label: "Token Budget", value: `${totalTokens} 枚词元 · 约 ${estimatedUsd} 美元` },
  )
  return {
    stage,
    stage_label: STAGE_LABELS[normalizedStage] ?? stage,
    stage_index: stageIndex,
    stage_total: AUTHOR_STAGE_FLOW.length,
    completion_ratio: Number((stageIndex / AUTHOR_STAGE_FLOW.length).toFixed(3)),
    primary_theme: preview.theme.primary_theme,
    cast_topology: preview.structure.cast_topology,
    expected_npc_count: preview.structure.expected_npc_count,
    expected_beat_count: preview.structure.expected_beat_count,
    preview_title: preview.story.title,
    preview_premise: preview.story.premise,
    flashcards: preview.flashcards,
    loading_cards: loadingCards,
  }
}

function stageForJob(createdAtMs: number): { status: AuthorJobStatusResponse["status"]; stage: string; stageIndex: number } {
  const elapsed = Date.now() - createdAtMs
  const index = Math.min(Math.floor(elapsed / 1200), AUTHOR_STAGE_FLOW.length - 1)
  const stage = AUTHOR_STAGE_FLOW[index]
  if (stage === "queued") return { status: "queued", stage, stageIndex: 1 }
  if (stage === "completed") return { status: "completed", stage, stageIndex: AUTHOR_STAGE_FLOW.length }
  return { status: "running", stage, stageIndex: index + 1 }
}

function summaryFromPreview(preview: AuthorPreviewResponse): AuthorStorySummary {
  return {
    title: preview.story.title,
    one_liner: preview.story.premise.slice(0, 220),
    premise: preview.story.premise,
    tone: preview.story.tone,
    theme: THEME_LABELS[preview.theme.primary_theme] ?? preview.theme.primary_theme,
    npc_count: preview.structure.expected_npc_count,
    beat_count: preview.structure.expected_beat_count,
  }
}

function buildPlaySnapshot(session: PlaceholderPlaySession): PlaySessionSnapshot {
  const progress: PlaySessionProgress = {
    completed_beats: Math.max(0, session.beatIndex - 1),
    total_beats: 3,
    current_beat_progress: session.ending ? 1 : Math.min(1, session.turnIndex === 0 ? 0 : 1),
    current_beat_goal: 1,
    turn_index: session.turnIndex,
    max_turns: 4,
    completion_ratio: session.ending ? 1 : Number((((Math.max(0, session.beatIndex - 1) + Math.min(1, session.turnIndex === 0 ? 0 : 1)) / 3)).toFixed(3)),
    display_percent: session.ending ? 100 : Math.round(((Math.max(0, session.beatIndex - 1) + Math.min(1, session.turnIndex === 0 ? 0 : 1)) / 3) * 100),
  }
  const supportSurfaces: PlaySupportSurfaces = {
    inventory: {
      enabled: false,
      disabled_reason: "Inventory is not authored for this placeholder runtime yet.",
    },
    map: {
      enabled: false,
      disabled_reason: "Map data is not available for this placeholder runtime yet.",
    },
  }
  return {
    session_id: session.sessionId,
    story_id: session.storyId,
    story_mode: "relationship_drama",
    story_shell_id: session.storyShellId,
    status: session.ending ? "completed" : "active",
    turn_index: session.turnIndex,
    beat_index: session.beatIndex,
    beat_title: ["Opening Pressure", "Public Strain", "Final Settlement"][session.beatIndex - 1] ?? "Final Settlement",
    story_title: session.storyTitle,
    narration: session.narration,
    protagonist: session.protagonist,
    feedback: session.feedback,
    progress,
    support_surfaces: supportSurfaces,
    state_bars: session.stateBars,
    current_route_target_id: null,
    relationship_state: null,
    suggested_actions: session.ending ? [] : session.suggestedActions,
    story_actions: session.ending ? [] : session.suggestedActions,
    control_actions: [],
    latent_radar: [],
    ending: session.ending,
  }
}

function nextEndingForStory(storyTitle: string, turnIndex: number): PlayEnding | null {
  if (turnIndex < 4) return null
  if (/blind/i.test(storyTitle)) {
    return { ending_id: "collapse", label: "Collapse", summary: "The crisis outruns coordination." }
  }
  if (/ledger|record/i.test(storyTitle)) {
    return { ending_id: "pyrrhic", label: "Pyrrhic Outcome", summary: "The truth holds, but at a steep civic cost." }
  }
  return { ending_id: "mixed", label: "Mixed Outcome", summary: "The city stabilizes, but not cleanly." }
}

export function createPlaceholderApiClient(): FrontendApiClient {
  const previews = new Map<string, AuthorPreviewResponse>()
  const jobs = new Map<string, PlaceholderAuthorJob>()
  const stories = new Map<string, PublishedStoryCard>()
  const storyPreviews = new Map<string, AuthorPreviewResponse>()
  const sessions = new Map<string, PlaceholderPlaySession>()
  const storyOwners = new Map<string, string>()
  const users = new Map<string, PlaceholderActor>()
  let currentUser: PlaceholderActor | null = null

  for (const story of DEMO_STORIES) {
    stories.set(story.story_id, story)
    storyPreviews.set(story.story_id, buildPreview(story.one_liner))
    storyOwners.set(story.story_id, "public-demo")
  }

  const buildAuthSession = (): AuthSessionResponse => ({
    authenticated: currentUser !== null,
    user: currentUser
      ? {
          user_id: currentUser.user_id,
          display_name: currentUser.display_name,
          email: currentUser.email,
        }
      : null,
  })

  return {
    async getAuthSession() {
      return buildAuthSession()
    },

    async registerAuth(request) {
      const email = request.email.trim().toLowerCase()
      if (users.has(email)) {
        throw new Error("An account with that email already exists.")
      }
      currentUser = {
        user_id: crypto.randomUUID(),
        display_name: request.display_name.trim(),
        email,
        password: request.password,
      }
      users.set(email, currentUser)
      return buildAuthSession()
    },

    async loginAuth(request) {
      const email = request.email.trim().toLowerCase()
      const user = users.get(email)
      if (!user || user.password !== request.password) {
        throw new Error("Invalid email or password.")
      }
      currentUser = user
      return buildAuthSession()
    },

    async logoutAuth() {
      currentUser = null
    },

    async getCurrentActor() {
      if (!currentUser) {
        throw new Error("需要先登录。")
      }
      return {
        user_id: currentUser.user_id,
        display_name: currentUser.display_name,
        email: currentUser.email,
        is_default: false,
      }
    },

    async createStoryPreview(request) {
      const preview = buildPreview(
        request.prompt_seed,
        request.play_length_preset ?? "12_15",
        request.target_gender_pref ?? null,
      )
      previews.set(preview.preview_id, preview)
      return preview
    },

    async createAuthorJob(request) {
      const preview = request.preview_id
        ? previews.get(request.preview_id) ?? buildPreview(request.prompt_seed, request.play_length_preset ?? "12_15")
        : buildPreview(request.prompt_seed, request.play_length_preset ?? "12_15")
      const jobId = crypto.randomUUID()
      jobs.set(jobId, {
        jobId,
        promptSeed: request.prompt_seed,
        preview,
        createdAtMs: Date.now(),
      })
      return this.getAuthorJob(jobId)
    },

    async getAuthorJob(jobId) {
      const job = jobs.get(jobId)
      if (!job) throw new Error(`Unknown placeholder job ${jobId}`)
      const stageState = stageForJob(job.createdAtMs)
      return {
        job_id: job.jobId,
        status: stageState.status,
        prompt_seed: job.promptSeed,
        preview: job.preview,
        progress: {
          stage: stageState.stage,
          stage_index: stageState.stageIndex,
          stage_total: AUTHOR_STAGE_FLOW.length,
        },
        progress_snapshot: progressSnapshot(job.preview, stageState.stage, stageState.stageIndex),
        cache_metrics: {
          session_cache_enabled: false,
          cache_path_used: false,
          total_call_count: stageState.stageIndex,
          previous_response_call_count: Math.max(0, stageState.stageIndex - 1),
          total_input_characters: job.promptSeed.length,
          estimated_input_tokens_from_chars: Math.ceil(job.promptSeed.length / 4),
          provider_usage: {},
          total_tokens: 1200 + stageState.stageIndex * 420,
          cache_metrics_source: "placeholder",
        },
        error: stageState.status === "failed" ? { code: "placeholder_job_failed", message: "Placeholder job failed." } : null,
      }
    },

    async *streamAuthorJobEvents(jobId, lastEventId = 0) {
      const stages = AUTHOR_STAGE_FLOW.slice(Math.max(0, lastEventId))
      let eventId = lastEventId
      for (const stage of stages) {
        eventId += 1
        const job = await this.getAuthorJob(jobId)
        yield {
          id: eventId,
          event: stage === "completed" ? "job_completed" : eventId === 1 ? "job_started" : "stage_changed",
          data: {
            job_id: job.job_id,
            status: stage === "completed" ? "completed" : "running",
            progress_snapshot: progressSnapshot(job.preview, stage, Math.min(eventId + 1, AUTHOR_STAGE_FLOW.length)),
          },
        }
      }
    },

    async getAuthorJobResult(jobId) {
      const job = jobs.get(jobId)
      if (!job) throw new Error(`Unknown placeholder job ${jobId}`)
      const stageState = stageForJob(job.createdAtMs)
      return {
        job_id: jobId,
        status: stageState.status,
        summary: stageState.status === "completed" ? summaryFromPreview(job.preview) : null,
        bundle: stageState.status === "completed" ? { story_bible: { title: job.preview.story.title } } : null,
        progress_snapshot: progressSnapshot(job.preview, stageState.stage, stageState.stageIndex),
        cache_metrics: {
          session_cache_enabled: false,
          cache_path_used: false,
          total_call_count: stageState.stageIndex,
          previous_response_call_count: Math.max(0, stageState.stageIndex - 1),
          total_input_characters: job.promptSeed.length,
          estimated_input_tokens_from_chars: Math.ceil(job.promptSeed.length / 4),
          provider_usage: {},
          total_tokens: 1200 + stageState.stageIndex * 420,
          cache_metrics_source: "placeholder",
        },
      }
    },

    async publishAuthorJob(jobId, visibility = "private") {
      const job = jobs.get(jobId)
      if (!job) throw new Error(`Unknown placeholder job ${jobId}`)
      const result = await this.getAuthorJobResult(jobId)
      if (result.status !== "completed" || !result.summary) {
        throw new Error("Placeholder job must be completed before publish.")
      }
      if (job.publishedStoryId) {
        return stories.get(job.publishedStoryId)!
      }
      const storyId = crypto.randomUUID()
      const card: PublishedStoryCard = {
        story_id: storyId,
        title: result.summary.title,
        one_liner: result.summary.one_liner,
        premise: result.summary.premise,
        theme: result.summary.theme,
        tone: result.summary.tone,
        npc_count: result.summary.npc_count,
        beat_count: result.summary.beat_count,
        topology: job.preview.structure.cast_topology,
        visibility,
        viewer_can_manage: true,
        published_at: new Date().toISOString(),
      }
      job.publishedStoryId = storyId
      stories.set(storyId, card)
      storyPreviews.set(storyId, job.preview)
      storyOwners.set(storyId, currentUser?.user_id ?? "placeholder-owner")
      return card
    },

    async listStories(params) {
      const visibleStories = Array.from(stories.values())
        .filter((story) => {
          const ownerUserId = storyOwners.get(story.story_id) ?? "local-dev"
          if ((params?.view ?? "accessible") === "mine") {
            return ownerUserId === currentUser?.user_id
          }
          if ((params?.view ?? "accessible") === "public") {
            return story.visibility === "public"
          }
          return ownerUserId === currentUser?.user_id || story.visibility === "public"
        })
        .map((story) => {
          const ownerUserId = storyOwners.get(story.story_id) ?? "local-dev"
          return {
            ...story,
            viewer_can_manage: ownerUserId === currentUser?.user_id,
          }
        })
      return listStoriesResponse(visibleStories, params)
    },

    async getStory(storyId) {
      const story = stories.get(storyId)
      const preview = storyPreviews.get(storyId)
      if (!story || !preview) throw new Error(`Unknown placeholder story ${storyId}`)
      const ownerUserId = storyOwners.get(storyId) ?? "local-dev"
      if (ownerUserId !== currentUser?.user_id && story.visibility !== "public") {
        throw new Error(`Unknown placeholder story ${storyId}`)
      }
      const viewerCanManage = ownerUserId === currentUser?.user_id
      const viewerStory = { ...story, viewer_can_manage: viewerCanManage }
      return {
        story: viewerStory,
        preview,
        presentation: {
          dossier_ref: `案卷号 ${story.story_id.slice(0, 3).toUpperCase()}`,
          status: "open_for_play",
          status_label: "可进入游玩",
          classification_label: THEME_LABELS[preview.theme.primary_theme] ?? preview.theme.primary_theme,
          engine_label: "LangGraph 运行时",
          visibility: story.visibility,
          viewer_can_manage: viewerCanManage,
        },
        play_overview: {
          protagonist: {
            title: "被所有人拿来解读的人",
            mandate: "活着走出这间屋子，选定一条线，并决定谁要在众目睽睽下出丑。",
            identity_summary: "你是这份案卷里的情绪中心，也是权力中心。每个被点名的人，都想在今晚从你身上拿到一点什么。",
          },
          opening_narration: `你走进《${story.title}》的现场。这间屋子已经知道，有个秘密快要浮出水面了，所有人都在等着看谁会先失控。`,
          runtime_profile: "relationship_drama_v2",
          runtime_profile_label: "关系戏 V2",
          play_length_preset: preview.play_length_preset ?? null,
          max_turns: 4,
        },
      }
    },

    async updateStoryVisibility(storyId, request) {
      const story = stories.get(storyId)
      if (!story) throw new Error(`Unknown placeholder story ${storyId}`)
      const ownerUserId = storyOwners.get(storyId) ?? "local-dev"
      if (ownerUserId !== currentUser?.user_id) throw new Error(`Unknown placeholder story ${storyId}`)
      const updatedStory = {
        ...story,
        visibility: request.visibility,
        viewer_can_manage: true,
      }
      stories.set(storyId, updatedStory)
      return updatedStory
    },

    async deleteStory(storyId) {
      const story = stories.get(storyId)
      if (!story) throw new Error(`Unknown placeholder story ${storyId}`)
      const ownerUserId = storyOwners.get(storyId) ?? "local-dev"
      if (ownerUserId !== currentUser?.user_id) throw new Error(`Unknown placeholder story ${storyId}`)
      stories.delete(storyId)
      storyPreviews.delete(storyId)
      storyOwners.delete(storyId)
      return {
        story_id: storyId,
        deleted: true,
      }
    },

    async createPlaySession(request) {
      const story = stories.get(request.story_id)
      const preview = storyPreviews.get(request.story_id)
      if (!story) throw new Error(`Unknown placeholder story ${request.story_id}`)
      const ownerUserId = storyOwners.get(request.story_id) ?? "local-dev"
      if (ownerUserId !== currentUser?.user_id && story.visibility !== "public") {
        throw new Error(`Unknown placeholder story ${request.story_id}`)
      }
      const sessionId = crypto.randomUUID()
      const session: PlaceholderPlaySession = {
        sessionId,
        storyId: story.story_id,
        storyTitle: story.title,
        storyShellId: preview?.story_shell_id ?? null,
        ownerUserId: currentUser?.user_id ?? "placeholder-owner",
        turnIndex: 0,
        beatIndex: 1,
        history: [
          {
            speaker: "gm",
            text: `You step into ${story.title}. The crisis is already moving and the room expects you to act.`,
            created_at: new Date().toISOString(),
            turn_index: 0,
          },
        ],
        protagonist: {
          title: "Civic Lead",
          mandate: "Keep the crisis from breaking the city in public.",
          identity_summary: "You are the central civic actor driving the response. The named NPCs are stakeholders around you.",
        },
        feedback: {
          ledgers: {
            success: {
              proof_progress: 0,
              coalition_progress: 0,
              order_progress: 0,
              settlement_progress: 0,
            },
            cost: {
              public_cost: 0,
              relationship_cost: 0,
              procedural_cost: 0,
              coercion_cost: 0,
            },
          },
          last_turn_axis_deltas: {},
          last_turn_stance_deltas: {},
          last_turn_global_deltas: {},
          last_turn_relationship_deltas: {},
          last_turn_tags: [],
          last_turn_consequences: [],
          last_turn_revealed_secret_ids: [],
        },
        narration: `You step into ${story.title}. The crisis is already moving and the room expects you to act.`,
        stateBars: [
          { bar_id: "external_pressure", label: "External Pressure", category: "axis", current_value: 1, min_value: 0, max_value: 5 },
          { bar_id: "public_panic", label: "Public Panic", category: "axis", current_value: 0, min_value: 0, max_value: 5 },
          { bar_id: "political_leverage", label: "Political Leverage", category: "axis", current_value: 1, min_value: 0, max_value: 5 },
        ],
        suggestedActions: [
          { suggestion_id: "s1", label: "Expose the hidden pressure", prompt: "You pull the hidden pressure into the open." },
          { suggestion_id: "s2", label: "Stabilize the coalition", prompt: "You keep the coalition from fracturing in public." },
          { suggestion_id: "s3", label: "Force a public settlement", prompt: "You try to lock one visible outcome into place." },
        ],
        ending: null,
      }
      sessions.set(sessionId, session)
      return buildPlaySnapshot(session)
    },

    async getPlaySession(sessionId) {
      const session = sessions.get(sessionId)
      if (!session) throw new Error(`Unknown placeholder session ${sessionId}`)
      if (session.ownerUserId !== currentUser?.user_id) throw new Error(`Unknown placeholder session ${sessionId}`)
      return buildPlaySnapshot(session)
    },

    async getPlaySessionHistory(sessionId) {
      const session = sessions.get(sessionId)
      if (!session) throw new Error(`Unknown placeholder session ${sessionId}`)
      if (session.ownerUserId !== currentUser?.user_id) throw new Error(`Unknown placeholder session ${sessionId}`)
      return {
        session_id: session.sessionId,
        story_id: session.storyId,
        entries: [...session.history],
      }
    },

    async submitPlayTurn(sessionId, request) {
      const session = sessions.get(sessionId)
      if (!session) throw new Error(`Unknown placeholder session ${sessionId}`)
      if (session.ownerUserId !== currentUser?.user_id) throw new Error(`Unknown placeholder session ${sessionId}`)
      session.turnIndex += 1
      session.beatIndex = Math.min(3, session.turnIndex >= 2 ? 2 : 1 + 0)
      if (session.turnIndex >= 4) {
        session.beatIndex = 3
      }
      session.stateBars = session.stateBars.map((bar) =>
        bar.category === "axis"
          ? {
              ...bar,
              current_value: Math.min(
                bar.max_value,
                Math.max(
                  bar.min_value,
                  bar.current_value +
                    (bar.bar_id === "external_pressure" ? 1 : 0) +
                    (bar.bar_id === "public_panic" && request.input_text.toLowerCase().includes("public") ? 1 : 0),
                ),
              ),
            }
          : {
              ...bar,
              current_value: Math.min(
                bar.max_value,
                Math.max(bar.min_value, bar.current_value + (request.input_text.toLowerCase().includes("trust") ? 1 : -1)),
              ),
            },
      )
      session.feedback = {
        ledgers: {
          success: {
            proof_progress: Math.min(4, session.feedback.ledgers.success.proof_progress + 1),
            coalition_progress: Math.min(4, session.feedback.ledgers.success.coalition_progress + 1),
            order_progress: Math.min(4, session.feedback.ledgers.success.order_progress + (session.turnIndex >= 2 ? 1 : 0)),
            settlement_progress: Math.min(4, session.feedback.ledgers.success.settlement_progress + (session.turnIndex >= 3 ? 1 : 0)),
          },
          cost: {
            public_cost: Math.min(4, session.feedback.ledgers.cost.public_cost + 1),
            relationship_cost: Math.min(4, session.feedback.ledgers.cost.relationship_cost + 1),
            procedural_cost: session.feedback.ledgers.cost.procedural_cost + (request.input_text.toLowerCase().includes("audit") ? 1 : 0),
            coercion_cost: Math.min(4, session.feedback.ledgers.cost.coercion_cost + (request.input_text.toLowerCase().includes("force") ? 1 : 0)),
          },
        },
        last_turn_axis_deltas: {
          external_pressure: 1,
          public_panic: request.input_text.toLowerCase().includes("public") ? 1 : 0,
        },
        last_turn_stance_deltas: {
          npc_relationship: request.input_text.toLowerCase().includes("trust") ? 1 : -1,
        },
        last_turn_global_deltas: {
          public_image: request.input_text.toLowerCase().includes("public") ? -1 : 0,
        },
        last_turn_relationship_deltas: {},
        last_turn_tags: ["coalition_strained", "public_record_secured"],
        last_turn_consequences: [
          "A visible relationship shifted under pressure.",
          "The public meaning of the crisis changed.",
        ],
        last_turn_revealed_secret_ids: [],
      }
      session.narration = `You say: "${request.input_text}". The room shifts, the pressure redistributes, and everyone waits to see whether this move stabilizes the crisis or hardens its cost.`
      session.ending = nextEndingForStory(session.storyTitle, session.turnIndex)
      session.history.push({
        speaker: "player",
        text: request.input_text,
        created_at: new Date().toISOString(),
        turn_index: session.turnIndex,
      })
      session.history.push({
        speaker: "gm",
        text: session.narration,
        created_at: new Date().toISOString(),
        turn_index: session.turnIndex,
      })
      return buildPlaySnapshot(session)
    },
  }
}
