import { type CSSProperties, useCallback, useEffect, useRef, useState } from "react"
import type {
  NarrativeAdvisorMessage,
  NarrativeStoryHistoryResponse,
  NarrativeStoryMessage,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import {
  getAdvisorAvatar,
  getAvatarForCastMember,
  getCoverForTemplate,
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
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [freeInput, setFreeInput] = useState("")
  const [showFreeInput, setShowFreeInput] = useState(false)
  const [advisorOpen, setAdvisorOpen] = useState(false)

  // Initial load
  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .getNarrativeStory(sessionId)
      .then((response) => {
        if (cancelled) return
        setStory(response)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "无法加载故事。")
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
    async (action: { chosen_option_index?: number; free_input?: string }) => {
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
            session: { ...prev.session, turn_count: prev.session.turn_count + 1 },
          }
        })
        setFreeInput("")
        setShowFreeInput(false)
      } catch (err) {
        setError(err instanceof Error ? err.message : "续写失败，请稍后再试。")
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
        <div style={ppStyles.centerNote}>
          {error ? `加载失败：${error}` : "故事加载中…"}
        </div>
      </div>
    )
  }

  const cover = getCoverForTemplate(story.template)
  const advisorAvatar = getAdvisorAvatar(
    story.template.template_id,
    story.template.advisor_persona,
  )

  return (
    <div style={ppStyles.page}>
      <Header
        onBackHome={onBackHome}
        title={story.template.title}
        cast={story.template.cast.map((c) => c.display_name)}
        turnCount={story.session.turn_count}
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

          {story.messages.map((m) => (
            <StoryBeat key={`${m.role}-${m.ord}`} message={m} />
          ))}

          {error ? <div style={ppStyles.errorInline}>{error}</div> : null}

          {/* Action area pinned at the bottom of the story column */}
          {isLastNarratorPending && lastNarrator ? (
            <ActionArea
              options={lastNarrator.options}
              showFreeInput={showFreeInput}
              freeInput={freeInput}
              setFreeInput={setFreeInput}
              setShowFreeInput={setShowFreeInput}
              busy={busy}
              onPickOption={(i) => void handleAdvance({ chosen_option_index: i })}
              onSubmitFree={() => {
                if (!freeInput.trim()) return
                void handleAdvance({ free_input: freeInput.trim() })
              }}
            />
          ) : busy ? (
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
      {advisorOpen ? (
        <AdvisorSidechat
          sessionId={sessionId}
          persona={story.template.advisor_persona}
          avatarUrl={advisorAvatar}
          onClose={() => setAdvisorOpen(false)}
        />
      ) : null}
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
  coverUrl,
}: {
  onBackHome: () => void
  title: string
  cast?: string[]
  turnCount?: number
  coverUrl?: string
}) {
  const headerStyle: CSSProperties = coverUrl
    ? {
        ...ppStyles.header,
        ...ppStyles.headerWithCover,
        backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.55) 0%, rgba(20,16,12,0.92) 100%), url(${coverUrl})`,
      }
    : ppStyles.header
  return (
    <header style={headerStyle}>
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
            {typeof turnCount === "number" ? (
              <span style={ppStyles.headerTurns}>· 第 {turnCount + 1} 段</span>
            ) : null}
          </div>
        ) : null}
      </div>
      <span style={{ width: 90 }} />
    </header>
  )
}

// ---------------------------------------------------------------------------
// Single story beat (narrator passage or player move)
// ---------------------------------------------------------------------------

function StoryBeat({ message }: { message: NarrativeStoryMessage }) {
  if (message.role === "narrator") {
    return (
      <article style={ppStyles.narratorBeat}>
        <div style={ppStyles.narratorText}>{message.content}</div>
        {message.chosen_option_index != null && message.options.length > 0 ? (
          <div style={ppStyles.chosenChip}>
            <span style={ppStyles.chosenLabel}>你选了</span>
            <span style={ppStyles.chosenText}>
              {message.options[message.chosen_option_index]?.label ?? "?"}
            </span>
          </div>
        ) : null}
      </article>
    )
  }
  // player move (echoed action)
  return (
    <article style={ppStyles.playerBeat}>
      <div style={ppStyles.playerLabel}>你</div>
      <div style={ppStyles.playerText}>{message.content}</div>
    </article>
  )
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
  busy,
  onPickOption,
  onSubmitFree,
}: {
  options: NarrativeStoryMessage["options"]
  showFreeInput: boolean
  freeInput: string
  setFreeInput: (v: string) => void
  setShowFreeInput: (v: boolean) => void
  busy: boolean
  onPickOption: (idx: number) => void
  onSubmitFree: () => void
}) {
  return (
    <div style={ppStyles.actionArea}>
      <div style={ppStyles.optionsList}>
        {options.length === 0 ? (
          <div style={ppStyles.noOptions}>
            （这一段没给选项，写下你想做的事）
          </div>
        ) : (
          options.map((opt, i) => (
            <button
              key={i}
              style={{
                ...ppStyles.optionBtn,
                opacity: busy ? 0.5 : 1,
                pointerEvents: busy ? "none" : "auto",
              }}
              onClick={() => onPickOption(i)}
              disabled={busy}
              type="button"
            >
              <div style={ppStyles.optionLabel}>{opt.label}</div>
              {opt.hint ? <div style={ppStyles.optionHint}>{opt.hint}</div> : null}
            </button>
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
    </div>
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
    <button style={ppStyles.fab} onClick={onOpen} title={persona} type="button">
      <img src={avatarUrl} alt="" style={ppStyles.fabAvatarImg} loading="lazy" />
      <span style={ppStyles.fabLabel}>聊聊</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Advisor sidechat panel
// ---------------------------------------------------------------------------

function AdvisorSidechat({
  sessionId,
  persona,
  avatarUrl,
  onClose,
}: {
  sessionId: string
  persona: string
  avatarUrl: string
  onClose: () => void
}) {
  const api = useApi()
  const [messages, setMessages] = useState<NarrativeAdvisorMessage[]>([])
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
        setError(err instanceof Error ? err.message : "顾问历史加载失败。")
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

  const handleAsk = async () => {
    const question = draft.trim()
    if (!question || busy) return
    setBusy(true)
    setError(null)
    setDraft("")
    try {
      const res = await api.askNarrativeAdvisor(sessionId, { question })
      setMessages((prev) => [...prev, res.player_message, res.advisor_message])
    } catch (err) {
      setError(err instanceof Error ? err.message : "顾问没回上你这一句，再试一次？")
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div style={ppStyles.advisorBackdrop} onClick={onClose} />
      <aside style={ppStyles.advisorPanel}>
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
            <div style={ppStyles.advisorIntro}>
              问 TA 任何事——你和谁的关系到了哪一步、那句话什么意思、你是不是太冲动了。
              TA 不会替你做决定，但会陪你想清楚。
            </div>
          ) : (
            messages.map((m) => (
              <div
                key={`${m.role}-${m.ord}`}
                style={m.role === "player" ? ppStyles.advisorRowPlayer : ppStyles.advisorRowAdvisor}
              >
                <div
                  style={
                    m.role === "player"
                      ? ppStyles.advisorBubblePlayer
                      : ppStyles.advisorBubbleAdvisor
                  }
                >
                  {m.content}
                </div>
              </div>
            ))
          )}
          {busy ? <div style={ppStyles.advisorTyping}>TA 在打字…</div> : null}
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
                void handleAsk()
              }
            }}
            disabled={busy}
            rows={2}
          />
          <button
            className="ts-btn ts-btn--primary"
            onClick={() => void handleAsk()}
            disabled={busy || !draft.trim()}
            type="button"
          >
            发送
          </button>
        </div>
      </aside>
    </>
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
    padding: "16px 32px",
    borderBottom: "1px solid var(--line)",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    background: "var(--bg)",
    position: "sticky",
    top: 0,
    zIndex: 5,
  },
  headerWithCover: {
    backgroundSize: "cover",
    backgroundPosition: "center 35%",
    borderBottom: "1px solid rgba(255,255,255,0.1)",
    padding: "20px 32px 22px",
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

  narratorBeat: { marginBottom: 32 },
  narratorText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 16.5,
    lineHeight: 1.85,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
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

  actionArea: { marginTop: 28, paddingTop: 24, borderTop: "1px dashed var(--line)" },
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
  advisorRowAdvisor: { display: "flex", justifyContent: "flex-start", marginBottom: 12 },
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
  advisorTyping: { fontSize: 12, color: "var(--text-faint)", fontStyle: "italic", padding: "6px 14px" },
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
}
