import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type {
  NarrativeAdvisorMessage,
  NarrativeEnding,
  NarrativeNPCPulse,
  NarrativeStoryHistoryResponse,
  NarrativeStoryMessage,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { LoadingShim } from "../../shared/ui/loading-shim"
import { friendlyError } from "../../shared/lib/friendly-error"
import {
  fadeTransition,
  fadeVariants,
  hoverLift,
  hoverNudge,
  itemTransition,
  itemVariants,
  pulseVariants,
  slideInRightTransition,
  slideInRightVariants,
  tapPress,
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
  const [story, setStory] = useState<NarrativeStoryHistoryResponse | null>(null)
  const [ending, setEnding] = useState<NarrativeEnding | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
        setError(friendlyError(err, "无法加载故事。"))
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
        setError(friendlyError(err, "续写失败，请稍后再试。"))
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
          <div style={ppStyles.centerNote}>加载失败：{error}</div>
        ) : (
          <LoadingShim label="故事正在加载…" />
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
                  <div style={ppStyles.castChipName}>{c.display_name}</div>
                  <div style={ppStyles.castChipRole}>{c.role}</div>
                </div>
              </div>
            ))}
          </div>

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
                <span style={ppStyles.roleBannerYou}>这一局的你</span>
                <span style={ppStyles.roleBannerLabel}>{story.session.player_role.label}</span>
              </div>
              <p style={ppStyles.roleBannerPersona}>
                {story.session.player_role.public_persona}
              </p>
              <div style={ppStyles.roleBannerSecret}>
                <span style={ppStyles.roleBannerSecretTag}>心里真正想要的</span>
                {story.session.player_role.hidden_objective}
              </div>
              {story.session.player_role.leverages_over_npcs.length > 0 ? (
                <div style={ppStyles.roleBannerLevSection}>
                  <span style={ppStyles.roleBannerSecretTag}>你手里的反将牌</span>
                  <ul style={ppStyles.roleBannerLevList}>
                    {story.session.player_role.leverages_over_npcs.map((lev, i) => (
                      <li key={i}>
                        <span style={ppStyles.roleBannerLevNpc}>
                          {castNameById[lev.npc_id] ?? lev.npc_id}
                        </span>
                        {lev.leverage}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {liveInventory.length > 0 ? (
                <div style={ppStyles.roleBannerLevSection}>
                  <span style={ppStyles.roleBannerSecretTag}>
                    手里的牌（{liveInventory.length}）
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
                            ...(isAcquired ? ppStyles.roleInvAcquired : {}),
                          }}
                        >
                          {isAcquired ? "+ " : "· "}
                          {item}
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
                <span style={ppStyles.gauntletBadge}>博弈模式</span>
                <span style={ppStyles.goalsTitle}>你这一局想要的：</span>
              </div>
              {story.template.player_goals.map((g, idx) => (
                <div key={idx} style={ppStyles.goalRow}>
                  <div style={ppStyles.goalText}>·  {g.goal}</div>
                  <div style={ppStyles.goalStakes}>失败：{g.stakes}</div>
                </div>
              ))}
            </motion.div>
          ) : null}

          {story.messages.map((m) => (
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
            />
          ))}

          {error ? <div style={ppStyles.errorInline}>{error}</div> : null}

          {isFinalApproaching && !busy ? (
            <motion.div
              style={ppStyles.approachingFinaleBanner}
              variants={pulseVariants}
              initial="initial"
              animate="animate"
            >
              {turnsRemaining === 0
                ? "故事正在收尾…"
                : turnsRemaining === 1
                  ? "下一段就是结局——慎选。"
                  : "还有 2 段就到结局——开始往那个方向收吧。"}
            </motion.div>
          ) : null}

          {/* Ending screen — only when the session has finished */}
          {isComplete && ending ? (
            <EndingScreen
              ending={ending}
              sessionId={sessionId}
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
                    window.prompt("复制这个链接发给朋友：", url)
                  },
                )
              }}
            />
          ) : null}

          {/* Action area pinned at the bottom of the story column.
              Hidden when the session is complete. */}
          {!isComplete && isLastNarratorPending && lastNarrator ? (
            <ActionArea
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
            <div style={ppStyles.busyShim}>故事在续写中…</div>
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
          ← 回到首页
        </button>
        <div style={ppStyles.headerTitle}>
          <div style={coverUrl ? { ...ppStyles.headerTitleLine, color: "white" } : ppStyles.headerTitleLine}>
            {title}
          </div>
          {cast && cast.length ? (
            <div
              style={
                coverUrl
                  ? { ...ppStyles.headerCast, color: "rgba(255,255,255,0.78)" }
                  : ppStyles.headerCast
              }
            >
              {cast.join(" · ")}
              {showProgress ? (
                <span style={ppStyles.headerTurns}>
                  · 第 {turnCount} / 共 {turnBudget} 段
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
  shareCopied,
  onShare,
}: {
  ending: NarrativeEnding
  sessionId: string
  shareCopied: boolean
  onShare: () => void
}) {
  void sessionId
  const illustration = getEndingIllustration(ending.label)
  const tier = ending.tier ?? "compromised"
  const tierSplash = getTierSplash(tier)
  const tierVisuals: Record<string, { ribbon: string; chipBg: string; chipColor: string; gradient: string; badgeText: string }> = {
    victory: {
      ribbon: "胜利结局",
      badgeText: "VICTORY",
      chipBg: "linear-gradient(90deg, #d4af37, #f7d97a)",
      chipColor: "#1a1108",
      gradient: "linear-gradient(180deg, rgba(180,140,40,0.0) 0%, rgba(60,40,15,0.55) 75%, var(--bg-elev) 100%)",
    },
    compromised: {
      ribbon: "妥协结局",
      badgeText: "COMPROMISED",
      chipBg: "rgba(255,255,255,0.12)",
      chipColor: "var(--text)",
      gradient: "linear-gradient(180deg, rgba(20,16,12,0.15) 0%, rgba(20,16,12,0.6) 75%, var(--bg-elev) 100%)",
    },
    collapsed: {
      ribbon: ending.early_terminated ? "提前崩盘" : "崩盘结局",
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
      initial="initial"
      animate="animate"
      transition={{ staggerChildren: 0.18, delayChildren: 0.1 }}
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
          initial={{ opacity: 0, scale: 1.06 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
          style={{
            ...ppStyles.endingHero,
            backgroundImage: `${tv.gradient}, url(${illustration})`,
          }}
        >
          {tierSplash ? (
            <motion.div
              initial={{ opacity: 0, scale: 1.12 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.25, duration: 0.95, ease: [0.16, 1, 0.3, 1] }}
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
                · 触发：{ending.failure_trigger}
              </span>
            ) : null}
          </div>
        </motion.div>
        <div style={ppStyles.endingCardInner}>
        <motion.div
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.45, type: "spring", stiffness: 320, damping: 18 }}
          style={{ ...ppStyles.endingLabelChip, background: tv.chipBg, color: tv.chipColor }}
        >
          {ending.label}
        </motion.div>
        <motion.h2
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6, ...itemTransition }}
          style={ppStyles.endingSubtitle}
        >
          「{ending.subtitle}」
        </motion.h2>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.85, duration: 0.6 }}
          style={ppStyles.endingPassage}
        >
          {ending.passage}
        </motion.div>

        {/* Highlight reel — 5 pivotal moments LLM picked from the run. */}
        {ending.highlights && ending.highlights.length > 0 ? (
          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.0, ...itemTransition }}
            style={ppStyles.highlightReel}
          >
            <div style={ppStyles.highlightReelLabel}>
              这一局的关键 {ending.highlights.length} 个时刻
            </div>
            <div style={ppStyles.highlightList}>
              {ending.highlights.map((h, i) => (
                <motion.div
                  key={`${h.beat_ord}-${i}`}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 1.05 + i * 0.08, ...itemTransition }}
                  style={ppStyles.highlightCard}
                >
                  <div style={ppStyles.highlightHeader}>
                    <span style={ppStyles.highlightIndex}>{i + 1}</span>
                    <span style={ppStyles.highlightHeadline}>{h.headline}</span>
                  </div>
                  <div style={ppStyles.highlightBody}>{h.body_excerpt}</div>
                  <div style={ppStyles.highlightWhy}>{h.why_pivotal}</div>
                </motion.div>
              ))}
            </div>
          </motion.section>
        ) : null}

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.4, ...itemTransition }}
          style={ppStyles.endingActions}
        >
          <motion.button
            className="ts-btn ts-btn--primary"
            onClick={onShare}
            type="button"
            style={{ minWidth: 200 }}
            whileHover={{ scale: 1.02 }}
            whileTap={tapPress}
            key={shareCopied ? "copied" : "default"}
            initial={shareCopied ? { scale: 0.92 } : false}
            animate={shareCopied ? { scale: [0.92, 1.06, 1] } : { scale: 1 }}
            transition={{ duration: 0.32 }}
          >
            {shareCopied ? "✓ 链接已复制" : "复制分享链接"}
          </motion.button>
          <p style={ppStyles.endingShareHint}>
            把链接发给朋友 — 他们能玩同一个开场，看自己会走出什么结局。
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
}: {
  message: NarrativeStoryMessage
  castNameById?: Record<string, string>
  intensity?: "calm" | "rising" | "peak"
  sceneUrl?: string
}) {
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
        style={beatStyle}
      >
        {intensity === "peak" && sceneUrl ? (
          <motion.div
            initial={{ opacity: 0, scale: 1.05 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
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
                你拿到：{item}
              </div>
            ))}
            {delta.removed.map((item, i) => (
              <div key={`rm-${i}`} style={ppStyles.invToastRemoved}>
                <span style={ppStyles.invToastIcon}>－</span>
                你失去了：{item}
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
            <span style={ppStyles.chosenLabel}>你选了</span>
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
              return (
                <span
                  key={`${p.npc_id}-${idx}`}
                  style={{ ...ppStyles.pulseChip, ...(shiftStyle ?? {}) }}
                  title={`${name}: ${p.state} (${p.shift})`}
                >
                  <span style={ppStyles.pulseChipName}>{name}</span>
                  <span style={ppStyles.pulseChipState}>· {p.state}</span>
                  <span style={ppStyles.pulseChipArrow}>{shiftArrow(p.shift)}</span>
                </span>
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
      <div style={ppStyles.playerLabel}>你</div>
      <div style={ppStyles.playerText}>{message.content}</div>
      {message.diary ? (
        <div style={ppStyles.playerDiary}>
          <span style={ppStyles.playerDiaryTag}>内心独白</span>
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
            （这一段没给选项，写下你想做的事）
          </div>
        ) : (
          options.map((opt, i) => (
            <motion.button
              key={i}
              style={{
                ...ppStyles.optionBtn,
                opacity: busy ? 0.5 : 1,
                pointerEvents: busy ? "none" : "auto",
              }}
              onClick={() => onPickOption(i)}
              disabled={busy}
              type="button"
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.05 * i + 0.1, ...itemTransition }}
              whileHover={busy ? undefined : hoverNudge}
              whileTap={busy ? undefined : tapPress}
            >
              <div style={ppStyles.optionLabel}>{opt.label}</div>
              {opt.hint ? <div style={ppStyles.optionHint}>{opt.hint}</div> : null}
            </motion.button>
          ))
        )}
      </div>

      {showFreeInput || options.length === 0 ? (
        <div style={ppStyles.freeInputBox}>
          <textarea
            style={ppStyles.freeTextarea}
            value={freeInput}
            placeholder="写下你想做的事——可以是动作、对话、或者一个决定。"
            onChange={(e) => setFreeInput(e.target.value)}
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
              onClick={onSubmitFree}
              type="button"
            >
              {busy ? "续写中…" : "就这么做 →"}
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
                取消
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        <button
          style={ppStyles.freeInputToggle}
          onClick={() => setShowFreeInput(true)}
          disabled={busy}
          type="button"
        >
          + 我想自己写一个动作
        </button>
      )}

      {/* Diary input — private inner monologue. Sits alongside the action
          and gets sent with the next submission. NPCs cannot see it. */}
      {showDiary ? (
        <div style={ppStyles.diaryBox}>
          <div style={ppStyles.diaryLabel}>
            <span style={ppStyles.diaryLabelTag}>内心独白</span>
            <span style={ppStyles.diaryLabelHint}>
              只有你和叙述者看得到 · NPC 听不到 · 跟下一个动作一起提交
            </span>
          </div>
          <textarea
            style={ppStyles.diaryTextarea}
            value={diary}
            placeholder="你心里真正在想什么？（30-200 字最佳，留空就是不写）"
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
            取消独白
          </button>
        </div>
      ) : (
        <button
          style={ppStyles.diaryToggle}
          onClick={() => setShowDiary(true)}
          disabled={busy}
          type="button"
        >
          + 写一句内心独白（NPC 看不到）
        </button>
      )}
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
      <span style={ppStyles.fabLabel}>聊聊</span>
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
      setError("这一局已经走完了，不能再消耗回合换情报。")
      return
    }
    if (oracle) {
      const ok = window.confirm(
        `用 1 回合换 advisor 的"看穿"提示？\n\n• 这会让你少 1 回合时间（剩余 ${turnsRemaining} → ${Math.max(1, turnsRemaining - 1)}）\n• advisor 会拿到只有 TA 才能看到的局势线索\n• 但 advisor 还是不会替你做决定\n\n继续？`,
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
            <div style={ppStyles.advisorTitle}>跟你的局外人朋友聊</div>
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
              transition={{ delay: 0.2, duration: 0.4 }}
              style={ppStyles.advisorIntro}
            >
              问 TA 任何事——你和谁的关系到了哪一步、那句话什么意思、你是不是太冲动了。
              TA 不会替你做决定，但会陪你想清楚。
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
                    <div style={ppStyles.oracleBadge}>🔮 情报 · 消耗了 1 回合</div>
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
            placeholder="想问什么？按 ⌘/Ctrl + Enter 发送"
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
              发送
            </button>
            <button
              style={ppStyles.oracleBtn}
              onClick={() => void handleAsk(true)}
              disabled={busy || !draft.trim() || isComplete || turnsRemaining <= 1}
              type="button"
              title={
                isComplete
                  ? "故事已结束"
                  : turnsRemaining <= 1
                    ? "回合不足，无法换情报"
                    : `用 1 回合换 advisor 的看穿（剩 ${turnsRemaining} 回合）`
              }
            >
              🔮 用 1 回合换情报
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
  castChipText: { display: "flex", flexDirection: "column", lineHeight: 1.2 },
  castChipName: { fontSize: 12.5, fontWeight: 500, color: "var(--text)" },
  castChipRole: { fontSize: 10.5, color: "var(--text-faint)", marginTop: 2 },

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
    flexWrap: "wrap",
    gap: 6,
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

  narratorBeat: { marginBottom: 32, position: "relative" as const },
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
  optionLabel: { fontSize: 15, fontWeight: 500, lineHeight: 1.4 },
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

  endingActions: { display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 10 },
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
