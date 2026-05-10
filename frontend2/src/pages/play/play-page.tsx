import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { AnimatePresence, motion, useReducedMotion, type TargetAndTransition } from "motion/react"
import type {
  NarrativeAdvisorMessage,
  NarrativeEnding,
  NarrativeNPCPulse,
  NarrativeStoryHistoryResponse,
  NarrativeStoryMessage,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { Hint } from "../../shared/ui/hint"
import { LoadingShim } from "../../shared/ui/loading-shim"
import { StageProgressBar } from "../../shared/ui/stage-progress-bar"
import { Truncated } from "../../shared/ui/truncated"
import { useBookmarks } from "../../shared/lib/bookmarks"
import { friendlyError } from "../../shared/lib/friendly-error"
import { useT } from "../../shared/lib/i18n"
import {
  cascadeDelay,
  fadeTransition,
  fadeVariants,
  hoverLift,
  hoverNudge,
  itemTransition,
  itemVariants,
  labelChipSpring,
  pulseVariants,
  slideInRightTransition,
  slideInRightVariants,
  tapPress,
  transitions,
} from "../../shared/lib/motion-presets"
import {
  getAdvisorAvatar,
  getAvatarForCastMember,
  getCoverForTemplate,
  getEndingIllustration,
  getPeakCloseUp,
  getTierSplash,
  ORACLE_VIGNETTE,
} from "../../shared/lib/webtoon-assets"

export function PlayPage({
  sessionId,
  onBackHome,
}: {
  sessionId: string
  onBackHome: () => void
}) {
  const api = useApi()
  const t = useT()
  const [story, setStory] = useState<NarrativeStoryHistoryResponse | null>(null)
  const [ending, setEnding] = useState<NarrativeEnding | null>(null)
  // Per-session bookmarks — beats the user marked as "I want to
  // remember this." Merged into ending highlights at finalize so
  // the user's call has authority alongside the LLM's picks.
  const { marked: bookmarkedOrds, toggle: toggleBookmark, count: bookmarkCount } =
    useBookmarks(sessionId)
  void bookmarkCount
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Remember the last action that errored so the inline error banner
  // can offer a one-tap retry instead of forcing the user to re-type
  // / re-pick what they just submitted.
  const lastFailedActionRef = useRef<{
    chosen_option_index?: number
    free_input?: string
    diary?: string
  } | null>(null)
  const [freeInput, setFreeInput] = useState("")
  const [showFreeInput, setShowFreeInput] = useState(false)
  const [diary, setDiary] = useState("")
  const [showDiary, setShowDiary] = useState(false)
  const [advisorOpen, setAdvisorOpen] = useState(false)
  const [shareCopied, setShareCopied] = useState(false)

  // Initial load: story + (if already completed) the ending.
  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .getNarrativeStory(sessionId)
      .then(async (response) => {
        if (cancelled) return
        setStory(response)
        // If session already finished, fetch the ending so we can render
        // the closing screen on direct-link visits.
        if (response.session.ending_label) {
          try {
            const e = await api.getNarrativeSessionEnding(sessionId)
            if (!cancelled && e) setEnding(e)
          } catch {
            // ignore — the summary still has the label/subtitle if needed
          }
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(friendlyError(err, t("play.error_load_story")))
      })
    return () => {
      cancelled = true
    }
  }, [api, sessionId])

  // Auto-scroll the story column to the bottom whenever new content arrives.
  const scrollerRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [story?.messages.length])

  const handleAdvance = useCallback(
    async (action: {
      chosen_option_index?: number
      free_input?: string
      diary?: string
    }) => {
      if (busy) return
      setBusy(true)
      setError(null)
      lastFailedActionRef.current = null
      try {
        const response = await api.advanceNarrativeTurn(sessionId, action)
        setStory((prev) => {
          if (!prev) return prev
          // Mark the prior narrator's chosen_option_index in the local copy
          // so the option chips render the dim+selected state.
          const updated = prev.messages.map((m) => {
            if (
              m.role === "narrator" &&
              m.ord === response.player_message.ord - 1 &&
              action.chosen_option_index != null
            ) {
              return { ...m, chosen_option_index: action.chosen_option_index }
            }
            return m
          })
          return {
            ...prev,
            messages: [...updated, response.player_message, response.narrator_message],
            session: {
              ...prev.session,
              turn_count: prev.session.turn_count + 1,
              ending_label: response.ending?.label ?? prev.session.ending_label,
              ending_subtitle: response.ending?.subtitle ?? prev.session.ending_subtitle,
            },
          }
        })
        if (response.ending) {
          setEnding(response.ending)
        }
        setFreeInput("")
        setShowFreeInput(false)
        setDiary("")
        setShowDiary(false)
      } catch (err) {
        setError(friendlyError(err, t("play.error_advance")))
        lastFailedActionRef.current = action
      } finally {
        setBusy(false)
      }
    },
    [api, busy, sessionId],
  )

  const lastNarrator = story
    ? [...story.messages].reverse().find((m) => m.role === "narrator") ?? null
    : null
  const isLastNarratorPending =
    lastNarrator !== null && lastNarrator.chosen_option_index == null

  if (!story) {
    return (
      <div style={ppStyles.page}>
        <Header onBackHome={onBackHome} title="" />
        {error ? (
          <div style={ppStyles.centerNote}>{t("play.load_failed", { error })}</div>
        ) : (
          <LoadingShim label={t("play.loading_story")} />
        )}
      </div>
    )
  }

  const cover = getCoverForTemplate(story.template)
  const advisorAvatar = getAdvisorAvatar(
    story.template.template_id,
    story.template.advisor_persona,
  )

  const turnsCompleted = story.session.turn_count
  const turnBudget = story.session.turn_budget
  const turnsRemaining = Math.max(0, turnBudget - turnsCompleted)
  const isFinalApproaching = turnsRemaining <= 2 && !ending
  const isComplete = ending !== null
  const isGauntlet = story.session.difficulty === "gauntlet"
  const castNameById: Record<string, string> = Object.fromEntries(
    story.template.cast.map((c) => [c.character_id, c.display_name]),
  )
  // Live inventory derived from role.starting_assets + Σ delta over
  // narrator messages. Mirrors backend compute_current_inventory.
  const liveInventory = computeLiveInventory(
    story.session.player_role?.starting_assets ?? [],
    story.messages,
  )
  const startingAssetSet = new Set(story.session.player_role?.starting_assets ?? [])

  return (
    <div style={ppStyles.page}>
      <Header
        onBackHome={onBackHome}
        title={story.template.title}
        cast={story.template.cast.map((c) => c.display_name)}
        turnCount={story.session.turn_count}
        turnBudget={story.session.turn_budget}
        coverUrl={cover}
      />

      <main style={ppStyles.main}>
        <div style={ppStyles.storyColumn} ref={scrollerRef}>
          {/* Cast strip — small portraits to anchor the reader visually */}
          <div style={ppStyles.castStrip}>
            {story.template.cast.map((c) => (
              <div key={c.character_id} style={ppStyles.castChip}>
                <img
                  src={getAvatarForCastMember(story.template.template_id, c)}
                  alt={c.display_name}
                  style={ppStyles.castChipAvatar}
                  loading="lazy"
                />
                <div style={ppStyles.castChipText}>
                  <Truncated style={ppStyles.castChipName}>{c.display_name}</Truncated>
                  <Truncated style={ppStyles.castChipRole}>{c.role}</Truncated>
                </div>
              </div>
            ))}
          </div>

          {/* Stage progression bar — visualizes the dramatic arc so
              players see WHERE in the story they are, not just turn N. */}
          {!isComplete ? (
            <StageProgressBar turnIndex={turnsCompleted} turnBudget={turnBudget} />
          ) : null}

          {/* Pulse legend — explains what the 5 NPC pulse colors mean.
              Without it, "warmer/colder/wary/broken" chips are mystery
              symbols. Always visible in gauntlet mode so players can
              cross-reference any time. */}
          {isGauntlet && !isComplete ? (
            <div style={ppStyles.pulseLegend} aria-label={t("play.pulse_legend_aria")}>
              <span style={ppStyles.pulseLegendLabel}>
                {t("play.pulse_legend_label")}
                <Hint text={t("play.hint_pulse")}>{t("play.hint_pulse")}</Hint>
              </span>
              {[
                { shift: "warmer", text: t("play.pulse_warmer") },
                { shift: "colder", text: t("play.pulse_colder") },
                { shift: "wary", text: t("play.pulse_wary") },
                { shift: "broken", text: t("play.pulse_broken") },
                { shift: "steady", text: t("play.pulse_steady") },
              ].map((s) => {
                const shiftStyle =
                  ppStyles[("pulseShift_" + s.shift) as keyof typeof ppStyles] as
                    | CSSProperties
                    | undefined
                return (
                  <span
                    key={s.shift}
                    style={{ ...ppStyles.pulseLegendItem, ...(shiftStyle ?? {}) }}
                  >
                    {s.text}
                  </span>
                )
              })}
            </div>
          ) : null}

          {/* Identity framing line — "This run, you are: {label}".
              Sits above the role banner as a one-line declaration,
              styled like a stage direction so the user pauses here
              before reading the opening. The role banner below is
              the operational card (persona / objective / leverages);
              this line is the *naming* of the role, the moment the
              user puts the costume on. Only renders pre-finale. */}
          {story.session.player_role && !isComplete ? (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, ...itemTransition }}
              style={ppStyles.identityFraming}
            >
              <span style={ppStyles.identityFramingPrefix}>
                {t("play.identity_framing_prefix")}
              </span>
              <span style={ppStyles.identityFramingLabel}>
                {story.session.player_role.label}
              </span>
            </motion.div>
          ) : null}

          {/* Player role banner — who YOU are this run. Private POV
              card; persona is what NPCs see, hidden_objective + leverages
              are your secrets. */}
          {story.session.player_role ? (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={itemTransition}
              style={ppStyles.roleBanner}
            >
              <div style={ppStyles.roleBannerHeader}>
                <span style={ppStyles.roleBannerYou}>{t("play.role_you_tag")}</span>
                <Truncated style={ppStyles.roleBannerLabel}>
                  {story.session.player_role.label}
                </Truncated>
              </div>
              <p style={ppStyles.roleBannerPersona}>
                {story.session.player_role.public_persona}
              </p>
              <div style={ppStyles.roleBannerSecret}>
                <span style={ppStyles.roleBannerSecretTag}>
                  {t("play.role_secret_objective")}
                  <Hint text={t("play.hint_role_secret")} side="bottom">
                    {t("play.hint_role_secret")}
                  </Hint>
                </span>
                {story.session.player_role.hidden_objective}
              </div>
              {story.session.player_role.leverages_over_npcs.length > 0 ? (
                <div style={ppStyles.roleBannerLevSection}>
                  <span style={ppStyles.roleBannerSecretTag}>
                    {t("play.role_secret_leverage")}
                    <Hint text={t("play.hint_role_leverage")} side="bottom">
                      {t("play.hint_role_leverage")}
                    </Hint>
                  </span>
                  <ul style={ppStyles.roleBannerLevList}>
                    {story.session.player_role.leverages_over_npcs.map((lev, i) => (
                      <li key={i}>
                        <Truncated style={ppStyles.roleBannerLevNpc}>
                          {castNameById[lev.npc_id] ?? lev.npc_id}
                        </Truncated>
                        {lev.leverage}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {liveInventory.length > 0 ? (
                <div style={ppStyles.roleBannerLevSection}>
                  <span style={ppStyles.roleBannerSecretTag}>
                    {t("play.role_inventory", { count: liveInventory.length })}
                  </span>
                  <ul style={ppStyles.roleBannerLevList}>
                    {liveInventory.map((item, i) => {
                      const isAcquired = !startingAssetSet.has(item)
                      return (
                        <motion.li
                          key={`${i}-${item}`}
                          initial={isAcquired ? { opacity: 0, x: -8 } : false}
                          animate={{ opacity: 1, x: 0 }}
                          transition={itemTransition}
                          style={{
                            display: "flex",
                            gap: 4,
                            alignItems: "baseline",
                            ...(isAcquired ? ppStyles.roleInvAcquired : {}),
                          }}
                        >
                          <span style={{ flexShrink: 0 }}>
                            {isAcquired ? "+ " : "· "}
                          </span>
                          <Truncated style={{ flex: "1 1 0", minWidth: 0 }}>
                            {item}
                          </Truncated>
                        </motion.li>
                      )
                    })}
                  </ul>
                </div>
              ) : null}
            </motion.div>
          ) : null}

          {/* Gauntlet-mode goals card — visible reminder of what you're
              fighting for and what you stand to lose. */}
          {isGauntlet && story.template.player_goals && story.template.player_goals.length > 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={itemTransition}
              style={ppStyles.goalsCard}
            >
              <div style={ppStyles.goalsHeader}>
                <span style={ppStyles.gauntletBadge}>{t("play.gauntlet_badge")}</span>
                <span style={ppStyles.goalsTitle}>{t("play.gauntlet_goals_title")}</span>
              </div>
              {story.template.player_goals.map((g, idx) => (
                <div key={idx} style={ppStyles.goalRow}>
                  <div style={ppStyles.goalText}>·  {g.goal}</div>
                  <div style={ppStyles.goalStakes}>{t("play.gauntlet_goal_stakes", { stakes: g.stakes })}</div>
                </div>
              ))}
            </motion.div>
          ) : null}

          {story.messages.map((m, idx) => {
            // For player messages that picked an option, find the
            // previous narrator beat and look up the option's handle.
            // Using this in StoryBeat lets us render "you picked: 亮录音"
            // as a memory anchor instead of the full intent-tagged sentence.
            let pickedHandle: string | undefined
            if (m.role === "player" && idx > 0) {
              const prev = story.messages[idx - 1]
              if (
                prev?.role === "narrator" &&
                prev.chosen_option_index != null &&
                prev.options[prev.chosen_option_index]?.handle
              ) {
                pickedHandle = prev.options[prev.chosen_option_index].handle
              }
            }
            return (
              <StoryBeat
                key={`${m.role}-${m.ord}`}
                message={m}
                castNameById={castNameById}
                intensity={
                  m.role === "narrator"
                    ? computeBeatIntensity(m, turnBudget)
                    : "calm"
                }
                sceneUrl={m.role === "narrator" ? getPeakCloseUp(m.ord) : undefined}
                pickedHandle={pickedHandle}
                isBookmarked={m.role === "narrator" && bookmarkedOrds.has(m.ord)}
                onToggleBookmark={
                  m.role === "narrator" && !isComplete
                    ? () => toggleBookmark(m.ord)
                    : undefined
                }
              />
            )
          })}

          <AnimatePresence>
            {error ? (
              <motion.div
                key="play-error"
                style={ppStyles.errorInline}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={transitions.snap}
                role="alert"
              >
                <span style={ppStyles.errorInlineText}>{error}</span>
                {lastFailedActionRef.current ? (
                  <button
                    type="button"
                    className="ts-btn ts-btn--secondary"
                    style={ppStyles.errorInlineRetry}
                    onClick={() => {
                      const a = lastFailedActionRef.current
                      if (!a) return
                      void handleAdvance(a)
                    }}
                  >
                    {t("action.retry")}
                  </button>
                ) : null}
              </motion.div>
            ) : null}
          </AnimatePresence>

          {isFinalApproaching && !busy ? (
            <motion.div
              style={ppStyles.approachingFinaleBanner}
              variants={pulseVariants}
              initial="initial"
              animate="animate"
            >
              {turnsRemaining === 0
                ? t("play.finale_wrapping")
                : turnsRemaining === 1
                  ? t("play.finale_one_left")
                  : t("play.finale_two_left")}
            </motion.div>
          ) : null}

          {/* Ending screen — only when the session has finished */}
          {isComplete && ending ? (
            <EndingScreen
              ending={ending}
              sessionId={sessionId}
              templateId={story.template.template_id}
              messages={story.messages}
              bookmarkedOrds={bookmarkedOrds}
              shareCopied={shareCopied}
              onShare={() => {
                const url = `${window.location.origin}/#/replay/${sessionId}`
                navigator.clipboard.writeText(url).then(
                  () => {
                    setShareCopied(true)
                    setTimeout(() => setShareCopied(false), 2200)
                  },
                  () => {
                    // Fallback: show URL in an alert if clipboard fails
                    window.prompt(t("play.share_prompt"), url)
                  },
                )
              }}
              onPlayAgain={() => {
                // Land on the template detail page where the user can
                // pick a different role and start a fresh session. We
                // deliberately don't auto-pick a different role for
                // them — letting them browse the role cards is part
                // of the replay loop.
                window.location.hash = `#/template/${story.template.template_id}`
              }}
              onBackHome={onBackHome}
            />
          ) : null}

          {/* Action area pinned at the bottom of the story column.
              Hidden when the session is complete. */}
          {!isComplete && isLastNarratorPending && lastNarrator ? (
            <ActionArea
              // Key on the narrator beat ord so the entire ActionArea
              // remounts each turn — option cascade re-fires from
              // {opacity: 0, x: -6} every advance, instead of only on
              // first paint. Free-input / diary text lives in parent
              // state, so remount doesn't drop user typing.
              key={`actions-${lastNarrator.ord}`}
              options={lastNarrator.options}
              showFreeInput={showFreeInput}
              freeInput={freeInput}
              setFreeInput={setFreeInput}
              setShowFreeInput={setShowFreeInput}
              diary={diary}
              setDiary={setDiary}
              showDiary={showDiary}
              setShowDiary={setShowDiary}
              busy={busy}
              onPickOption={(i) =>
                void handleAdvance({
                  chosen_option_index: i,
                  diary: diary.trim() || undefined,
                })
              }
              onSubmitFree={() => {
                if (!freeInput.trim()) return
                void handleAdvance({
                  free_input: freeInput.trim(),
                  diary: diary.trim() || undefined,
                })
              }}
            />
          ) : !isComplete && busy ? (
            <LoadingShim variant="inline" label={t("play.busy_shim")} />
          ) : null}
        </div>
      </main>

      {/* Floating advisor button + sidechat */}
      <AdvisorFab
        onOpen={() => setAdvisorOpen(true)}
        avatarUrl={advisorAvatar}
        persona={story.template.advisor_persona}
      />
      <AnimatePresence>
        {advisorOpen ? (
          <AdvisorSidechat
            sessionId={sessionId}
            persona={story.template.advisor_persona}
            avatarUrl={advisorAvatar}
            turnsRemaining={turnsRemaining}
            isComplete={isComplete}
            onClose={() => setAdvisorOpen(false)}
            onOracleConsumed={(newBudget) => {
              // Update local session budget so the header chip updates
              // immediately and the oracle button respects the new
              // remaining count.
              setStory((prev) =>
                prev
                  ? {
                      ...prev,
                      session: { ...prev.session, turn_budget: newBudget },
                    }
                  : prev,
              )
            }}
          />
        ) : null}
      </AnimatePresence>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({
  onBackHome,
  title,
  cast,
  turnCount,
  turnBudget,
  coverUrl,
}: {
  onBackHome: () => void
  title: string
  cast?: string[]
  turnCount?: number
  turnBudget?: number
  coverUrl?: string
}) {
  const t = useT()
  const headerStyle: CSSProperties = coverUrl
    ? {
        ...ppStyles.header,
        ...ppStyles.headerWithCover,
        backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.55) 0%, rgba(20,16,12,0.92) 100%), url(${coverUrl})`,
      }
    : ppStyles.header

  const showProgress = typeof turnCount === "number" && typeof turnBudget === "number"
  const pct = showProgress ? Math.min(100, (turnCount! / turnBudget!) * 100) : 0

  return (
    <header style={headerStyle}>
      <div style={ppStyles.headerRow}>
        <button
          style={coverUrl ? { ...ppStyles.backBtn, ...ppStyles.backBtnOnCover } : ppStyles.backBtn}
          onClick={onBackHome}
          type="button"
        >
          {t("play.back_home")}
        </button>
        <div style={ppStyles.headerTitle}>
          <Truncated
            style={coverUrl ? { ...ppStyles.headerTitleLine, color: "white" } : ppStyles.headerTitleLine}
          >
            {title}
          </Truncated>
          {cast && cast.length ? (
            <div
              style={
                coverUrl
                  ? { ...ppStyles.headerCast, color: "rgba(255,255,255,0.78)" }
                  : ppStyles.headerCast
              }
              title={cast.join(" · ")}
            >
              {cast.join(" · ")}
              {showProgress ? (
                <span style={ppStyles.headerTurns}>
                  {t("play.header_turn_count", { current: turnCount!, total: turnBudget! })}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <span style={{ width: 90 }} />
      </div>
      {showProgress ? (
        <div style={ppStyles.progressTrack}>
          <div
            style={{
              ...ppStyles.progressFill,
              width: `${pct}%`,
            }}
          />
        </div>
      ) : null}
    </header>
  )
}

function EndingScreen({
  ending,
  sessionId,
  templateId,
  messages,
  bookmarkedOrds,
  shareCopied,
  onShare,
  onPlayAgain,
  onBackHome,
}: {
  ending: NarrativeEnding
  sessionId: string
  templateId: string
  messages: NarrativeStoryMessage[]
  bookmarkedOrds: Set<number>
  shareCopied: boolean
  onShare: () => void
  onPlayAgain: () => void
  onBackHome: () => void
}) {
  void templateId
  const t = useT()

  // Merge user bookmarks into the LLM's highlight list. User picks
  // get a `userMarked` flag and a synthesized headline / body
  // excerpt so they slot into the same card layout. Dedupe against
  // LLM picks (same ord = the LLM and the user both flagged it,
  // collapse into one card with the badge).
  type DisplayHighlight = {
    beat_ord: number
    headline: string
    body_excerpt: string
    why_pivotal: string
    userMarked: boolean
  }
  const llmHighlights: DisplayHighlight[] = (ending.highlights ?? []).map((h) => ({
    beat_ord: h.beat_ord,
    headline: h.headline,
    body_excerpt: h.body_excerpt,
    why_pivotal: h.why_pivotal,
    userMarked: bookmarkedOrds.has(h.beat_ord),
  }))
  const llmOrds = new Set(llmHighlights.map((h) => h.beat_ord))
  const narratorByOrd = new Map(
    messages.filter((m) => m.role === "narrator").map((m) => [m.ord, m]),
  )
  const userOnlyHighlights: DisplayHighlight[] = Array.from(bookmarkedOrds)
    .filter((ord) => !llmOrds.has(ord))
    .map((ord) => {
      const m = narratorByOrd.get(ord)
      return {
        beat_ord: ord,
        headline: t("play.ending_user_bookmark"),
        body_excerpt: m?.content?.slice(0, 200) ?? "",
        why_pivotal: "",
        userMarked: true,
      }
    })
    .filter((h) => h.body_excerpt.length > 0)
  const mergedHighlights: DisplayHighlight[] = [
    // User-only marks lead so the user's voice is first.
    ...userOnlyHighlights,
    ...llmHighlights,
  ].sort((a, b) => a.beat_ord - b.beat_ord)

  // Skip the 1.7s choreography in two cases:
  //  1. User prefers reduced motion (a11y system pref)
  //  2. They've already seen this exact ending in this browser session
  //     — re-opening the run page (back/forward, refresh) shouldn't
  //     replay the splash; it's the first view that earns the
  //     ceremony.
  const reducedMotion = useReducedMotion()
  const [hasSeenBefore] = useState(() => {
    if (typeof window === "undefined") return false
    try {
      return window.sessionStorage.getItem(
        `tiny-stories-ending-seen-${sessionId}`,
      ) === "1"
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        `tiny-stories-ending-seen-${sessionId}`,
        "1",
      )
    } catch {
      // sessionStorage unavailable (private mode) — fail silently;
      // worst case the splash plays again on refresh.
    }
  }, [sessionId])
  const skipChoreography = Boolean(reducedMotion) || hasSeenBefore

  // Helper: collapse `initial` state to `false` (= start at animate
  // target, no entrance) and zero out staggered delays when skipping.
  const initialOr = (
    full: TargetAndTransition,
  ): TargetAndTransition | false => (skipChoreography ? false : full)
  const delayOr = (delay: number): number =>
    skipChoreography ? 0 : delay

  const illustration = getEndingIllustration(ending.label)
  const tier = ending.tier ?? "compromised"
  const tierSplash = getTierSplash(tier)
  const tierVisuals: Record<string, { ribbon: string; chipBg: string; chipColor: string; gradient: string; badgeText: string }> = {
    victory: {
      ribbon: t("play.ending_ribbon_victory"),
      badgeText: "VICTORY",
      chipBg: "linear-gradient(90deg, #d4af37, #f7d97a)",
      chipColor: "#1a1108",
      gradient: "linear-gradient(180deg, rgba(180,140,40,0.0) 0%, rgba(60,40,15,0.55) 75%, var(--bg-elev) 100%)",
    },
    compromised: {
      ribbon: t("play.ending_ribbon_compromised"),
      badgeText: "COMPROMISED",
      chipBg: "rgba(255,255,255,0.12)",
      chipColor: "var(--text)",
      gradient: "linear-gradient(180deg, rgba(20,16,12,0.15) 0%, rgba(20,16,12,0.6) 75%, var(--bg-elev) 100%)",
    },
    collapsed: {
      ribbon: ending.early_terminated ? t("play.ending_ribbon_early") : t("play.ending_ribbon_collapsed"),
      badgeText: "GAME OVER",
      chipBg: "linear-gradient(90deg, #8a1a1a, #c33b3b)",
      chipColor: "white",
      gradient: "linear-gradient(180deg, rgba(60,10,10,0.25) 0%, rgba(50,8,8,0.78) 75%, var(--bg-elev) 100%)",
    },
  }
  const tv = tierVisuals[tier]
  return (
    <motion.section
      style={ppStyles.endingSection}
      initial={skipChoreography ? "animate" : "initial"}
      animate="animate"
      transition={{
        staggerChildren: skipChoreography ? 0 : 0.18,
        delayChildren: delayOr(0.1),
      }}
    >
      <motion.div
        variants={itemVariants}
        transition={itemTransition}
        style={ppStyles.endingDivider}
      >
        <span style={ppStyles.endingDividerLabel}>{tv.ribbon}</span>
      </motion.div>
      <motion.div
        variants={itemVariants}
        transition={itemTransition}
        style={ppStyles.endingCard}
      >
        {/* Illustrated banner — the visual punctuation that makes the
            ending feel like a closed object the player can screenshot. */}
        <motion.div
          initial={initialOr({ opacity: 0, scale: 1.06 })}
          animate={{ opacity: 1, scale: 1 }}
          transition={transitions.slow}
          style={{
            ...ppStyles.endingHero,
            backgroundImage: `${tv.gradient}, url(${illustration})`,
          }}
        >
          {tierSplash ? (
            <motion.div
              initial={initialOr({ opacity: 0, scale: 1.12 })}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: delayOr(0.25), ...transitions.ceremony }}
              style={{
                ...ppStyles.endingSplashOverlay,
                backgroundImage: `url(${tierSplash})`,
              }}
            />
          ) : null}
          <div style={ppStyles.endingTierBadge}>
            <span style={ppStyles.endingTierBadgeText}>{tv.badgeText}</span>
            {ending.early_terminated && ending.failure_trigger ? (
              <span style={ppStyles.endingTierTrigger}>
                {t("play.ending_trigger_prefix", { trigger: ending.failure_trigger })}
              </span>
            ) : null}
          </div>
        </motion.div>
        <div style={ppStyles.endingCardInner}>
        <motion.div
          initial={initialOr({ opacity: 0, scale: 0.6 })}
          animate={{ opacity: 1, scale: 1 }}
          transition={
            skipChoreography
              ? transitions.snap
              : labelChipSpring
          }
          style={{ ...ppStyles.endingLabelChip, background: tv.chipBg, color: tv.chipColor }}
        >
          {ending.label}
        </motion.div>
        <motion.h2
          initial={initialOr({ opacity: 0, y: 14 })}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: delayOr(0.6), ...itemTransition }}
          style={ppStyles.endingSubtitle}
        >
          「{ending.subtitle}」
        </motion.h2>
        <motion.div
          initial={initialOr({ opacity: 0 })}
          animate={{ opacity: 1 }}
          transition={{ delay: delayOr(0.85), ...transitions.slow }}
          style={ppStyles.endingPassage}
        >
          {ending.passage}
        </motion.div>

        {/* Highlight reel — LLM picks merged with user bookmarks.
            User-marked cards lead with a ★ badge and yellow accent
            border so it reads as "your pick" alongside the system's. */}
        {mergedHighlights.length > 0 ? (
          <motion.section
            initial={initialOr({ opacity: 0, y: 12 })}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: delayOr(1.0), ...itemTransition }}
            style={ppStyles.highlightReel}
          >
            <div style={ppStyles.highlightReelLabel}>
              {t("play.ending_highlights_title", { count: mergedHighlights.length })}
            </div>
            <div style={ppStyles.highlightList}>
              {mergedHighlights.map((h, i) => (
                <motion.div
                  key={`${h.beat_ord}-${i}`}
                  initial={initialOr({ opacity: 0, x: -8 })}
                  animate={{ opacity: 1, x: 0 }}
                  whileHover={{
                    y: -2,
                    borderColor: "rgba(245,200,120,0.45)",
                    transition: transitions.snap,
                  }}
                  transition={{ delay: delayOr(1.05 + cascadeDelay(i, 0.08)), ...itemTransition }}
                  style={{
                    ...ppStyles.highlightCard,
                    ...(h.userMarked ? ppStyles.highlightCardUserMarked : null),
                  }}
                >
                  <div style={ppStyles.highlightHeader}>
                    <span style={ppStyles.highlightIndex}>{i + 1}</span>
                    {h.userMarked ? (
                      <span style={ppStyles.highlightUserMark} aria-label="bookmarked by you">
                        ★
                      </span>
                    ) : null}
                    <span style={ppStyles.highlightHeadline}>{h.headline}</span>
                  </div>
                  <div style={ppStyles.highlightBody}>{h.body_excerpt}</div>
                  {h.why_pivotal ? (
                    <div style={ppStyles.highlightWhy}>{h.why_pivotal}</div>
                  ) : null}
                </motion.div>
              ))}
            </div>
          </motion.section>
        ) : null}

        {/* Branches — alternate paths the player didn't take, drives
            replay intent. Each card shows the pivot turn, what they
            chose vs alternate, and tier-color-graded predicted ending. */}
        {ending.branches && ending.branches.length > 0 ? (
          <motion.section
            initial={initialOr({ opacity: 0, y: 12 })}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: delayOr(1.25), ...itemTransition }}
            style={ppStyles.branchesSection}
          >
            <div style={ppStyles.branchesLabel}>
              {t("play.ending_branches_title", { count: ending.branches.length })}
            </div>
            <p style={ppStyles.branchesHint}>
              {t("play.ending_branches_hint")}
            </p>
            <div style={ppStyles.branchList}>
              {ending.branches.map((b, i) => {
                const tierStyle =
                  b.alternate_ending_tier === "victory"
                    ? ppStyles.branchTierVictory
                    : b.alternate_ending_tier === "collapsed"
                      ? ppStyles.branchTierCollapsed
                      : ppStyles.branchTierCompromised
                return (
                  <motion.div
                    key={`${b.pivot_beat_ord}-${i}`}
                    initial={initialOr({ opacity: 0, x: -8 })}
                    animate={{ opacity: 1, x: 0 }}
                    whileHover={{
                      y: -2,
                      borderColor: "rgba(140,100,200,0.45)",
                      transition: transitions.snap,
                    }}
                    transition={{ delay: delayOr(1.3 + cascadeDelay(i, 0.08)), ...itemTransition }}
                    style={ppStyles.branchCard}
                  >
                    <div style={ppStyles.branchTurnBadge}>
                      {t("play.ending_branch_turn", { turn: Math.floor(b.pivot_beat_ord / 2) })}
                    </div>
                    <div style={ppStyles.branchPaths}>
                      <div style={ppStyles.branchChosen}>
                        <span style={ppStyles.branchPathTag}>{t("play.ending_branch_chosen_tag")}</span>
                        <span style={ppStyles.branchPathText}>{b.chosen_path_summary}</span>
                      </div>
                      <div style={ppStyles.branchArrow}>{t("play.ending_branch_arrow")}</div>
                      <div style={ppStyles.branchAlternate}>
                        <span style={ppStyles.branchPathTag}>{t("play.ending_branch_alt_tag")}</span>
                        <span style={ppStyles.branchPathText}>{b.alternate_path_summary}</span>
                      </div>
                    </div>
                    <div style={ppStyles.branchOutcome}>
                      <span style={{ ...ppStyles.branchEndingChip, ...tierStyle }}>
                        {b.alternate_ending_label}
                      </span>
                      <span style={ppStyles.branchRationale}>{b.rationale}</span>
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </motion.section>
        ) : null}

        <motion.div
          initial={initialOr({ opacity: 0, y: 8 })}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: delayOr(1.7), ...itemTransition }}
          style={ppStyles.endingActions}
        >
          <div style={ppStyles.endingActionsRow}>
            <motion.button
              className="ts-btn ts-btn--primary"
              onClick={onShare}
              type="button"
              style={{ minWidth: 180 }}
              whileHover={{ scale: 1.02 }}
              whileTap={tapPress}
              key={shareCopied ? "copied" : "default"}
              initial={shareCopied ? { scale: 0.92 } : false}
              animate={shareCopied ? { scale: [0.92, 1.06, 1] } : { scale: 1 }}
              transition={transitions.base}
            >
              {shareCopied ? t("play.ending_share_copied") : t("play.ending_share")}
            </motion.button>
            {/* Replay-with-different-role — closes the loop. Without
                this, finishing a run was a dead end; user had to nav
                back home → find template → re-pick role. Now it's
                one click. We deliberately route through the template
                detail page rather than auto-picking a new role —
                seeing the role cards is part of the re-engagement. */}
            <motion.button
              className="ts-btn ts-btn--secondary"
              onClick={onPlayAgain}
              type="button"
              whileHover={{ scale: 1.02 }}
              whileTap={tapPress}
            >
              {t("play.ending_replay")}
            </motion.button>
            <motion.button
              className="ts-btn ts-btn--ghost"
              onClick={onBackHome}
              type="button"
              whileHover={{ scale: 1.02 }}
              whileTap={tapPress}
            >
              {t("action.back_home")}
            </motion.button>
          </div>
          <p style={ppStyles.endingShareHint}>
            {t("play.ending_share_hint")}
          </p>
        </motion.div>
        </div>
      </motion.div>
    </motion.section>
  )
}

// ---------------------------------------------------------------------------
// Single story beat (narrator passage or player move)
// ---------------------------------------------------------------------------

function StoryBeat({
  message,
  castNameById,
  intensity = "calm",
  sceneUrl,
  pickedHandle,
  isBookmarked,
  onToggleBookmark,
}: {
  message: NarrativeStoryMessage
  castNameById?: Record<string, string>
  intensity?: "calm" | "rising" | "peak"
  sceneUrl?: string
  /** When this player message was an option pick, the option's
   *  short memory handle. Used to render a leading chip so users
   *  remember "I picked X" rather than re-parsing the full sentence. */
  pickedHandle?: string
  /** True if the user has bookmarked this narrator beat. */
  isBookmarked?: boolean
  /** Click handler for the bookmark icon. Undefined hides the icon
   *  (e.g. for player messages or after the run is complete). */
  onToggleBookmark?: () => void
}) {
  const t = useT()
  if (message.role === "narrator") {
    const pulses = message.npc_pulse ?? []
    const delta = message.inventory_delta
    const hasDelta = !!(delta && (delta.added.length > 0 || delta.removed.length > 0))
    // Visual tier: calm = default; rising = +size + decor line; peak =
    // larger type + bold left rail + scene banner overlay.
    const beatStyle =
      intensity === "peak"
        ? { ...ppStyles.narratorBeat, ...ppStyles.narratorBeatPeak }
        : intensity === "rising"
          ? { ...ppStyles.narratorBeat, ...ppStyles.narratorBeatRising }
          : ppStyles.narratorBeat
    const textStyle =
      intensity === "peak"
        ? { ...ppStyles.narratorText, ...ppStyles.narratorTextPeak }
        : intensity === "rising"
          ? { ...ppStyles.narratorText, ...ppStyles.narratorTextRising }
          : ppStyles.narratorText
    return (
      <motion.article
        layout
        initial="initial"
        animate="animate"
        variants={itemVariants}
        transition={itemTransition}
        style={{
          ...beatStyle,
          position: "relative",
          ...(isBookmarked ? ppStyles.narratorBeatBookmarked : null),
        }}
      >
        {/* Bookmark toggle — top-right of every narrator beat while
            the run is active. Lets the user mark "this is the
            moment I want to remember" so it shows up in the ending
            highlights with their own badge, alongside (or instead
            of) the LLM picks. */}
        {onToggleBookmark ? (
          <button
            type="button"
            onClick={onToggleBookmark}
            aria-label={isBookmarked ? "Bookmarked — click to remove" : "Bookmark this beat"}
            aria-pressed={!!isBookmarked}
            style={{
              ...ppStyles.beatBookmarkBtn,
              ...(isBookmarked ? ppStyles.beatBookmarkBtnActive : null),
            }}
            title={isBookmarked ? "已标记 · 点击取消" : "标记这一段"}
          >
            {isBookmarked ? "★" : "☆"}
          </button>
        ) : null}
        {intensity === "peak" && sceneUrl ? (
          <motion.div
            initial={{ opacity: 0, scale: 1.05 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={transitions.slow}
            style={{
              ...ppStyles.beatSceneBanner,
              backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.15) 0%, rgba(20,16,12,0.85) 90%, var(--bg) 100%), url(${sceneUrl})`,
            }}
            aria-hidden
          />
        ) : null}
        {intensity === "rising" || intensity === "peak" ? (
          <div
            style={
              intensity === "peak" ? ppStyles.beatDecorPeak : ppStyles.beatDecorRising
            }
            aria-hidden
          />
        ) : null}
        <div style={textStyle}>{message.content}</div>
        {hasDelta && delta ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.92, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ delay: 0.18, ...itemTransition }}
            style={ppStyles.invToast}
          >
            {delta.added.map((item, i) => (
              <div key={`add-${i}`} style={ppStyles.invToastAdded}>
                <span style={ppStyles.invToastIcon}>＋</span>
                {t("play.beat_inv_added", { item })}
              </div>
            ))}
            {delta.removed.map((item, i) => (
              <div key={`rm-${i}`} style={ppStyles.invToastRemoved}>
                <span style={ppStyles.invToastIcon}>－</span>
                {t("play.beat_inv_removed", { item })}
              </div>
            ))}
            {delta.reason ? (
              <div style={ppStyles.invToastReason}>{delta.reason}</div>
            ) : null}
          </motion.div>
        ) : null}
        {message.chosen_option_index != null && message.options.length > 0 ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.12, ...itemTransition }}
            style={ppStyles.chosenChip}
          >
            <span style={ppStyles.chosenLabel}>{t("play.beat_chosen_label")}</span>
            <span style={ppStyles.chosenText}>
              {message.options[message.chosen_option_index]?.label ?? "?"}
            </span>
          </motion.div>
        ) : null}
        {pulses.length > 0 ? (
          <motion.div
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, ...itemTransition }}
            style={ppStyles.pulseStrip}
          >
            {pulses.map((p, idx) => {
              const name = (castNameById && castNameById[p.npc_id]) || p.npc_id
              const shiftStyle =
                ppStyles[
                  ("pulseShift_" + p.shift) as keyof typeof ppStyles
                ] as CSSProperties | undefined
              const isBroken = p.shift === "broken"
              const hasReason = !!(p.reason && p.shift !== "steady")
              return (
                <div key={`${p.npc_id}-${idx}`} style={ppStyles.pulseRow}>
                  <motion.span
                    style={{ ...ppStyles.pulseChip, ...(shiftStyle ?? {}) }}
                    title={`${name}: ${p.state} (${p.shift})${p.reason ? ` — ${p.reason}` : ""}`}
                    animate={
                      isBroken
                        ? {
                            boxShadow: [
                              "0 0 0 0 rgba(220,80,60,0)",
                              "0 0 0 4px rgba(220,80,60,0.45)",
                              "0 0 0 0 rgba(220,80,60,0)",
                            ],
                          }
                        : undefined
                    }
                    transition={
                      isBroken
                        ? { duration: 1.4, repeat: 2, ease: "easeOut", delay: 0.3 }
                        : undefined
                    }
                  >
                    <span style={ppStyles.pulseChipName}>{name}</span>
                    <span style={ppStyles.pulseChipState}>· {p.state}</span>
                    <span style={ppStyles.pulseChipArrow}>{shiftArrow(p.shift)}</span>
                  </motion.span>
                  {hasReason ? (
                    <span style={ppStyles.pulseReason}>
                      <span style={ppStyles.pulseReasonArrow} aria-hidden>←</span>
                      {t("play.pulse_reason_prefix", { reason: p.reason ?? "" })}
                    </span>
                  ) : null}
                </div>
              )
            })}
          </motion.div>
        ) : null}
      </motion.article>
    )
  }
  // player move (echoed action)
  return (
    <motion.article
      layout
      initial="initial"
      animate="animate"
      variants={itemVariants}
      transition={itemTransition}
      style={ppStyles.playerBeat}
    >
      <div style={ppStyles.playerLabel}>
        {t("play.beat_player_label")}
        {pickedHandle ? (
          <>
            <span style={ppStyles.playerLabelSeparator}>{" · "}</span>
            <span style={ppStyles.playerHandleChip} title={message.content}>
              {pickedHandle}
            </span>
          </>
        ) : null}
      </div>
      <div style={ppStyles.playerText}>{message.content}</div>
      {message.diary ? (
        <div style={ppStyles.playerDiary}>
          <span style={ppStyles.playerDiaryTag}>{t("play.beat_diary_tag")}</span>
          <span style={ppStyles.playerDiaryText}>{message.diary}</span>
        </div>
      ) : null}
    </motion.article>
  )
}

