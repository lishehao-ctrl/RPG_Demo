import { type CSSProperties, useEffect, useState } from "react"
import type { NarrativePublicReplayResponse } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { friendlyError } from "../../shared/lib/friendly-error"
import { ENDING_LABEL_DISPLAY, useLanguage, useT } from "../../shared/lib/i18n"
import { LoadingShim } from "../../shared/ui/loading-shim"
import { EmptyState } from "../../shared/ui/empty-state"
import { Truncated } from "../../shared/ui/truncated"
import {
  getAdvisorAvatar,
  getAvatarForCastMember,
  getCoverForTemplate,
  getEndingIllustration,
} from "../../shared/lib/webtoon-assets"

/**
 * Public, auth-free replay of a completed (or in-progress) session.
 * Anyone with the URL can read the full playthrough including the
 * advisor sidechat. The whole point is to make sharing genuinely
 * compelling — your friend reads YOUR choices and YOUR ending,
 * then can fork the same template to play their own.
 */
export function ReplayPage({
  sessionId,
  onBackHome,
  onOpenTemplate,
}: {
  sessionId: string
  onBackHome: () => void
  onOpenTemplate: (templateId: string) => void
}) {
  const api = useApi()
  const t = useT()
  const { lang } = useLanguage()
  const [replay, setReplay] = useState<NarrativePublicReplayResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAdvisor, setShowAdvisor] = useState(true)
  // Entry mode for shared replay links:
  //   "preview" — hero + 5 highlight cards in a horizontal carousel +
  //   CTA. The default. Friends arriving from a shared link see the
  //   shape of the story at a glance, decide if they want to dive in.
  //   "full"    — the original 12-beat read, with skim toggle.
  // Switching is a single tap; preference is per-tab (not persisted).
  const [viewMode, setViewMode] = useState<"preview" | "full">("preview")
  // Skim mode: collapse narrator beats to a 3-line preview by default.
  // Friends opening a 12-turn replay link don't necessarily want to
  // read all 4000 words — they want to see the shape, then expand
  // the bits that catch their eye. Click a beat to expand it.
  const [skimMode, setSkimMode] = useState(true)
  const [expandedOrds, setExpandedOrds] = useState<Set<number>>(new Set())
  const toggleBeat = (ord: number) => {
    setExpandedOrds((prev) => {
      const next = new Set(prev)
      if (next.has(ord)) next.delete(ord)
      else next.add(ord)
      return next
    })
  }

  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .getNarrativePublicReplay(sessionId)
      .then((r) => {
        if (cancelled) return
        setReplay(r)
      })
      .catch((err) => {
        if (cancelled) return
        setError(friendlyError(err, t("replay.error_load_failed")))
      })
    return () => {
      cancelled = true
    }
  }, [api, sessionId, t])

  if (!replay) {
    return (
      <div style={rpStyles.page}>
        {error ? (
          <EmptyState
            title={t("replay.error_title")}
            hint={error}
            action={
              <button
                className="ts-btn ts-btn--primary"
                type="button"
                onClick={onBackHome}
              >
                {t("replay.error_back_plaza")}
              </button>
            }
          />
        ) : (
          <LoadingShim label={t("replay.loading_label")} />
        )}
      </div>
    )
  }

  // Build a synthetic template-like object so we can reuse the cover helper.
  const templateLike = {
    template_id: sessionId, // stable hash on session_id for the cover pick
    seed: replay.template_seed,
    title: replay.template_title,
    cast: replay.cast,
  }
  // For completed replays, use the ending-specific illustration as the
  // hero — that's the visual identity of *this particular* playthrough.
  // Incomplete replays fall back to the shell cover.
  const cover = replay.completed && replay.ending
    ? getEndingIllustration(replay.ending.label)
    : getCoverForTemplate(templateLike)
  const advisorAvatar = getAdvisorAvatar(sessionId, replay.advisor_persona)
  const endingSubtitleText = replay.ending
    ? lang === "en" ? `"${replay.ending.subtitle}"` : `「${replay.ending.subtitle}」`
    : ""

  return (
    <div style={rpStyles.page}>
      {/* Hero: shell cover banner with title + meta */}
      <div
        style={{
          ...rpStyles.hero,
          backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.18) 0%, rgba(20,16,12,0.65) 60%, var(--bg) 100%), url(${cover})`,
        }}
      >
        <div style={rpStyles.heroInner}>
          <button style={rpStyles.crumb} onClick={onBackHome} type="button">
            {t("replay.crumb_back_home")}
          </button>
          <div style={rpStyles.replayBadge}>{t("replay.badge")}</div>
          <h1 style={rpStyles.title}>{replay.template_title}</h1>
          <p style={rpStyles.heroSeed}>"{replay.template_seed}"</p>
          {replay.completed && replay.ending ? (
            <div style={rpStyles.heroEnding}>
              <div style={rpStyles.heroEndingLabel}>
                {ENDING_LABEL_DISPLAY[lang][replay.ending.label] ?? replay.ending.label}
              </div>
              <div style={rpStyles.heroEndingSubtitle}>{endingSubtitleText}</div>
            </div>
          ) : (
            <div style={rpStyles.heroIncomplete}>
              {t("replay.in_progress_meta", {
                current: replay.turn_count,
                total: replay.turn_budget,
              })}
            </div>
          )}
        </div>
      </div>

      <main style={rpStyles.main}>
        {/* Cast row */}
        <section style={rpStyles.section}>
          <div style={rpStyles.sectionLabel}>{t("replay.cast_label")}</div>
          <div style={rpStyles.castRow}>
            {replay.cast.map((c) => (
              <div key={c.character_id} style={rpStyles.castChip}>
                <img
                  src={getAvatarForCastMember(sessionId, c)}
                  alt={c.display_name}
                  style={rpStyles.castAvatar}
                  loading="lazy"
                />
                <div style={{ minWidth: 0, maxWidth: 140 }}>
                  <Truncated style={rpStyles.castName}>{c.display_name}</Truncated>
                  <Truncated style={rpStyles.castRole}>{c.role}</Truncated>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* Preview / Full view-mode toggle. Hidden when there are no
            highlights to preview (incomplete run or LLM failure) —
            in that case "full" is the only sensible mode anyway. */}
        {replay.ending?.highlights && replay.ending.highlights.length > 0 ? (
          <div style={rpStyles.viewModeRow}>
            <button
              type="button"
              style={{
                ...rpStyles.viewModeBtn,
                ...(viewMode === "preview" ? rpStyles.viewModeBtnActive : null),
              }}
              onClick={() => setViewMode("preview")}
              aria-pressed={viewMode === "preview"}
            >
              {t("replay.view_preview")}
            </button>
            <button
              type="button"
              style={{
                ...rpStyles.viewModeBtn,
                ...(viewMode === "full" ? rpStyles.viewModeBtnActive : null),
              }}
              onClick={() => setViewMode("full")}
              aria-pressed={viewMode === "full"}
            >
              {t("replay.view_full")}
            </button>
          </div>
        ) : null}

        {/* PREVIEW MODE — highlight carousel with CTA. Skipped when
            no ending/highlights or when user picked full mode. */}
        {viewMode === "preview" &&
        replay.ending?.highlights &&
        replay.ending.highlights.length > 0 ? (
          <>
            <section style={rpStyles.section}>
              <div style={rpStyles.sectionLabel}>
                {t("replay.preview_label", { count: replay.ending.highlights.length })}
              </div>
              <p style={rpStyles.previewHint}>{t("replay.preview_hint")}</p>
              <div style={rpStyles.highlightCarousel}>
                {replay.ending.highlights.map((h, i) => (
                  <article key={`${h.beat_ord}-${i}`} style={rpStyles.previewCard}>
                    <div style={rpStyles.previewCardIndex}>
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <h3 style={rpStyles.previewCardHeadline}>{h.headline}</h3>
                    <p style={rpStyles.previewCardBody}>{h.body_excerpt}</p>
                    <p style={rpStyles.previewCardWhy}>{h.why_pivotal}</p>
                  </article>
                ))}
              </div>
            </section>

            {/* Ending splash sits below the carousel as the punctuation. */}
            {replay.ending ? (
              <section style={rpStyles.section}>
                <div style={rpStyles.endingDivider}>
                  <span style={rpStyles.endingDividerLabel}>{t("replay.ending_divider")}</span>
                </div>
                <div style={rpStyles.endingCard}>
                  <div style={rpStyles.endingLabelChip}>
                    {ENDING_LABEL_DISPLAY[lang][replay.ending.label] ?? replay.ending.label}
                  </div>
                  <h2 style={rpStyles.endingSubtitle}>{endingSubtitleText}</h2>
                </div>
              </section>
            ) : null}

            {/* CTA — switch to full read or play yourself. */}
            <div style={rpStyles.cta}>
              <p style={rpStyles.ctaHint}>{t("replay.preview_cta_hint")}</p>
              <div style={rpStyles.ctaRow}>
                <button
                  className="ts-btn ts-btn--secondary ts-btn--lg"
                  onClick={() => setViewMode("full")}
                  type="button"
                >
                  {t("replay.preview_cta_full")}
                </button>
                <button
                  className="ts-btn ts-btn--primary ts-btn--lg"
                  onClick={() => replay.template_forkable ? onOpenTemplate(replay.template_id) : onBackHome()}
                  type="button"
                >
                  {replay.template_forkable ? t("replay.cta_play_template") : t("replay.cta_back_plaza")}
                </button>
              </div>
            </div>
          </>
        ) : null}

        {/* FULL MODE — advisor toggle + story column + ending. */}
        {viewMode === "full" || !replay.ending?.highlights || replay.ending.highlights.length === 0 ? (
        <>
        {/* Advisor toggle */}
        {replay.advisor_messages.length > 0 ? (
          <section style={rpStyles.advisorToggleSection}>
            <button
              style={rpStyles.advisorToggleBtn}
              onClick={() => setShowAdvisor((v) => !v)}
              type="button"
            >
              <img
                src={advisorAvatar}
                alt=""
                style={rpStyles.advisorToggleAvatar}
                loading="lazy"
              />
              <div style={{ flex: 1 }}>
                <div style={rpStyles.advisorToggleTitle}>
                  {showAdvisor
                    ? t("replay.advisor_toggle_prefix_showing")
                    : t("replay.advisor_toggle_prefix_view")}
                  <span style={{ color: "var(--accent)" }}>
                    {t("replay.advisor_toggle_advisor_word")}
                  </span>
                  {t("replay.advisor_toggle_suffix", {
                    count: replay.advisor_messages.length / 2,
                  })}
                </div>
                <div style={rpStyles.advisorTogglePersona}>{replay.advisor_persona}</div>
              </div>
              <span style={rpStyles.advisorToggleArrow}>{showAdvisor ? "▾" : "▸"}</span>
            </button>
          </section>
        ) : null}

        {/* Story column with optional inline advisor messages */}
        <section style={rpStyles.storyColumn}>
          {/* Skim toggle — friends landing on a shared replay don't
              necessarily want to read all 12 narrator beats top to
              bottom. Skim mode collapses each beat to a 3-line
              preview; click any beat to expand. Default is "skim"
              because that matches the entry behavior of someone
              who just opened a link. */}
          <div style={rpStyles.skimToggleRow}>
            <button
              type="button"
              style={{
                ...rpStyles.skimToggle,
                ...(skimMode ? null : rpStyles.skimToggleActive),
              }}
              onClick={() => setSkimMode(false)}
              aria-pressed={!skimMode}
            >
              {t("replay.skim_full")}
            </button>
            <button
              type="button"
              style={{
                ...rpStyles.skimToggle,
                ...(skimMode ? rpStyles.skimToggleActive : null),
              }}
              onClick={() => setSkimMode(true)}
              aria-pressed={skimMode}
            >
              {t("replay.skim_compact")}
            </button>
          </div>
          {renderInterleavedStream(replay, showAdvisor, advisorAvatar, t, skimMode, expandedOrds, toggleBeat)}

          {/* Ending block at the very bottom */}
          {replay.ending ? (
            <div style={rpStyles.endingDivider}>
              <span style={rpStyles.endingDividerLabel}>{t("replay.ending_divider")}</span>
            </div>
          ) : null}
          {replay.ending ? (
            <div style={rpStyles.endingCard}>
              <div style={rpStyles.endingLabelChip}>
                {ENDING_LABEL_DISPLAY[lang][replay.ending.label] ?? replay.ending.label}
              </div>
              <h2 style={rpStyles.endingSubtitle}>{endingSubtitleText}</h2>
              <div style={rpStyles.endingPassage}>{replay.ending.passage}</div>
            </div>
          ) : null}
        </section>

        <div style={rpStyles.cta}>
          <p style={rpStyles.ctaHint}>{t("replay.cta_hint")}</p>
          {replay.template_forkable ? (
            <button
              className="ts-btn ts-btn--primary ts-btn--lg"
              onClick={() => onOpenTemplate(replay.template_id)}
              type="button"
            >
              {t("replay.cta_play_template")}
            </button>
          ) : null}
          <button
            className="ts-btn ts-btn--ghost ts-btn--lg"
            onClick={onBackHome}
            type="button"
          >
            {t("replay.cta_back_plaza")}
          </button>
        </div>
        </>
        ) : null}
      </main>
    </div>
  )
}

/**
 * The advisor messages are timestamp-less in the replay payload — we don't
 * know exactly which story turn they correspond to. For v1 we render the
 * full advisor track separately from the main story, but show it via a
 * collapsible bar so it doesn't dominate. A future enhancement would be
 * to interleave by ord-correlation; for now keep it readable.
 */
function renderInterleavedStream(
  replay: NarrativePublicReplayResponse,
  showAdvisor: boolean,
  advisorAvatar: string,
  t: ReturnType<typeof useT>,
  skimMode: boolean,
  expandedOrds: Set<number>,
  toggleBeat: (ord: number) => void,
) {
  return (
    <>
      {replay.messages.map((m) =>
        m.role === "narrator" ? (
          (() => {
            const isExpanded = !skimMode || expandedOrds.has(m.ord)
            return (
              <article
                key={`n-${m.ord}`}
                style={{
                  ...rpStyles.narratorBeat,
                  ...(skimMode ? { cursor: "pointer" } : null),
                }}
                onClick={() => skimMode && toggleBeat(m.ord)}
                role={skimMode ? "button" : undefined}
                tabIndex={skimMode ? 0 : undefined}
                aria-expanded={skimMode ? isExpanded : undefined}
                onKeyDown={(e) => {
                  if (skimMode && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault()
                    toggleBeat(m.ord)
                  }
                }}
              >
                <div
                  style={{
                    ...rpStyles.narratorText,
                    ...(isExpanded ? null : rpStyles.narratorTextSkim),
                  }}
                >
                  {m.content}
                </div>
                {!isExpanded ? (
                  <div style={rpStyles.skimMore}>{t("replay.skim_expand")}</div>
                ) : null}
                {m.chosen_option_index != null && m.options.length > 0 ? (
                  <div style={rpStyles.chosenChip}>
                    <span style={rpStyles.chosenLabel}>{t("replay.chosen_label")}</span>
                    <span style={rpStyles.chosenText}>
                      {m.options[m.chosen_option_index]?.label ?? "?"}
                    </span>
                  </div>
                ) : null}
              </article>
            )
          })()
        ) : (
          <article key={`p-${m.ord}`} style={rpStyles.playerBeat}>
            <div style={rpStyles.playerLabel}>{t("replay.player_label")}</div>
            <div style={rpStyles.playerText}>{m.content}</div>
          </article>
        ),
      )}

      {/* Advisor block (collapsed/expanded). Rendered below the main story
          stream as a separate vertical track, since we can't reliably
          interleave by turn without additional ord metadata. */}
      {showAdvisor && replay.advisor_messages.length > 0 ? (
        <section style={rpStyles.advisorTrack}>
          <div style={rpStyles.advisorTrackHeader}>
            <img
              src={advisorAvatar}
              alt=""
              style={rpStyles.advisorTrackAvatar}
              loading="lazy"
            />
            <div style={rpStyles.advisorTrackTitle}>{t("replay.advisor_track_title")}</div>
          </div>
          {replay.advisor_messages.map((m) => (
            <div
              key={`a-${m.role}-${m.ord}`}
              style={
                m.role === "player" ? rpStyles.advisorRowPlayer : rpStyles.advisorRowAdvisor
              }
            >
              <div
                style={
                  m.role === "player"
                    ? rpStyles.advisorBubblePlayer
                    : rpStyles.advisorBubbleAdvisor
                }
              >
                {m.content}
              </div>
            </div>
          ))}
        </section>
      ) : null}
    </>
  )
}

const rpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  center: {
    padding: 80,
    textAlign: "center",
    color: "var(--text-muted)",
    fontSize: 14,
  },

  hero: {
    width: "100%",
    minHeight: 320,
    backgroundSize: "cover",
    backgroundPosition: "center",
    color: "white",
    display: "flex",
    alignItems: "flex-end",
  },
  heroInner: {
    width: "100%",
    maxWidth: 720,
    margin: "0 auto",
    padding: "32px 32px 60px",
  },
  crumb: {
    background: "rgba(255,255,255,0.12)",
    border: "1px solid rgba(255,255,255,0.18)",
    color: "white",
    fontSize: 12.5,
    cursor: "pointer",
    padding: "5px 12px",
    borderRadius: 999,
    marginBottom: 18,
    backdropFilter: "blur(6px)",
  },
  replayBadge: {
    display: "inline-block",
    padding: "4px 12px",
    background: "var(--accent)",
    color: "white",
    borderRadius: 4,
    fontSize: 12,
    letterSpacing: "0.16em",
    fontWeight: 600,
    marginBottom: 14,
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 38,
    lineHeight: 1.18,
    fontWeight: 400,
    margin: "0 0 12px",
    color: "white",
    textShadow: "0 2px 18px rgba(0,0,0,0.5)",
  },
  heroSeed: {
    fontSize: 14,
    color: "rgba(255,255,255,0.78)",
    fontStyle: "italic",
    margin: "0 0 22px",
    lineHeight: 1.6,
  },
  heroEnding: {
    display: "inline-flex",
    flexDirection: "column",
    gap: 6,
    padding: "14px 20px",
    background: "rgba(0,0,0,0.4)",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: "var(--radius-md)",
    backdropFilter: "blur(8px)",
  },
  heroEndingLabel: {
    display: "inline-block",
    padding: "3px 10px",
    background: "var(--accent)",
    color: "white",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    width: "fit-content",
  },
  heroEndingSubtitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.4,
    color: "white",
  },
  heroIncomplete: {
    display: "inline-block",
    padding: "8px 14px",
    background: "rgba(0,0,0,0.4)",
    border: "1px solid rgba(255,255,255,0.18)",
    borderRadius: 999,
    fontSize: 13,
    color: "rgba(255,255,255,0.85)",
  },

  main: { maxWidth: 720, margin: "-40px auto 0", padding: "0 32px 80px", position: "relative", zIndex: 2 },

  section: { marginBottom: 28 },
  sectionLabel: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    marginBottom: 10,
  },
  castRow: { display: "flex", gap: 8, flexWrap: "wrap" },
  castChip: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "6px 12px 6px 6px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
  },
  castAvatar: { width: 30, height: 30, borderRadius: "50%", objectFit: "cover" },
  castName: { fontSize: 13, fontWeight: 500, color: "var(--text)" },
  castRole: { fontSize: 11, color: "var(--text-faint)", marginTop: 2 },

  advisorToggleSection: { marginBottom: 24 },
  advisorToggleBtn: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "12px 16px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
    cursor: "pointer",
    textAlign: "left",
  },
  advisorToggleAvatar: { width: 36, height: 36, borderRadius: "50%", objectFit: "cover" },
  advisorToggleTitle: { fontSize: 14, color: "var(--text)" },
  advisorTogglePersona: { fontSize: 11, color: "var(--text-faint)", marginTop: 3 },
  advisorToggleArrow: { color: "var(--text-faint)", fontSize: 12 },

  storyColumn: {},
  // View-mode toggle (preview vs full) — same pill-segmented look
  // as the skim toggle below, but at the page level.
  viewModeRow: {
    display: "inline-flex",
    gap: 0,
    margin: "0 0 24px",
    padding: 2,
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
  },
  viewModeBtn: {
    background: "transparent",
    border: "none",
    color: "var(--text-muted)",
    fontSize: 12.5,
    padding: "6px 16px",
    borderRadius: 999,
    letterSpacing: "0.04em",
    cursor: "pointer",
    transition: "background 160ms, color 160ms",
  },
  viewModeBtnActive: {
    background: "var(--accent-soft)",
    color: "var(--accent)",
    fontWeight: 500,
  },
  // Highlight carousel — horizontal scroll with snap-to-card on
  // mobile, stack-of-3 on desktop. Entry experience for shared links.
  highlightCarousel: {
    display: "grid",
    gridAutoFlow: "row",
    gap: 12,
    marginTop: 12,
  },
  previewCard: {
    padding: "18px 22px",
    background: "linear-gradient(180deg, rgba(245,200,120,0.08), rgba(245,200,120,0.02))",
    border: "1px solid rgba(245,200,120,0.28)",
    borderRadius: "var(--radius-md)",
    display: "flex",
    flexDirection: "column" as const,
    gap: 10,
  },
  previewCardIndex: {
    fontFamily: "var(--font-narrative)",
    fontSize: 11.5,
    fontWeight: 700,
    letterSpacing: "0.16em",
    color: "rgba(245,200,120,0.78)",
  },
  previewCardHeadline: {
    fontFamily: "var(--font-narrative)",
    fontSize: 19,
    fontWeight: 500,
    color: "rgba(255,235,210,0.96)",
    lineHeight: 1.3,
    margin: 0,
  },
  previewCardBody: {
    fontFamily: "var(--font-narrative)",
    fontSize: 14.5,
    lineHeight: 1.7,
    color: "var(--text)",
    margin: 0,
    fontStyle: "italic" as const,
  },
  previewCardWhy: {
    fontSize: 12.5,
    lineHeight: 1.55,
    color: "var(--text-muted)",
    margin: 0,
  },
  previewHint: {
    fontSize: 13,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    margin: "8px 0 0",
  },
  ctaRow: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap" as const,
    alignItems: "center",
  },
  // Skim toggle row pinned at the top of the story column.
  skimToggleRow: {
    display: "inline-flex",
    gap: 0,
    marginBottom: 24,
    padding: 2,
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
  },
  skimToggle: {
    background: "transparent",
    border: "none",
    color: "var(--text-muted)",
    fontSize: 12,
    padding: "5px 14px",
    borderRadius: 999,
    letterSpacing: "0.04em",
    cursor: "pointer",
    transition: "background 160ms, color 160ms",
  },
  skimToggleActive: {
    background: "var(--accent-soft)",
    color: "var(--accent)",
  },
  narratorBeat: { marginBottom: 28 },
  narratorText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
  },
  // Skim mode: clamp narrator content to 3 lines with a soft fade
  // at the bottom so it reads as "more below" rather than a hard cut.
  narratorTextSkim: {
    display: "-webkit-box",
    WebkitLineClamp: 3,
    WebkitBoxOrient: "vertical" as const,
    overflow: "hidden",
    maskImage: "linear-gradient(180deg, var(--text) 60%, transparent)",
    WebkitMaskImage: "linear-gradient(180deg, var(--text) 60%, transparent)",
  },
  skimMore: {
    fontSize: 11.5,
    color: "var(--accent)",
    marginTop: 8,
    letterSpacing: "0.04em",
    cursor: "pointer",
  },
  chosenChip: {
    marginTop: 12,
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

  playerBeat: { marginBottom: 24, paddingLeft: 16, borderLeft: "2px solid var(--accent)" },
  playerLabel: {
    fontSize: 11,
    color: "var(--accent)",
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  playerText: {
    fontSize: 14,
    lineHeight: 1.6,
    color: "var(--text-muted)",
    fontStyle: "italic",
  },

  advisorTrack: {
    marginTop: 36,
    padding: "20px 22px",
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--line)",
  },
  advisorTrackHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 16,
    paddingBottom: 14,
    borderBottom: "1px dashed var(--line)",
  },
  advisorTrackAvatar: { width: 32, height: 32, borderRadius: "50%", objectFit: "cover" },
  advisorTrackTitle: { fontSize: 13, color: "var(--text)", letterSpacing: "0.04em" },
  advisorRowPlayer: { display: "flex", justifyContent: "flex-end", marginBottom: 10 },
  advisorRowAdvisor: { display: "flex", justifyContent: "flex-start", marginBottom: 10 },
  advisorBubblePlayer: {
    background: "var(--accent)",
    color: "white",
    padding: "8px 12px",
    borderRadius: "14px 14px 4px 14px",
    fontSize: 13,
    lineHeight: 1.55,
    maxWidth: "82%",
  },
  advisorBubbleAdvisor: {
    background: "var(--bg)",
    color: "var(--text)",
    padding: "8px 12px",
    borderRadius: "14px 14px 14px 4px",
    fontSize: 13,
    lineHeight: 1.6,
    maxWidth: "82%",
    border: "1px solid var(--line)",
  },

  endingDivider: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    margin: "40px 0 28px",
  },
  endingDividerLabel: {
    background: "var(--bg)",
    padding: "0 16px",
    fontSize: 12,
    color: "var(--text-faint)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
  },
  endingCard: {
    padding: "32px 28px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-lg)",
    boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
  },
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
    fontSize: 24,
    lineHeight: 1.35,
    fontWeight: 400,
    margin: "0 0 22px",
    color: "var(--text)",
  },
  endingPassage: {
    fontFamily: "var(--font-narrative)",
    fontSize: 15.5,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
  },

  cta: {
    marginTop: 56,
    padding: "32px 0 0",
    borderTop: "1px dashed var(--line)",
    textAlign: "center",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 14,
  },
  ctaHint: { fontSize: 13, color: "var(--text-muted)", margin: 0, lineHeight: 1.5 },
}
