import { type CSSProperties, useEffect, useState } from "react"
import type { NarrativePublicReplayResponse } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { friendlyError } from "../../shared/lib/friendly-error"
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
  const [replay, setReplay] = useState<NarrativePublicReplayResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showAdvisor, setShowAdvisor] = useState(true)

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
        setError(friendlyError(err, "回放加载失败。"))
      })
    return () => {
      cancelled = true
    }
  }, [api, sessionId])

  if (!replay) {
    return (
      <div style={rpStyles.page}>
        <div style={rpStyles.center}>
          {error ? `加载失败：${error}` : "回放加载中…"}
        </div>
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

  // We need a notional template_id to navigate back to "play it yourself."
  // Replay doesn't include it directly, so we derive nothing — the main CTA
  // sends the viewer to the public plaza or back home.
  void onOpenTemplate

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
            ← 回到首页
          </button>
          <div style={rpStyles.replayBadge}>回放</div>
          <h1 style={rpStyles.title}>{replay.template_title}</h1>
          <p style={rpStyles.heroSeed}>"{replay.template_seed}"</p>
          {replay.completed && replay.ending ? (
            <div style={rpStyles.heroEnding}>
              <div style={rpStyles.heroEndingLabel}>{replay.ending.label}</div>
              <div style={rpStyles.heroEndingSubtitle}>「{replay.ending.subtitle}」</div>
            </div>
          ) : (
            <div style={rpStyles.heroIncomplete}>
              进行中 · 已玩 {replay.turn_count} / {replay.turn_budget} 段
            </div>
          )}
        </div>
      </div>

      <main style={rpStyles.main}>
        {/* Cast row */}
        <section style={rpStyles.section}>
          <div style={rpStyles.sectionLabel}>出场人物</div>
          <div style={rpStyles.castRow}>
            {replay.cast.map((c) => (
              <div key={c.character_id} style={rpStyles.castChip}>
                <img
                  src={getAvatarForCastMember(sessionId, c)}
                  alt={c.display_name}
                  style={rpStyles.castAvatar}
                  loading="lazy"
                />
                <div>
                  <div style={rpStyles.castName}>{c.display_name}</div>
                  <div style={rpStyles.castRole}>{c.role}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

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
                  {showAdvisor ? "正在显示" : "查看"}与{" "}
                  <span style={{ color: "var(--accent)" }}>顾问</span>{" "}
                  的私下对话（{replay.advisor_messages.length / 2} 次）
                </div>
                <div style={rpStyles.advisorTogglePersona}>{replay.advisor_persona}</div>
              </div>
              <span style={rpStyles.advisorToggleArrow}>{showAdvisor ? "▾" : "▸"}</span>
            </button>
          </section>
        ) : null}

        {/* Story column with optional inline advisor messages */}
        <section style={rpStyles.storyColumn}>
          {renderInterleavedStream(replay, showAdvisor, advisorAvatar)}

          {/* Ending block at the very bottom */}
          {replay.ending ? (
            <div style={rpStyles.endingDivider}>
              <span style={rpStyles.endingDividerLabel}>故事到这里</span>
            </div>
          ) : null}
          {replay.ending ? (
            <div style={rpStyles.endingCard}>
              <div style={rpStyles.endingLabelChip}>{replay.ending.label}</div>
              <h2 style={rpStyles.endingSubtitle}>「{replay.ending.subtitle}」</h2>
              <div style={rpStyles.endingPassage}>{replay.ending.passage}</div>
            </div>
          ) : null}
        </section>

        <div style={rpStyles.cta}>
          <p style={rpStyles.ctaHint}>
            想看自己能玩出什么结局？回到首页找广场上的同一个故事开个新一局。
          </p>
          <button
            className="ts-btn ts-btn--primary ts-btn--lg"
            onClick={onBackHome}
            type="button"
          >
            回到广场
          </button>
        </div>
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
) {
  return (
    <>
      {replay.messages.map((m) =>
        m.role === "narrator" ? (
          <article key={`n-${m.ord}`} style={rpStyles.narratorBeat}>
            <div style={rpStyles.narratorText}>{m.content}</div>
            {m.chosen_option_index != null && m.options.length > 0 ? (
              <div style={rpStyles.chosenChip}>
                <span style={rpStyles.chosenLabel}>TA 选了</span>
                <span style={rpStyles.chosenText}>
                  {m.options[m.chosen_option_index]?.label ?? "?"}
                </span>
              </div>
            ) : null}
          </article>
        ) : (
          <article key={`p-${m.ord}`} style={rpStyles.playerBeat}>
            <div style={rpStyles.playerLabel}>TA</div>
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
            <div style={rpStyles.advisorTrackTitle}>玩家与顾问的私聊</div>
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
  narratorBeat: { marginBottom: 28 },
  narratorText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
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