function computeLiveInventory(
  startingAssets: string[],
  messages: NarrativeStoryMessage[],
): string[] {
  const inv: string[] = [...startingAssets]
  for (const msg of messages) {
    if (msg.role !== "narrator" || !msg.inventory_delta) continue
    for (const added of msg.inventory_delta.added) {
      inv.push(added)
    }
    for (const removed of msg.inventory_delta.removed) {
      const target = removed.toLowerCase()
      for (let i = 0; i < inv.length; i += 1) {
        const item = inv[i]?.toLowerCase() ?? ""
        if (item && (item.includes(target) || target.includes(item))) {
          inv.splice(i, 1)
          break
        }
      }
    }
  }
  return inv
}

// Mirror of backend _stage_for. Used to drive visual intensity and to
// map a narrator beat back to a segment scene asset.
function stageForLocal(turnIndex: number, turnBudget: number): string {
  if (turnIndex <= 1) return "hook"
  const midpoint = turnBudget / 2
  if (turnIndex < midpoint - 0.5) return "pressure"
  if (turnIndex < midpoint + 0.5) return "reversal"
  if (turnIndex < turnBudget - 1) return "climax"
  if (turnIndex < turnBudget) return "pre_finale"
  return "pre_finale_open"
}

// Visual intensity heuristic — purely client-side from data we already
// have. Peak: any pulse broken, OR inventory delta fired, OR (climax/
// pre_finale stage AND any colder/wary). Rising: reversal/climax stages
// without peak signal. Calm: hook + early pressure.
function computeBeatIntensity(
  message: NarrativeStoryMessage,
  turnBudget: number,
): "calm" | "rising" | "peak" {
  if (message.role !== "narrator") return "calm"
  const turnIndex = Math.floor(message.ord / 2)
  // Opening (ord=0) is always calm — sets the scene, no visual punch yet.
  if (turnIndex === 0) return "calm"
  const stage = stageForLocal(turnIndex, turnBudget)
  const pulses = message.npc_pulse ?? []
  const hasBroken = pulses.some((p) => p.shift === "broken")
  const hasColderOrWary = pulses.some(
    (p) => p.shift === "colder" || p.shift === "wary",
  )
  const delta = message.inventory_delta
  const hasDelta = !!(
    delta && (delta.added.length > 0 || delta.removed.length > 0)
  )
  if (hasBroken) return "peak"
  if (hasDelta) return "peak"
  if ((stage === "climax" || stage === "pre_finale" || stage === "pre_finale_open") && hasColderOrWary) {
    return "peak"
  }
  if (stage === "reversal" || stage === "climax" || stage === "pre_finale" || stage === "pre_finale_open") {
    return "rising"
  }
  return "calm"
}

// Parse an option label that may start with an intent tag like "[挑拨] xxx".
// Returns { tag: "挑拨", body: "xxx" } or { tag: null, body: full label }.
// Used so the UI can render the tag as a colored chip + the action body
// as plain text, giving players a visual scan-tag for what the choice
// means before reading the full action.
function parseOptionLabel(label: string): { tag: string | null; body: string } {
  const m = label.match(/^\s*[\[【]([^\]】]{1,8})[\]】]\s*(.*)$/)
  if (m) {
    return { tag: m[1].trim(), body: (m[2] ?? "").trim() }
  }
  return { tag: null, body: label }
}

// Color palette for the 8 known tags. Active/aggressive tags use warm
// gold or red; passive/defensive use neutral or purple. Unknown tags
// fall back to neutral.
function optionTagStyle(tag: string): CSSProperties {
  const ACTIVE_HOT = {
    background: "linear-gradient(90deg, rgba(220,80,60,0.22), rgba(220,80,60,0.08))",
    color: "rgba(245,180,170,0.96)",
    border: "1px solid rgba(220,80,60,0.42)",
  }
  const ACTIVE_GOLD = {
    background: "linear-gradient(90deg, rgba(212,168,83,0.22), rgba(212,168,83,0.08))",
    color: "rgba(245,210,140,0.96)",
    border: "1px solid rgba(212,168,83,0.45)",
  }
  const ACTIVE_PURPLE = {
    background: "linear-gradient(90deg, rgba(140,100,200,0.20), rgba(140,100,200,0.06))",
    color: "rgba(200,170,235,0.96)",
    border: "1px solid rgba(140,100,200,0.45)",
  }
  const PASSIVE = {
    background: "rgba(255,255,255,0.04)",
    color: "var(--text-muted)",
    border: "1px solid var(--line)",
  }
  // Chinese tag set (legacy) and English mirror (used when template
  // language=en). Unknown tags fall through to PASSIVE — the directive
  // in engine.py keeps both sets stable, so this list rarely needs
  // updating.
  if (tag === "挑拨" || tag === "硬刚" || tag === "Provoke" || tag === "Confront") return ACTIVE_HOT
  if (tag === "反将" || tag === "合作" || tag === "Counter" || tag === "Ally") return ACTIVE_GOLD
  if (tag === "试探" || tag === "Probe") return ACTIVE_PURPLE
  // 妥协 / 观望 / 示弱 / Yield / Watch / Submit / unknown → PASSIVE
  return PASSIVE
}

function shiftArrow(shift: NarrativeNPCPulse["shift"]): string {
  switch (shift) {
    case "warmer": return "↗"
    case "colder": return "↘"
    case "wary":   return "⚠"
    case "broken": return "✕"
    case "steady":
    default:       return "—"
  }
}

// ---------------------------------------------------------------------------
// Action area — options + free input
// ---------------------------------------------------------------------------

function ActionArea({
  options,
  showFreeInput,
  freeInput,
  setFreeInput,
  setShowFreeInput,
  diary,
  setDiary,
  showDiary,
  setShowDiary,
  busy,
  onPickOption,
  onSubmitFree,
}: {
  options: NarrativeStoryMessage["options"]
  showFreeInput: boolean
  freeInput: string
  setFreeInput: (v: string) => void
  setShowFreeInput: (v: boolean) => void
  diary: string
  setDiary: (v: string) => void
  showDiary: boolean
  setShowDiary: (v: boolean) => void
  busy: boolean
  onPickOption: (idx: number) => void
  onSubmitFree: () => void
}) {
  const t = useT()
  // Local "I picked option N this turn" so we can immediately reflect
  // the choice — instead of just dimming everything to 50% opacity
  // and waiting 5-8s for the LLM. State resets every turn because
  // the parent gives us key={beat.ord}, remounting ActionArea.
  const [pickedIndex, setPickedIndex] = useState<number | null>(null)
  const [submittedFree, setSubmittedFree] = useState(false)

  const handleOptionPick = (i: number) => {
    if (busy) return
    setPickedIndex(i)
    onPickOption(i)
  }

  const handleSubmitFreeWithReflect = () => {
    if (!freeInput.trim() || busy) return
    setSubmittedFree(true)
    onSubmitFree()
  }

  // Once the parent flips busy=false (turn settled, narrator beat
  // arrived), the parent will remount us via key change anyway. But
  // if the request fails and busy goes false without remount, clear
  // the picked state so the user can retry.
  useEffect(() => {
    if (!busy) {
      setPickedIndex(null)
      setSubmittedFree(false)
    }
  }, [busy])

  // Keyboard shortcuts:
  //   1 / 2 / 3 ... pick the corresponding option (when not focused
  //   in a text input / textarea — otherwise the digit just types).
  // The hint chips on each option button reflect this.
  useEffect(() => {
    if (busy || options.length === 0) return
    const handler = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null
      if (!tgt) return
      const inEditable =
        tgt.tagName === "TEXTAREA" ||
        tgt.tagName === "INPUT" ||
        tgt.isContentEditable
      if (inEditable) return
      if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return
      if (e.key >= "1" && e.key <= "9") {
        const idx = parseInt(e.key, 10) - 1
        if (idx >= 0 && idx < options.length) {
          e.preventDefault()
          handleOptionPick(idx)
        }
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, options.length])

  const showPickedReflection = pickedIndex !== null || submittedFree
  // OS-aware "Cmd" vs "Ctrl" for the submit-shortcut hint.
  const submitModKey = useMemo(() => {
    if (typeof navigator === "undefined") return "Ctrl"
    return /Mac|iPhone|iPad/i.test(navigator.platform) ? "⌘" : "Ctrl"
  }, [])

  return (
    <motion.div
      style={ppStyles.actionArea}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.08, ...itemTransition }}
    >
      <div style={ppStyles.optionsList}>
        {options.length === 0 ? (
          <div style={ppStyles.noOptions}>
            {t("play.action_no_options")}
          </div>
        ) : (
          options.map((opt, i) => {
            const parsed = parseOptionLabel(opt.label)
            const isPicked = pickedIndex === i
            const isUnpicked = pickedIndex !== null && pickedIndex !== i
            return (
              <motion.button
                key={i}
                style={{
                  ...ppStyles.optionBtn,
                  // While picked: highlight the chosen one (gold border),
                  // fade the unchosen ones harder than busy default.
                  ...(isPicked ? ppStyles.optionBtnPicked : null),
                  opacity: isUnpicked ? 0.28 : busy && !isPicked ? 0.5 : 1,
                  pointerEvents: busy ? "none" : "auto",
                }}
                onClick={() => handleOptionPick(i)}
                disabled={busy}
                type="button"
                initial={{ opacity: 0, x: -6 }}
                animate={{
                  opacity: isUnpicked ? 0.28 : busy && !isPicked ? 0.5 : 1,
                  x: 0,
                  scale: isPicked ? 1.015 : 1,
                }}
                transition={{ delay: cascadeDelay(i, 0.05, 0.1), ...itemTransition }}
                whileHover={busy ? undefined : hoverNudge}
                whileTap={busy ? undefined : tapPress}
              >
                <div style={ppStyles.optionLabel}>
                  {/* Number key hint — visual cue that pressing the
                      digit picks this option. Lives on the leading
                      edge so it reads as "shortcut: 1, then this
                      action." Hidden on the small handful of options
                      beyond 9 (we cap at the first 9 for sanity). */}
                  {i < 9 ? (
                    <kbd style={ppStyles.optionKbd} aria-label={`Press ${i + 1}`}>
                      {i + 1}
                    </kbd>
                  ) : null}
                  {parsed.tag ? (
                    <span
                      style={{
                        ...ppStyles.optionTagChip,
                        ...optionTagStyle(parsed.tag),
                      }}
                    >
                      {parsed.tag}
                    </span>
                  ) : null}
                  <span>{parsed.body}</span>
                </div>
                {opt.hint ? <div style={ppStyles.optionHint}>{opt.hint}</div> : null}
              </motion.button>
            )
          })
        )}
      </div>

      {/* Reflective banner — confirms the just-submitted move while
          the LLM composes the next beat. Slips in right after the
          tap; disappears when the new beat arrives (parent remounts). */}
      <AnimatePresence>
        {showPickedReflection && busy ? (
          <motion.div
            key="picked-reflect"
            style={ppStyles.pickedReflect}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={transitions.snap}
          >
            <span style={ppStyles.pickedReflectIcon}>✓</span>
            <span>{t("play.action_busy")}</span>
            {/* Echo the picked option's `handle` (memory hook) — gives
                the user something concrete to remember picking, instead
                of just the abstract "submitting…". E.g. "✓ submitting…
                · 亮录音". When the option had no handle (legacy data),
                falls back to nothing extra. */}
            {pickedIndex !== null && options[pickedIndex]?.handle ? (
              <span style={ppStyles.pickedReflectHandle}>
                · {options[pickedIndex]?.handle}
              </span>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>

      <AnimatePresence mode="wait" initial={false}>
        {showFreeInput || options.length === 0 ? (
          <motion.div
            key="free-input-open"
            style={ppStyles.freeInputBox}
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: "auto", marginTop: 14 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            transition={transitions.snap}
          >
            <textarea
              style={ppStyles.freeTextarea}
              value={freeInput}
              placeholder={t("play.action_free_placeholder")}
              onChange={(e) => setFreeInput(e.target.value)}
              onKeyDown={(e) => {
                // Cmd/Ctrl + Enter submits — the standard "send" pattern
                // for any modern textarea input. Plain Enter still
                // line-breaks because the input is multi-line drama.
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  if (!freeInput.trim() || busy) return
                  e.preventDefault()
                  handleSubmitFreeWithReflect()
                }
              }}
              disabled={busy}
              spellCheck={false}
              rows={3}
            />
            <div style={ppStyles.freeInputActions}>
              <button
                className="ts-btn ts-btn--primary"
                style={{
                  opacity: !freeInput.trim() || busy ? 0.5 : 1,
                  pointerEvents: !freeInput.trim() || busy ? "none" : "auto",
                }}
                onClick={handleSubmitFreeWithReflect}
                type="button"
              >
                <span>{busy ? t("play.action_busy") : t("play.action_submit")}</span>
                {!busy ? (
                  <span style={ppStyles.kbdInline} aria-hidden>
                    <kbd>{submitModKey}</kbd>
                    <kbd>↵</kbd>
                  </span>
                ) : null}
              </button>
              {options.length > 0 ? (
                <button
                  className="ts-btn ts-btn--ghost"
                  onClick={() => {
                    setShowFreeInput(false)
                    setFreeInput("")
                  }}
                  disabled={busy}
                  type="button"
                >
                  {t("play.action_cancel")}
                </button>
              ) : null}
            </div>
          </motion.div>
        ) : (
          <motion.button
            key="free-input-toggle"
            style={ppStyles.freeInputToggle}
            onClick={() => setShowFreeInput(true)}
            disabled={busy}
            type="button"
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: "auto", marginTop: 12 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            transition={transitions.snap}
          >
            {t("play.action_open_free")}
          </motion.button>
        )}
      </AnimatePresence>

      {/* Diary input — private inner monologue. Sits alongside the action
          and gets sent with the next submission. NPCs cannot see it. */}
      <AnimatePresence mode="wait" initial={false}>
        {showDiary ? (
          <motion.div
            key="diary-open"
            style={ppStyles.diaryBox}
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: "auto", marginTop: 14 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            transition={transitions.snap}
          >
            <div style={ppStyles.diaryLabel}>
              <span style={ppStyles.diaryLabelTag}>{t("play.beat_diary_tag")}</span>
              <span style={ppStyles.diaryLabelHint}>
                {t("play.diary_label_hint")}
              </span>
            </div>
            <textarea
              style={ppStyles.diaryTextarea}
              value={diary}
              placeholder={t("play.diary_placeholder")}
              onChange={(e) => setDiary(e.target.value)}
              disabled={busy}
              spellCheck={false}
              rows={2}
              maxLength={600}
            />
            <button
              className="ts-btn ts-btn--ghost"
              onClick={() => {
                setShowDiary(false)
                setDiary("")
              }}
              disabled={busy}
              type="button"
              style={{ fontSize: 12, padding: "4px 10px" }}
            >
              {t("play.diary_close")}
            </button>
          </motion.div>
        ) : (
          <motion.button
            key="diary-toggle"
            style={ppStyles.diaryToggle}
            onClick={() => setShowDiary(true)}
            disabled={busy}
            type="button"
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: "auto", marginTop: 10 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            transition={transitions.snap}
          >
            {t("play.diary_open")}
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Floating Advisor button
// ---------------------------------------------------------------------------

function AdvisorFab({
  onOpen,
  avatarUrl,
  persona,
}: {
  onOpen: () => void
  avatarUrl: string
  persona: string
}) {
  const t = useT()
  return (
    <motion.button
      style={ppStyles.fab}
      onClick={onOpen}
      title={persona}
      type="button"
      initial={{ opacity: 0, scale: 0.7, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: 0.4, type: "spring", stiffness: 280, damping: 18 }}
      whileHover={hoverLift}
      whileTap={tapPress}
    >
      <img src={avatarUrl} alt="" style={ppStyles.fabAvatarImg} loading="lazy" />
      <span style={ppStyles.fabLabel}>{t("play.fab_label")}</span>
    </motion.button>
  )
}

// ---------------------------------------------------------------------------
// Advisor sidechat panel
// ---------------------------------------------------------------------------

function AdvisorSidechat({
  sessionId,
  persona,
  avatarUrl,
  turnsRemaining,
  isComplete,
  onClose,
  onOracleConsumed,
}: {
  sessionId: string
  persona: string
  avatarUrl: string
  turnsRemaining: number
  isComplete: boolean
  onClose: () => void
  onOracleConsumed: (newBudget: number) => void
}) {
  const api = useApi()
  const t = useT()
  const [messages, setMessages] = useState<NarrativeAdvisorMessage[]>([])
  const [oracleOrds, setOracleOrds] = useState<Set<number>>(new Set())
  const [draft, setDraft] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getNarrativeAdvisorHistory(sessionId)
      .then((res) => {
        if (cancelled) return
        setMessages(res.messages)
      })
      .catch((err) => {
        if (cancelled) return
        setError(friendlyError(err, "顾问历史加载失败。"))
      })
    return () => {
      cancelled = true
    }
  }, [api, sessionId])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [messages.length])

  const handleAsk = async (oracle: boolean) => {
    const question = draft.trim()
    if (!question || busy) return
    if (oracle && isComplete) {
      setError(t("play.oracle_completed_error"))
      return
    }
    if (oracle) {
      const ok = window.confirm(
        t("play.oracle_confirm", {
          before: turnsRemaining,
          after: Math.max(1, turnsRemaining - 1),
        }),
      )
      if (!ok) return
    }
    setBusy(true)
    setError(null)
    setDraft("")
    try {
      const res = await api.askNarrativeAdvisor(sessionId, {
        question,
        ...(oracle ? { oracle_mode: true } : {}),
      })
      setMessages((prev) => [...prev, res.player_message, res.advisor_message])
      if (res.oracle_used) {
        setOracleOrds((prev) => {
          const next = new Set(prev)
          next.add(res.advisor_message.ord)
          return next
        })
        if (typeof res.turn_budget_after === "number") {
          onOracleConsumed(res.turn_budget_after)
        }
      }
    } catch (err) {
      setError(friendlyError(err, "顾问没回上你这一句，再试一次？"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <motion.div
        style={ppStyles.advisorBackdrop}
        onClick={onClose}
        variants={fadeVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={fadeTransition}
      />
      <motion.aside
        style={ppStyles.advisorPanel}
        variants={slideInRightVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={slideInRightTransition}
      >
        <header style={ppStyles.advisorHeader}>
          <img src={avatarUrl} alt="" style={ppStyles.advisorHeaderAvatar} loading="lazy" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={ppStyles.advisorTitle}>{t("play.advisor_title")}</div>
            <div style={ppStyles.advisorPersona}>{persona}</div>
          </div>
          <button style={ppStyles.advisorClose} onClick={onClose} type="button">
            ✕
          </button>
        </header>

        <div style={ppStyles.advisorMessages} ref={scrollerRef}>
          {messages.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2, ...transitions.medium }}
              style={ppStyles.advisorIntro}
            >
              {t("play.advisor_intro")}
            </motion.div>
          ) : (
            messages.map((m) => {
              const isOracle = m.role === "advisor" && oracleOrds.has(m.ord)
              return (
                <motion.div
                  key={`${m.role}-${m.ord}`}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={itemTransition}
                  style={m.role === "player" ? ppStyles.advisorRowPlayer : ppStyles.advisorRowAdvisor}
                >
                  {isOracle ? (
                    <div style={ppStyles.oracleBadge}>{t("play.oracle_badge")}</div>
                  ) : null}
                  {isOracle ? (
                    <div style={ppStyles.oracleBubbleWrap}>
                      <div
                        style={{
                          ...ppStyles.oracleVignette,
                          backgroundImage: `url(${ORACLE_VIGNETTE})`,
                        }}
                        aria-hidden
                      />
                      <div
                        style={{ ...ppStyles.advisorBubbleOracle, position: "relative", zIndex: 1 }}
                      >
                        {m.content}
                      </div>
                    </div>
                  ) : (
                    <div
                      style={
                        m.role === "player"
                          ? ppStyles.advisorBubblePlayer
                          : ppStyles.advisorBubbleAdvisor
                      }
                    >
                      {m.content}
                    </div>
                  )}
                </motion.div>
              )
            })
          )}
          {busy ? <TypingDots /> : null}
        </div>

        {error ? <div style={ppStyles.advisorError}>{error}</div> : null}

        <div style={ppStyles.advisorInput}>
          <textarea
            style={ppStyles.advisorTextarea}
            value={draft}
            placeholder={t("play.advisor_textarea_placeholder")}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault()
                void handleAsk(false)
              }
            }}
            disabled={busy}
            rows={2}
          />
          <div style={ppStyles.advisorBtnRow}>
            <button
              className="ts-btn ts-btn--primary"
              onClick={() => void handleAsk(false)}
              disabled={busy || !draft.trim()}
              type="button"
            >
              {t("play.advisor_send")}
            </button>
            <button
              style={ppStyles.oracleBtn}
              onClick={() => void handleAsk(true)}
              disabled={busy || !draft.trim() || isComplete || turnsRemaining <= 1}
              type="button"
              title={
                isComplete
                  ? t("play.oracle_tip_complete")
                  : turnsRemaining <= 1
                    ? t("play.oracle_tip_no_turns")
                    : t("play.oracle_tip_active", { turns: turnsRemaining })
              }
            >
              {t("play.oracle_button")}
            </button>
          </div>
        </div>
      </motion.aside>
    </>
  )
}

// Bouncing 3-dot typing indicator. Used in advisor sidechat while waiting
// for the LLM response. Pure CSS keyframes via inline animation.
function TypingDots() {
  return (
    <div style={ppStyles.typingRow}>
      <div style={ppStyles.typingBubble}>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            style={ppStyles.typingDot}
            animate={{ y: [0, -4, 0] }}
            transition={{
              duration: 0.9,
              repeat: Infinity,
              delay: i * 0.15,
              ease: "easeInOut",
            }}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const ppStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)", display: "flex", flexDirection: "column" },
  centerNote: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "var(--text-muted)",
    fontSize: 14,
  },

  header: {
    padding: "0",
    borderBottom: "1px solid var(--line)",
    display: "flex",
    flexDirection: "column",
    background: "var(--bg)",
    position: "sticky",
    top: 0,
    zIndex: 5,
  },
  headerRow: {
    padding: "16px 32px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  headerWithCover: {
    backgroundSize: "cover",
    backgroundPosition: "center 35%",
    borderBottom: "1px solid rgba(255,255,255,0.1)",
  },
  progressTrack: {
    height: 3,
    background: "rgba(255,255,255,0.08)",
    position: "relative",
  },
  progressFill: {
    height: "100%",
    background: "var(--accent)",
    transition: "width 480ms ease-out",
    boxShadow: "0 0 8px rgba(var(--accent-rgb,201,90,67), 0.6)",
  },
  backBtnOnCover: {
    color: "white",
    background: "rgba(255,255,255,0.14)",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: 999,
    padding: "5px 12px",
    backdropFilter: "blur(6px)",
    width: "auto",
  },
  backBtn: {
    fontSize: 13,
    color: "var(--text-muted)",
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: 4,
    width: 90,
    textAlign: "left",
  },
  headerTitle: { flex: 1, textAlign: "center", minWidth: 0 },
  headerTitleLine: {
    fontFamily: "var(--font-narrative)",
    fontSize: 17,
    color: "var(--text)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerCast: {
    fontSize: 12,
    color: "var(--text-faint)",
    marginTop: 4,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  headerTurns: { marginLeft: 8 },

  main: { flex: 1, display: "flex", justifyContent: "center", overflow: "hidden" },
  storyColumn: { width: "100%", maxWidth: 720, padding: "32px 32px 120px", overflowY: "auto" },

  castStrip: {
    display: "flex",
    gap: 8,
    overflowX: "auto",
    paddingBottom: 18,
    marginBottom: 20,
    borderBottom: "1px dashed var(--line)",
  },
  castChip: {
    flex: "0 0 auto",
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 12px 6px 6px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
  },
  castChipAvatar: {
    width: 30,
    height: 30,
    borderRadius: "50%",
    objectFit: "cover",
  },
  castChipText: {
    display: "flex",
    flexDirection: "column",
    lineHeight: 1.2,
    // Cap the chip text column so long names truncate instead of
    // bloating the cast strip and pushing later chips off screen.
    maxWidth: 140,
    minWidth: 0,
  },
  castChipName: { fontSize: 12.5, fontWeight: 500, color: "var(--text)" },
  castChipRole: { fontSize: 10.5, color: "var(--text-faint)", marginTop: 2 },

  // Stage-direction-style identity framing line. Single sentence,
  // small caps prefix in muted text, role label in narrative serif
  // at a slightly bigger size. Sits above the role banner — the
  // *naming* of the role, the moment the user steps into the costume.
  identityFraming: {
    margin: "0 0 14px",
    padding: "10px 0 12px",
    borderTop: "1px dashed var(--line-strong)",
    borderBottom: "1px dashed var(--line-strong)",
    display: "flex",
    alignItems: "baseline",
    gap: 14,
    flexWrap: "wrap" as const,
  },
  identityFramingPrefix: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
    fontWeight: 500,
    flexShrink: 0,
  },
  identityFramingLabel: {
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    fontWeight: 500,
    color: "var(--text)",
    lineHeight: 1.2,
    letterSpacing: "-0.005em",
  },
  // Player-role banner — who YOU are this run, including your private cards
  roleBanner: {
    margin: "0 0 16px",
    padding: "16px 18px",
    background: "linear-gradient(180deg, rgba(120,80,180,0.10), rgba(120,80,180,0.03))",
    border: "1px solid rgba(140,100,200,0.34)",
    borderRadius: "var(--radius-md)",
  },
  roleBannerHeader: {
    display: "flex",
    alignItems: "baseline",
    gap: 10,
    marginBottom: 8,
    flexWrap: "wrap" as const,
  },
  roleBannerYou: {
    padding: "2px 8px",
    background: "#7e58c8",
    color: "white",
    borderRadius: 4,
    fontSize: 10.5,
    fontWeight: 700,
    letterSpacing: "0.12em",
  },
  roleBannerLabel: {
    fontFamily: "var(--font-narrative)",
    fontSize: 17,
    color: "var(--text)",
    fontWeight: 500,
  },
  roleBannerPersona: {
    fontSize: 13,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    margin: "0 0 12px",
  },
  roleBannerSecret: {
    fontSize: 13,
    color: "var(--text)",
    lineHeight: 1.6,
    background: "rgba(0,0,0,0.22)",
    border: "1px dashed rgba(140,100,200,0.32)",
    borderRadius: 6,
    padding: "8px 12px",
    marginBottom: 8,
  },
  roleBannerSecretTag: {
    display: "inline-block",
    fontSize: 10,
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    color: "rgba(180,150,230,0.85)",
    fontWeight: 600,
    marginRight: 8,
  },
  roleBannerLevSection: {
    marginTop: 6,
    fontSize: 12.5,
    color: "var(--text-muted)",
    lineHeight: 1.6,
  },
  roleBannerLevList: {
    margin: "4px 0 0",
    padding: 0,
    listStyle: "none",
  },
  roleBannerLevNpc: {
    color: "rgba(180,150,230,0.95)",
    fontWeight: 600,
    marginRight: 6,
  },
  roleInvAcquired: {
    color: "rgba(245,200,120,0.92)",
    fontWeight: 500,
  },

  // Inventory delta toast — sits above pulse chips on a narrator beat
  invToast: {
    margin: "10px 0 8px",
    padding: "10px 14px",
    background: "linear-gradient(180deg, rgba(245,200,120,0.13), rgba(245,200,120,0.04))",
    border: "1px solid rgba(245,200,120,0.36)",
    borderRadius: 8,
    fontSize: 13,
    lineHeight: 1.55,
  },
  invToastAdded: {
    color: "rgba(245,210,140,1)",
    fontWeight: 600,
    display: "flex",
    alignItems: "baseline",
    gap: 8,
  },
  invToastRemoved: {
    color: "rgba(220,140,140,0.95)",
    fontWeight: 500,
    display: "flex",
    alignItems: "baseline",
    gap: 8,
    marginTop: 4,
  },
  invToastIcon: {
    fontSize: 15,
    fontWeight: 700,
    minWidth: 14,
  },
  invToastReason: {
    marginTop: 6,
    fontSize: 11.5,
    color: "var(--text-faint)",
    fontStyle: "italic" as const,
  },

  // Gauntlet-mode goals card
  goalsCard: {
    margin: "0 0 24px",
    padding: "14px 16px",
    background: "linear-gradient(180deg, rgba(220,80,60,0.10), rgba(220,80,60,0.04))",
    border: "1px solid rgba(220,80,60,0.32)",
    borderRadius: "var(--radius-md)",
  },
  goalsHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 10,
  },
  gauntletBadge: {
    padding: "2px 8px",
    background: "#dc6b4a",
    color: "white",
    borderRadius: 4,
    fontSize: 10.5,
    fontWeight: 700,
    letterSpacing: "0.12em",
  },
  goalsTitle: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    letterSpacing: "0.04em",
  },
  goalRow: {
    marginBottom: 8,
    paddingLeft: 4,
  },
  goalText: {
    fontSize: 14,
    color: "var(--text)",
    fontFamily: "var(--font-narrative)",
    lineHeight: 1.5,
  },
  goalStakes: {
    fontSize: 11.5,
    color: "var(--text-faint)",
    marginTop: 3,
    paddingLeft: 16,
    fontStyle: "italic",
    lineHeight: 1.4,
  },

  // Per-turn NPC pulse strip
  pulseStrip: {
    marginTop: 14,
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  pulseRow: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap" as const,
  },
  // Reason explanation paired with each pulse chip — this is the
  // *because* of "she went colder because you...". Previously
  // rendered at faint fontSize 11 — easy to miss. Bumped to 12.5 +
  // muted (not faint) color, with a leading arrow glyph that
  // visually links the cause to the chip on its left. Without this,
  // users couldn't see that NPCs are reacting to THEM specifically.
  pulseReason: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    fontStyle: "italic" as const,
    lineHeight: 1.55,
    paddingLeft: 4,
    flex: "1 1 60%",
    minWidth: 0,
  },
  pulseReasonArrow: {
    color: "var(--text-faint)",
    fontSize: 11,
    fontStyle: "normal" as const,
    marginRight: 4,
  },
  pulseChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "3px 10px",
    border: "1px solid var(--line)",
    borderRadius: 999,
    fontSize: 11.5,
    background: "var(--bg-elev)",
  },
  pulseChipName: { fontWeight: 600, color: "var(--text)" },
  pulseChipState: { color: "var(--text-muted)" },
  pulseChipArrow: { marginLeft: 2, fontSize: 12 },
  pulseLegend: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap" as const,
    marginBottom: 24,
    padding: "8px 12px",
    background: "rgba(255,255,255,0.02)",
    border: "1px dashed var(--line)",
    borderRadius: "var(--radius-sm)",
  },
  pulseLegendLabel: {
    fontSize: 10.5,
    color: "var(--text-faint)",
    letterSpacing: "0.10em",
    textTransform: "uppercase" as const,
    marginRight: 4,
  },
  pulseLegendItem: {
    fontSize: 10.5,
    padding: "2px 8px",
    borderRadius: 999,
    border: "1px solid var(--line)",
    color: "var(--text-muted)",
    letterSpacing: "0.04em",
  },
  pulseShift_warmer: { borderColor: "rgba(80,180,120,0.5)", background: "rgba(80,180,120,0.08)" },
  pulseShift_colder: { borderColor: "rgba(140,160,200,0.5)", background: "rgba(140,160,200,0.08)" },
  pulseShift_wary: { borderColor: "rgba(220,180,80,0.5)", background: "rgba(220,180,80,0.10)" },
  pulseShift_broken: { borderColor: "rgba(220,80,60,0.6)", background: "rgba(220,80,60,0.12)", color: "var(--warn)" },
  pulseShift_steady: {},

  // Ending tier badge over banner image
  endingTierBadge: {
    position: "absolute",
    top: 16,
    left: 16,
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: "5px 12px",
    background: "rgba(0,0,0,0.55)",
    backdropFilter: "blur(6px)",
    borderRadius: 4,
    border: "1px solid rgba(255,255,255,0.18)",
  },
  endingTierBadgeText: {
    fontSize: 11,
    color: "white",
    fontWeight: 700,
    letterSpacing: "0.18em",
  },
  endingTierTrigger: {
    fontSize: 11,
    color: "rgba(255,255,255,0.78)",
  },

  narratorBeat: { marginBottom: 32, position: "relative" as const, paddingRight: 36 },
  // Bookmarked beat — soft accent ring on the left edge, signals
  // "you marked this" without competing with the rising/peak intensity
  // ramp.
  narratorBeatBookmarked: {
    background: "linear-gradient(90deg, var(--accent-soft) 0%, transparent 16%)",
    borderRadius: "var(--radius-sm)",
  },
  beatBookmarkBtn: {
    position: "absolute" as const,
    top: 0,
    right: 0,
    width: 28,
    height: 28,
    padding: 0,
    background: "transparent",
    border: "none",
    color: "var(--text-faint)",
    fontSize: 18,
    lineHeight: 1,
    cursor: "pointer",
    transition: "color 160ms, transform 160ms",
    borderRadius: 4,
  },
  beatBookmarkBtnActive: {
    color: "var(--accent)",
  },
  narratorBeatRising: {
    marginBottom: 38,
    paddingLeft: 18,
    paddingTop: 8,
    borderLeft: "2px solid rgba(140,100,200,0.45)",
  },
  narratorBeatPeak: {
    marginBottom: 48,
    paddingLeft: 22,
    paddingTop: 12,
    paddingRight: 4,
    borderLeft: "3px solid rgba(245,200,120,0.75)",
    background:
      "linear-gradient(90deg, rgba(245,200,120,0.06) 0%, rgba(245,200,120,0) 60%)",
    boxShadow: "inset 0 0 0 0 rgba(245,200,120,0)",
  },
  narratorText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16.5,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
  },
  narratorTextRising: {
    fontSize: 17.5,
    lineHeight: 1.9,
    letterSpacing: "0.005em",
  },
  narratorTextPeak: {
    fontSize: 19,
    lineHeight: 1.95,
    letterSpacing: "0.01em",
    color: "rgba(255,235,210,0.96)",
  },
  beatSceneBanner: {
    height: 140,
    backgroundSize: "cover",
    backgroundPosition: "center",
    // Bleed past the parent padding (paddingLeft 22, paddingRight 4) by
    // pulling the box left/right with negative margins; the natural
    // width with auto becomes parent width + 26.
    marginLeft: -22,
    marginRight: -4,
    marginTop: -12,
    marginBottom: 18,
    borderRadius: "0 0 6px 6px",
  },
  beatDecorRising: {
    width: 36,
    height: 1,
    background: "rgba(140,100,200,0.55)",
    marginBottom: 12,
  },
  beatDecorPeak: {
    width: 56,
    height: 2,
    background: "linear-gradient(90deg, rgba(245,200,120,0.85), rgba(245,200,120,0))",
    marginBottom: 14,
  },
  chosenChip: {
    marginTop: 14,
    fontSize: 12,
    color: "var(--text-faint)",
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: "5px 12px",
    border: "1px solid var(--line)",
    borderRadius: 999,
    background: "var(--bg-elev)",
  },
  chosenLabel: { letterSpacing: "0.06em" },
  chosenText: { color: "var(--text-muted)" },

  playerBeat: { marginBottom: 28, paddingLeft: 16, borderLeft: "2px solid var(--accent)" },
  // Picked-option memory handle chip — sits inline next to the
  // "you" label. Reads as "you · 亮录音" so users can later say
  // "I picked '亮录音' that turn" instead of re-parsing the full
  // intent-tagged sentence below.
  playerHandleChip: {
    fontSize: 11.5,
    fontFamily: "var(--font-narrative)",
    fontWeight: 500,
    color: "var(--accent)",
    background: "var(--accent-soft)",
    padding: "2px 8px",
    borderRadius: 4,
    letterSpacing: 0,
    textTransform: "none" as const,
    fontStyle: "normal" as const,
  },
  playerLabelSeparator: {
    margin: "0 6px",
    color: "var(--text-faint)",
    letterSpacing: 0,
  },
  playerLabel: {
    fontSize: 11,
    color: "var(--accent)",
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  playerText: { fontSize: 14.5, lineHeight: 1.6, color: "var(--text-muted)", fontStyle: "italic" },
  playerDiary: {
    marginTop: 8,
    padding: "8px 12px",
    background: "rgba(140,100,200,0.06)",
    border: "1px dashed rgba(140,100,200,0.32)",
    borderRadius: 6,
    display: "flex",
    flexDirection: "column" as const,
    gap: 4,
  },
  playerDiaryTag: {
    fontSize: 10,
    color: "rgba(180,150,230,0.85)",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    fontWeight: 600,
  },
  playerDiaryText: {
    fontSize: 13,
    lineHeight: 1.65,
    color: "rgba(220,210,240,0.92)",
    fontFamily: "var(--font-narrative)",
  },

  actionArea: {
    marginTop: 28,
    paddingTop: 24,
    paddingBottom: 16,
    borderTop: "1px dashed var(--line)",
    // Sticky to bottom of the scrolling story column so when the player
    // scrolls up to re-read past beats the action area stays reachable.
    // Backdrop blur + a slight bg fade so the prose underneath dims
    // gracefully without blocking text outright.
    position: "sticky" as const,
    bottom: 0,
    background:
      "linear-gradient(180deg, rgba(12,12,16,0) 0%, rgba(12,12,16,0.92) 18%, var(--bg) 40%)",
    backdropFilter: "blur(2px)",
    zIndex: 2,
  },
  optionsList: { display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 },
  optionBtn: {
    textAlign: "left",
    padding: "14px 18px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    color: "var(--text)",
    cursor: "pointer",
    transition: "all 160ms",
  },
  // Picked-state highlight — gold accent border + soft shadow.
  // Stacked over `optionBtn` via spread.
  optionBtnPicked: {
    borderColor: "var(--accent)",
    background: "linear-gradient(180deg, rgba(212,168,83,0.16), rgba(212,168,83,0.06))",
    boxShadow: "0 8px 28px -12px rgba(212,168,83,0.6)",
  },
  // Reflective banner shown right under the options after the user
  // picks one — bridges the 5-8s LLM wait with a "yes, we got it"
  // visual signal.
  pickedReflect: {
    marginTop: 12,
    padding: "10px 14px",
    background: "rgba(212,168,83,0.08)",
    border: "1px solid rgba(212,168,83,0.32)",
    borderRadius: "var(--radius-md)",
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 13,
    color: "var(--accent)",
    letterSpacing: "0.02em",
    fontStyle: "italic" as const,
  },
  pickedReflectIcon: {
    fontSize: 14,
    fontWeight: 600,
    fontStyle: "normal" as const,
  },
  // Memory-handle echo on the picked-reflect banner. Visually
  // distinct from the "submitting…" copy via heavier weight + the
  // accent color. Anchors the moment as "this is what I picked."
  pickedReflectHandle: {
    fontWeight: 600,
    color: "var(--accent)",
    fontStyle: "normal" as const,
    letterSpacing: "0.02em",
    marginLeft: 2,
  },
  optionLabel: {
    fontSize: 15,
    fontWeight: 500,
    lineHeight: 1.4,
    display: "flex",
    alignItems: "baseline",
    gap: 8,
    flexWrap: "wrap" as const,
  },
  optionTagChip: {
    fontSize: 11,
    fontWeight: 600,
    padding: "2px 8px",
    borderRadius: 4,
    letterSpacing: "0.04em",
    flexShrink: 0,
    fontFamily: "var(--font-narrative)",
  },
  // Number-key shortcut hint chip on the leading edge of each option.
  // Shares look-and-feel with global `kbd` but is a touch larger so
  // it's clearly a hit target hint, not just a label.
  optionKbd: {
    flexShrink: 0,
    minWidth: 22,
    height: 22,
    fontSize: 11.5,
    color: "var(--text-muted)",
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line-strong)",
    borderBottomWidth: 2,
    borderRadius: 5,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "var(--font-ui)",
  },
  // Inline keyboard hint (e.g. `⌘ ↵` next to the Send button).
  kbdInline: {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    marginLeft: 10,
    opacity: 0.7,
  },
  optionHint: { fontSize: 12.5, color: "var(--text-muted)", marginTop: 5, lineHeight: 1.45 },
  noOptions: { fontSize: 13, color: "var(--text-faint)", fontStyle: "italic" },

  freeInputBox: {
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    padding: 14,
  },
  freeTextarea: {
    width: "100%",
    background: "transparent",
    border: "none",
    fontFamily: "var(--font-narrative)",
    fontSize: 15,
    lineHeight: 1.6,
    color: "var(--text)",
    resize: "vertical",
    outline: "none",
    minHeight: 64,
  },
  freeInputActions: { display: "flex", gap: 8, marginTop: 10 },
  freeInputToggle: {
    background: "none",
    border: "none",
    color: "var(--text-muted)",
    fontSize: 13,
    padding: "8px 0",
    cursor: "pointer",
    textAlign: "left",
  },

  // Diary input — same shape as freeInputBox but purple-tinted to read
  // as private/inner monologue, paired with diary toggle button.
  diaryToggle: {
    background: "none",
    border: "none",
    color: "rgba(180,150,230,0.85)",
    fontSize: 12.5,
    padding: "6px 0",
    cursor: "pointer",
    textAlign: "left",
    fontStyle: "italic" as const,
  },
  diaryBox: {
    marginTop: 12,
    padding: "12px 14px",
    background: "rgba(140,100,200,0.05)",
    border: "1px dashed rgba(140,100,200,0.30)",
    borderRadius: "var(--radius-sm)",
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  },
  diaryLabel: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 2,
  },
  diaryLabelTag: {
    fontSize: 10,
    color: "rgba(180,150,230,0.92)",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    fontWeight: 600,
  },
  diaryLabelHint: {
    fontSize: 11,
    color: "var(--text-faint)",
    fontStyle: "italic" as const,
  },
  diaryTextarea: {
    width: "100%",
    background: "var(--bg-elev)",
    border: "1px solid rgba(140,100,200,0.20)",
    borderRadius: "var(--radius-sm)",
    fontSize: 13.5,
    lineHeight: 1.6,
    color: "rgba(230,220,240,0.95)",
    padding: "10px 12px",
    resize: "none" as const,
    outline: "none",
    fontFamily: "var(--font-narrative)",
  },

  busyShim: {
    marginTop: 24,
    paddingTop: 20,
    borderTop: "1px dashed var(--line)",
    color: "var(--text-faint)",
    fontSize: 13,
    fontStyle: "italic",
  },

  errorInline: {
    margin: "8px 0",
    padding: "10px 14px",
    background: "rgba(220,80,80,0.08)",
    border: "1px solid rgba(220,80,80,0.25)",
    borderRadius: "var(--radius-sm)",
    fontSize: 13,
    color: "var(--warn)",
    display: "flex",
    alignItems: "center",
    gap: 12,
    flexWrap: "wrap" as const,
  },
  errorInlineText: { flex: "1 1 0", minWidth: 0 },
  errorInlineRetry: {
    flexShrink: 0,
    fontSize: 12,
    padding: "5px 12px",
    minHeight: 28,
  },

  approachingFinaleBanner: {
    marginTop: 12,
    marginBottom: 20,
    padding: "10px 14px",
    background: "rgba(var(--accent-rgb,201,90,67), 0.08)",
    border: "1px solid var(--accent)",
    borderRadius: "var(--radius-sm)",
    fontSize: 13,
    color: "var(--accent)",
    fontStyle: "italic",
    textAlign: "center",
    letterSpacing: "0.04em",
  },

  endingSection: { marginTop: 40 },
  endingDivider: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    margin: "0 0 28px",
    position: "relative",
  },
  endingDividerLabel: {
    background: "var(--bg)",
    padding: "0 16px",
    fontSize: 12,
    color: "var(--text-faint)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    position: "relative",
    zIndex: 1,
  },
  endingCard: {
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-lg)",
    boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
    overflow: "hidden",
  },
  endingHero: {
    width: "100%",
    height: 220,
    backgroundSize: "cover",
    backgroundPosition: "center",
    marginBottom: -1,
    position: "relative",
    overflow: "hidden",
  },
  endingSplashOverlay: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    mixBlendMode: "screen",
    pointerEvents: "none",
  },
  endingCardInner: { padding: "24px 28px 28px" },
  endingLabelChip: {
    display: "inline-block",
    padding: "5px 14px",
    background: "var(--accent-soft)",
    color: "var(--accent)",
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 600,
    letterSpacing: "0.06em",
    marginBottom: 16,
  },
  endingSubtitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 26,
    lineHeight: 1.35,
    fontWeight: 400,
    margin: "0 0 24px",
    color: "var(--text)",
  },
  endingPassage: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
    paddingBottom: 28,
    borderBottom: "1px dashed var(--line)",
    marginBottom: 24,
  },
  // Highlight reel below ending passage — chronological pivotal moments
  highlightReel: {
    marginBottom: 28,
    paddingBottom: 28,
    borderBottom: "1px dashed var(--line)",
  },
  highlightReelLabel: {
    fontSize: 11,
    color: "rgba(245,200,120,0.92)",
    letterSpacing: "0.12em",
    textTransform: "uppercase" as const,
    fontWeight: 600,
    marginBottom: 16,
  },
  highlightList: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 12,
  },
  highlightCard: {
    padding: "14px 16px",
    background: "linear-gradient(180deg, rgba(245,200,120,0.06), rgba(245,200,120,0.02))",
    border: "1px solid rgba(245,200,120,0.22)",
    borderRadius: "var(--radius-sm)",
    display: "flex",
    flexDirection: "column" as const,
    gap: 8,
  },
  // User-bookmarked highlight — slightly heavier accent border
  // and a soft side bar so the card reads as "your call" rather
  // than "what the system thought."
  highlightCardUserMarked: {
    borderColor: "rgba(245,200,120,0.45)",
    boxShadow: "inset 3px 0 0 0 var(--accent)",
  },
  highlightUserMark: {
    color: "var(--accent)",
    fontSize: 13,
    lineHeight: 1,
  },
  highlightHeader: {
    display: "flex",
    alignItems: "baseline",
    gap: 10,
  },
  highlightIndex: {
    fontSize: 12,
    color: "rgba(245,200,120,0.85)",
    fontWeight: 700,
    minWidth: 18,
    fontFamily: "var(--font-narrative)",
  },
  highlightHeadline: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16,
    fontWeight: 500,
    color: "rgba(255,235,210,0.96)",
    lineHeight: 1.35,
  },
  highlightBody: {
    fontSize: 13.5,
    lineHeight: 1.7,
    color: "var(--text)",
    paddingLeft: 28,
    fontFamily: "var(--font-narrative)",
  },
  highlightWhy: {
    fontSize: 12,
    color: "var(--text-muted)",
    lineHeight: 1.55,
    paddingLeft: 28,
    fontStyle: "italic" as const,
  },

  // Branches section — alternate paths the player didn't take
  branchesSection: {
    marginBottom: 28,
    paddingBottom: 28,
    borderBottom: "1px dashed var(--line)",
  },
  branchesLabel: {
    fontSize: 11,
    color: "rgba(180,150,230,0.92)",
    letterSpacing: "0.12em",
    textTransform: "uppercase" as const,
    fontWeight: 600,
    marginBottom: 8,
  },
  branchesHint: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    lineHeight: 1.55,
    margin: "0 0 16px",
    fontStyle: "italic" as const,
  },
  branchList: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 12,
  },
  branchCard: {
    position: "relative" as const,
    padding: "14px 16px",
    background: "linear-gradient(180deg, rgba(140,100,200,0.06), rgba(140,100,200,0.02))",
    border: "1px solid rgba(140,100,200,0.28)",
    borderRadius: "var(--radius-sm)",
    display: "flex",
    flexDirection: "column" as const,
    gap: 10,
  },
  branchTurnBadge: {
    position: "absolute" as const,
    top: -1,
    right: 12,
    fontSize: 10,
    color: "rgba(180,150,230,0.9)",
    background: "rgba(140,100,200,0.18)",
    border: "1px solid rgba(140,100,200,0.30)",
    borderTop: "none",
    padding: "3px 8px",
    borderRadius: "0 0 4px 4px",
    letterSpacing: "0.06em",
    fontWeight: 600,
  },
  branchPaths: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  branchChosen: {
    fontSize: 13,
    lineHeight: 1.55,
    color: "var(--text-muted)",
    display: "flex",
    flexDirection: "column" as const,
  },
  branchAlternate: {
    fontSize: 13,
    lineHeight: 1.55,
    color: "var(--text)",
    display: "flex",
    flexDirection: "column" as const,
  },
  branchPathTag: {
    fontSize: 10,
    color: "var(--text-faint)",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    marginBottom: 2,
  },
  branchPathText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 14,
  },
  branchArrow: {
    fontSize: 10.5,
    color: "rgba(180,150,230,0.8)",
    letterSpacing: "0.12em",
    textAlign: "center" as const,
    padding: "2px 0",
  },
  branchOutcome: {
    display: "flex",
    alignItems: "flex-start",
    gap: 10,
    paddingTop: 8,
    borderTop: "1px dashed rgba(140,100,200,0.18)",
  },
  branchEndingChip: {
    fontFamily: "var(--font-narrative)",
    fontSize: 13,
    fontWeight: 600,
    padding: "4px 10px",
    borderRadius: 999,
    flexShrink: 0,
    letterSpacing: "0.04em",
  },
  branchTierVictory: {
    background: "linear-gradient(90deg, rgba(212,168,83,0.22), rgba(212,168,83,0.08))",
    color: "rgba(245,210,140,0.96)",
    border: "1px solid rgba(212,168,83,0.45)",
  },
  branchTierCompromised: {
    background: "rgba(255,255,255,0.05)",
    color: "var(--text)",
    border: "1px solid var(--line)",
  },
  branchTierCollapsed: {
    background: "linear-gradient(90deg, rgba(220,80,60,0.20), rgba(220,80,60,0.06))",
    color: "rgba(245,180,170,0.96)",
    border: "1px solid rgba(220,80,60,0.42)",
  },
  branchRationale: {
    fontSize: 12,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    fontStyle: "italic" as const,
    flex: 1,
  },

  endingActions: { display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 },
  endingActionsRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    flexWrap: "wrap" as const,
  },
  endingShareHint: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    margin: 0,
    lineHeight: 1.5,
  },

  fab: {
    position: "fixed",
    bottom: 24,
    right: 24,
    background: "var(--accent)",
    color: "white",
    border: "none",
    borderRadius: 999,
    padding: "10px 16px 10px 10px",
    display: "inline-flex",
    alignItems: "center",
    gap: 10,
    cursor: "pointer",
    boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
    zIndex: 20,
  },
  fabAvatarImg: {
    width: 32,
    height: 32,
    borderRadius: "50%",
    objectFit: "cover",
    border: "2px solid rgba(255,255,255,0.45)",
  },
  fabLabel: { fontSize: 14, fontWeight: 500 },

  advisorBackdrop: { position: "fixed", inset: 0, background: "rgba(0,0,0,0.18)", zIndex: 30 },
  advisorPanel: {
    position: "fixed",
    top: 0,
    right: 0,
    bottom: 0,
    width: "min(420px, 95vw)",
    background: "var(--bg)",
    borderLeft: "1px solid var(--line)",
    display: "flex",
    flexDirection: "column",
    zIndex: 31,
    boxShadow: "-12px 0 32px rgba(0,0,0,0.12)",
  },
  advisorHeader: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "16px 20px",
    borderBottom: "1px solid var(--line)",
  },
  advisorHeaderAvatar: {
    width: 44,
    height: 44,
    borderRadius: "50%",
    objectFit: "cover",
    border: "1px solid var(--line)",
    flexShrink: 0,
  },
  advisorTitle: { fontFamily: "var(--font-narrative)", fontSize: 16, color: "var(--text)" },
  advisorPersona: {
    fontSize: 12,
    color: "var(--text-faint)",
    lineHeight: 1.4,
    marginTop: 4,
    maxWidth: 320,
  },
  advisorClose: {
    background: "none",
    border: "none",
    color: "var(--text-muted)",
    fontSize: 18,
    cursor: "pointer",
    padding: 4,
  },
  advisorMessages: { flex: 1, overflowY: "auto", padding: "20px" },
  advisorIntro: {
    fontSize: 13,
    color: "var(--text-faint)",
    lineHeight: 1.6,
    padding: "16px 14px",
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-sm)",
    border: "1px solid var(--line)",
  },
  advisorRowPlayer: { display: "flex", justifyContent: "flex-end", marginBottom: 12 },
  advisorRowAdvisor: {
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "flex-start",
    marginBottom: 12,
    gap: 4,
  },
  advisorBubblePlayer: {
    background: "var(--accent)",
    color: "white",
    padding: "10px 14px",
    borderRadius: "16px 16px 4px 16px",
    fontSize: 14,
    lineHeight: 1.55,
    maxWidth: "82%",
  },
  advisorBubbleAdvisor: {
    background: "var(--bg-elev)",
    color: "var(--text)",
    padding: "10px 14px",
    borderRadius: "16px 16px 16px 4px",
    fontSize: 14,
    lineHeight: 1.6,
    maxWidth: "82%",
    border: "1px solid var(--line)",
  },
  advisorBubbleOracle: {
    background: "linear-gradient(180deg, rgba(245,200,120,0.15), rgba(245,200,120,0.05))",
    color: "rgba(255,235,200,0.96)",
    padding: "10px 14px",
    borderRadius: "16px 16px 16px 4px",
    fontSize: 14,
    lineHeight: 1.6,
    maxWidth: "82%",
    border: "1px solid rgba(245,200,120,0.4)",
    boxShadow: "0 0 0 1px rgba(245,200,120,0.08), 0 4px 16px rgba(245,200,120,0.06)",
  },
  oracleBubbleWrap: {
    position: "relative" as const,
    maxWidth: "82%",
    borderRadius: "16px 16px 16px 4px",
    overflow: "hidden",
  },
  oracleVignette: {
    position: "absolute" as const,
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    opacity: 0.32,
    pointerEvents: "none" as const,
    borderRadius: "16px 16px 16px 4px",
    mixBlendMode: "overlay" as const,
  },
  oracleBadge: {
    fontSize: 10.5,
    color: "rgba(245,210,140,0.92)",
    letterSpacing: "0.06em",
    fontWeight: 600,
    marginBottom: 4,
    background: "rgba(245,200,120,0.10)",
    border: "1px solid rgba(245,200,120,0.30)",
    padding: "2px 8px",
    borderRadius: 4,
    alignSelf: "flex-start" as const,
  },
  advisorTyping: { fontSize: 12, color: "var(--text-faint)", fontStyle: "italic", padding: "6px 14px" },
  typingRow: { display: "flex", justifyContent: "flex-start", marginBottom: 12 },
  typingBubble: {
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "16px 16px 16px 4px",
    padding: "12px 16px",
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
  },
  typingDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "var(--text-faint)",
    display: "inline-block",
  },
  advisorError: {
    margin: "0 20px 8px",
    padding: "8px 12px",
    background: "rgba(220,80,80,0.08)",
    border: "1px solid rgba(220,80,80,0.25)",
    borderRadius: "var(--radius-sm)",
    fontSize: 12,
    color: "var(--warn)",
  },
  advisorInput: {
    padding: "14px 20px",
    borderTop: "1px solid var(--line)",
    display: "flex",
    gap: 10,
    alignItems: "flex-end",
  },
  advisorTextarea: {
    flex: 1,
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
    fontSize: 14,
    lineHeight: 1.5,
    color: "var(--text)",
    padding: "10px 12px",
    resize: "none",
    outline: "none",
    fontFamily: "inherit",
  },
  advisorBtnRow: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
    alignItems: "stretch",
  },
  oracleBtn: {
    fontSize: 12,
    padding: "8px 12px",
    background: "linear-gradient(180deg, rgba(245,200,120,0.18), rgba(245,200,120,0.08))",
    color: "rgba(255,235,200,0.95)",
    border: "1px solid rgba(245,200,120,0.45)",
    borderRadius: "var(--radius-sm)",
    cursor: "pointer",
    fontFamily: "inherit",
    fontWeight: 500,
    whiteSpace: "nowrap" as const,
    transition: "filter 0.15s",
  },
}
