import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react"
import type {
  PlayControlAction,
  PlayLatentRadarItem,
  PlayRelationshipTargetState,
  PlaySessionSnapshot,
  PlayStateBar,
  PlaySuggestedAction,
} from "../../api/contracts"
import { type TranscriptEntry, usePlaySession } from "./use-play-session"

type DrawerTab = "characters" | "state" | "echoes" | "transcript"

type ActionDescriptor = {
  kind: "story" | "press" | "redirect" | "detonate" | "none"
  title: string
  prompt: string
}

type PendingPlayer =
  | { kind: "next-hand"; title: string; text: string }
  | { kind: "free"; text: string }

export function PlayPage({
  sessionId,
  onBackHome,
}: {
  sessionId: string
  onBackHome: () => void
}) {
  const session = usePlaySession(sessionId)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [pendingPlayer, setPendingPlayer] = useState<PendingPlayer | null>(null)
  const [streamed, setStreamed] = useState("")
  const [freeOpen, setFreeOpen] = useState(false)
  const [freeText, setFreeText] = useState("")
  const lastNarrationRef = useRef<string | null>(null)

  // Typewriter effect — restart whenever narration changes.
  useEffect(() => {
    if (!session.snapshot) return
    const fullText = session.snapshot.narration ?? ""
    if (fullText === lastNarrationRef.current) return
    lastNarrationRef.current = fullText
    setStreamed("")
    let i = 0
    const id = window.setInterval(() => {
      i += 1
      setStreamed(fullText.slice(0, i))
      if (i >= fullText.length) window.clearInterval(id)
    }, 22)
    return () => window.clearInterval(id)
  }, [session.snapshot])

  // Clear pending player bubble after a turn lands.
  useEffect(() => {
    if (!pendingPlayer) return
    const t = window.setTimeout(() => setPendingPlayer(null), 1800)
    return () => window.clearTimeout(t)
  }, [pendingPlayer])

  if (session.loading) {
    return (
      <div style={ppStyles.page}>
        <SimpleHeader onHome={onBackHome} />
        <main style={ppStyles.main}>
          <div style={ppStyles.loading}>正在接入会话…</div>
        </main>
      </div>
    )
  }
  if (!session.snapshot) {
    return (
      <div style={ppStyles.page}>
        <SimpleHeader onHome={onBackHome} />
        <main style={ppStyles.main}>
          <div style={ppStyles.loading}>{session.error ?? "这场会话当前不可访问。"}</div>
          <div style={{ marginTop: 16 }}>
            <button className="ts-btn ts-btn--primary" onClick={onBackHome}>
              返回首页
            </button>
          </div>
        </main>
      </div>
    )
  }

  const snapshot = session.snapshot
  const fullText = snapshot.narration ?? ""

  const storyActionsRaw = snapshot.story_actions?.length ? snapshot.story_actions : snapshot.suggested_actions
  const storyActions: ActionDescriptor[] = (storyActionsRaw ?? []).map((a) => ({
    kind: "story",
    title: a.label,
    prompt: a.prompt,
  }))
  const controlActions: ActionDescriptor[] = (snapshot.control_actions ?? []).map((a) => ({
    kind: a.action_type,
    title: a.label,
    prompt: a.prompt,
  }))
  const allActions = [...storyActions, ...controlActions]

  const completed = snapshot.status === "completed" || Boolean(snapshot.ending)

  const pickAction = (a: ActionDescriptor, raw: PlaySuggestedAction | PlayControlAction, isControl: boolean) => {
    if (session.submitting) return
    setPendingPlayer({ kind: "next-hand", title: a.title, text: a.prompt })
    if (isControl) {
      void session.submitTurn({ inputText: raw.prompt, controlAction: raw as PlayControlAction })
    } else {
      void session.submitTurn({ inputText: raw.prompt, storyAction: raw as PlaySuggestedAction })
    }
  }

  const sendFree = () => {
    if (!freeText.trim()) return
    if (session.submitting) return
    setPendingPlayer({ kind: "free", text: freeText })
    void session.submitTurn({ inputText: freeText })
    setFreeText("")
    setFreeOpen(false)
  }

  const totalActs = snapshot.progress?.total_beats ?? 0
  const currentAct = (snapshot.progress?.completed_beats ?? snapshot.beat_index) + 1

  return (
    <div style={ppStyles.page}>
      <header style={ppStyles.meta}>
        <div style={ppStyles.metaInner}>
          <div style={ppStyles.metaLeft}>
            <button style={ppStyles.brandLink} onClick={onBackHome}>
              <span
                style={{
                  color: "var(--accent)",
                  fontSize: 18,
                  transform: "translateY(-1px)",
                  display: "inline-block",
                }}
              >
                ·
              </span>
              <span style={{ fontFamily: "var(--font-narrative)", fontSize: 14, color: "var(--text-muted)" }}>
                Tiny Stories
              </span>
            </button>
            <span style={ppStyles.divider}>/</span>
            <span style={ppStyles.storyTitle}>{snapshot.story_title}</span>
            <span style={ppStyles.dot}>·</span>
            <span style={ppStyles.beatTitle}>{snapshot.beat_title}</span>
          </div>
          <div style={ppStyles.metaRight}>
            <span style={ppStyles.progress}>
              {currentAct}/{totalActs} 幕
              <span style={ppStyles.dot}>·</span>第 {snapshot.turn_index} 轮
            </span>
            <button style={ppStyles.metaBtn} onClick={() => setDrawerOpen(true)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="8" r="3.5" />
                <path d="M5 20c0-3.5 3.5-6 7-6s7 2.5 7 6" strokeLinecap="round" />
              </svg>
              人物 · 状态
            </button>
          </div>
        </div>
      </header>

      <main style={ppStyles.main}>
        <section style={ppStyles.narration}>
          {streamed.split("\n\n").map((p, i) => (
            <p key={i} style={ppStyles.para}>
              {p}
              {i === streamed.split("\n\n").length - 1 && streamed.length < fullText.length && (
                <span style={ppStyles.caret}>▍</span>
              )}
            </p>
          ))}
        </section>

        {pendingPlayer && (
          <div style={ppStyles.playerBubble}>
            <div style={ppStyles.playerEyebrow}>你刚刚</div>
            <div style={ppStyles.playerText}>
              {pendingPlayer.kind === "next-hand" ? `「${pendingPlayer.title}」` : `「${pendingPlayer.text}」`}
            </div>
          </div>
        )}

        {completed ? (
          <PlayEndingPanel
            label={snapshot.ending?.label ?? "故事到这里了"}
            summary={snapshot.ending?.summary ?? ""}
            sessionId={sessionId}
            endingArtworkUrl={endingArtworkFor(snapshot)}
            onCreate={() => {
              window.location.hash = "#/create"
            }}
            onHome={onBackHome}
          />
        ) : (
          <>
            <div style={ppStyles.actionsLabel}>下一手</div>
            <div style={ppStyles.actionsGrid}>
              {storyActions.map((a, i) => (
                <ActionCard
                  key={`s-${i}`}
                  action={a}
                  onClick={() => {
                    const raw = (storyActionsRaw ?? [])[i]
                    if (raw) pickAction(a, raw, false)
                  }}
                />
              ))}
              {controlActions.map((a, i) => (
                <ActionCard
                  key={`c-${i}`}
                  action={a}
                  onClick={() => {
                    const raw = (snapshot.control_actions ?? [])[i]
                    if (raw) pickAction(a, raw, true)
                  }}
                />
              ))}
            </div>

            {!freeOpen ? (
              <button style={ppStyles.freeToggle} onClick={() => setFreeOpen(true)}>
                自由输入 ↓
              </button>
            ) : (
              <div style={ppStyles.freeBox}>
                <textarea
                  style={ppStyles.freeText}
                  placeholder="说点什么、做点什么…"
                  value={freeText}
                  onChange={(e) => setFreeText(e.target.value)}
                  autoFocus
                />
                <div style={ppStyles.freeActions}>
                  <button
                    className="ts-btn ts-btn--ghost"
                    onClick={() => {
                      setFreeOpen(false)
                      setFreeText("")
                    }}
                  >
                    收起
                  </button>
                  <button className="ts-btn ts-btn--primary" onClick={sendFree}>
                    发送
                  </button>
                </div>
              </div>
            )}

            {session.error ? <div style={ppStyles.error}>{session.error}</div> : null}
          </>
        )}
      </main>

      <PlayDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        snapshot={snapshot}
        transcript={session.transcript}
        actsTotal={totalActs}
        currentAct={currentAct}
      />
    </div>
  )
}

function endingArtworkFor(snapshot: PlaySessionSnapshot): string {
  // Placeholder fallback — backend hasn't surfaced an explicit ending artwork URL yet.
  // Use the shell-based cover (or burned_alone segment image) so the panel still has art.
  const shell = snapshot.story_shell_id ?? "office_power"
  return `/webtoons/shells/${shell}.jpg`
}

function ActionCard({ action, onClick }: { action: ActionDescriptor; onClick: () => void }) {
  const [hover, setHover] = useState(false)
  const isControl =
    action.kind === "press" || action.kind === "redirect" || action.kind === "detonate"
  return (
    <button
      style={{
        ...ppStyles.actionCard,
        borderStyle: isControl ? "dashed" : "solid",
        borderColor: hover ? "var(--accent)" : "var(--line)",
        transform: hover ? "translateY(-1px)" : "none",
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
    >
      <div style={ppStyles.actionLabel}>{isControl ? action.kind.toUpperCase() : "下一手"}</div>
      <div style={ppStyles.actionTitle}>{action.title}</div>
      <div style={ppStyles.actionPrompt}>{action.prompt}</div>
    </button>
  )
}

// ────────────── Drawer ──────────────

function PlayDrawer({
  open,
  onClose,
  snapshot,
  transcript,
  actsTotal,
  currentAct,
}: {
  open: boolean
  onClose: () => void
  snapshot: PlaySessionSnapshot
  transcript: TranscriptEntry[]
  actsTotal: number
  currentAct: number
}) {
  const [tab, setTab] = useState<DrawerTab>("characters")
  const [mounted, setMounted] = useState(open)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (open) {
      setMounted(true)
      requestAnimationFrame(() => setVisible(true))
    } else {
      setVisible(false)
      const t = window.setTimeout(() => setMounted(false), 280)
      return () => window.clearTimeout(t)
    }
  }, [open])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose()
    }
    if (open) window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!mounted) return null

  const tabs: Array<{ id: DrawerTab; label: string }> = [
    { id: "characters", label: "人物" },
    { id: "state", label: "状态" },
    { id: "echoes", label: "余波" },
    { id: "transcript", label: "转录" },
  ]

  void actsTotal
  return (
    <div style={{ ...pdStyles.host, pointerEvents: visible ? "auto" : "none" }}>
      <div style={{ ...pdStyles.scrim, opacity: visible ? 1 : 0 }} onClick={onClose} />
      <aside
        style={{
          ...pdStyles.drawer,
          transform: visible ? "translateX(0)" : "translateX(24px)",
          opacity: visible ? 1 : 0,
        }}
      >
        <div style={pdStyles.head}>
          <div style={pdStyles.eyebrow}>
            《{snapshot.story_title}》· 第 {currentAct} 幕
          </div>
          <button style={pdStyles.close} onClick={onClose} aria-label="关闭">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M6 6l12 12M18 6l-12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div style={pdStyles.segwrap}>
          <div style={pdStyles.seg}>
            {tabs.map((t) => (
              <button
                key={t.id}
                style={{
                  ...pdStyles.segBtn,
                  ...(tab === t.id ? pdStyles.segBtnActive : {}),
                }}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div style={pdStyles.body}>
          {tab === "characters" && (
            <Characters list={snapshot.relationship_state?.targets ?? []} />
          )}
          {tab === "state" && (
            <StateTab
              bars={snapshot.state_bars}
              consequences={snapshot.feedback?.last_turn_consequences ?? []}
              latent={snapshot.latent_radar}
            />
          )}
          {tab === "echoes" && <EchoesTab consequences={snapshot.feedback?.last_turn_consequences ?? []} />}
          {tab === "transcript" && <Transcript transcript={transcript} />}
        </div>
      </aside>
    </div>
  )
}

function Bar({ value, color = "var(--accent)" }: { value: number; color?: string }) {
  const clamped = Math.max(0, Math.min(1, value))
  return (
    <div style={pdStyles.barTrack}>
      <div style={{ ...pdStyles.barFill, width: `${clamped * 100}%`, background: color }} />
    </div>
  )
}

function Characters({ list }: { list: PlayRelationshipTargetState[] }) {
  if (list.length === 0) {
    return <div style={pdStyles.empty}>还没有人出场</div>
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {list.map((c) => {
        const metrics = [
          { label: "亲密", value: normalize(c.affection, -3, 6) },
          { label: "信任", value: normalize(c.trust, -3, 6) },
          { label: "拉扯", value: normalize(c.tension, 0, 6) },
          { label: "怀疑", value: normalize(c.suspicion, 0, 6) },
        ]
        return (
          <div key={c.character_id} style={pdStyles.charCard}>
            <div style={pdStyles.charHead}>
              <div style={pdStyles.charName}>{c.name}</div>
              {c.is_route_focus && <span className="ts-tag">焦点</span>}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
              {metrics.map((m) => (
                <div key={m.label} style={pdStyles.miniRow}>
                  <span style={pdStyles.miniLabel}>{m.label}</span>
                  <Bar value={m.value} />
                  <span style={pdStyles.miniValue}>{Math.round(m.value * 100)}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StateTab({
  bars,
  consequences,
  latent,
}: {
  bars: PlayStateBar[]
  consequences: string[]
  latent: PlayLatentRadarItem[]
}) {
  return (
    <div>
      <div style={pdStyles.section}>
        {bars.map((b) => {
          const v = normalize(b.current_value, b.min_value, b.max_value)
          return (
            <div key={b.bar_id} style={{ ...pdStyles.miniRow, marginBottom: 10 }}>
              <span style={pdStyles.miniLabel}>{b.label}</span>
              <Bar value={v} />
              <span style={pdStyles.miniValue}>{Math.round(v * 100)}</span>
            </div>
          )
        })}
      </div>
      <div style={pdStyles.sectionLabel}>这一手的后果</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 24 }}>
        {consequences.length === 0 ? (
          <div style={pdStyles.empty}>暂无</div>
        ) : (
          consequences.map((c, i) => (
            <div key={i} style={pdStyles.consequence}>
              {c}
            </div>
          ))
        )}
      </div>
      <div style={pdStyles.sectionLabel}>水面下</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {latent.map((l, i) => (
          <div key={i} style={pdStyles.latent}>
            <div style={pdStyles.latentNote}>{l.note}</div>
            <Bar value={Math.min(1, l.pressure / 100)} color="var(--warn)" />
          </div>
        ))}
      </div>
    </div>
  )
}

function EchoesTab({ consequences }: { consequences: string[] }) {
  if (consequences.length === 0) {
    return <div style={pdStyles.empty}>还没有余波</div>
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {consequences.map((c, i) => (
        <div key={i} style={pdStyles.consequence}>
          {c}
        </div>
      ))}
    </div>
  )
}

function Transcript({ transcript }: { transcript: TranscriptEntry[] }) {
  if (transcript.length === 0) {
    return <div style={pdStyles.empty}>还没有对话记录</div>
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {transcript.map((m) => (
        <div key={m.id} style={m.speaker === "player" ? pdStyles.bubblePlayer : pdStyles.bubbleGM}>
          <div style={pdStyles.bubbleLabel}>{m.speaker === "player" ? "你" : "讲述"}</div>
          <div style={pdStyles.bubbleText}>{m.text}</div>
        </div>
      ))}
    </div>
  )
}

function normalize(value: number, min: number, max: number): number {
  if (max <= min) return 0.5
  return Math.max(0, Math.min(1, (value - min) / (max - min)))
}

// ────────────── Ending Panel ──────────────

function PlayEndingPanel({
  label,
  summary,
  sessionId,
  endingArtworkUrl,
  onCreate,
  onHome,
}: {
  label: string
  summary: string
  sessionId: string
  endingArtworkUrl: string
  onCreate: () => void
  onHome: () => void
}) {
  const [pulse, setPulse] = useState(false)
  const [toast, setToast] = useState(false)
  const shareUrl = useMemo(
    () => `${window.location.origin}${window.location.pathname}#/play/${sessionId}/replay`,
    [sessionId],
  )

  const shareEnding = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
    } catch {
      window.prompt("复制这个链接发给朋友：", shareUrl)
    }
    setPulse(true)
    setToast(true)
    window.setTimeout(() => setPulse(false), 600)
    window.setTimeout(() => setToast(false), 2000)
  }

  return (
    <div style={pepStyles.panel}>
      <div style={pepStyles.artwork}>
        <div style={{ ...pepStyles.artworkImg, backgroundImage: `url(${endingArtworkUrl})` }} />
        <div style={pepStyles.artworkDarken} />
        <div style={pepStyles.artworkGradient} />
        <div style={pepStyles.artworkInner}>
          <span style={pepStyles.artworkEyebrow}>结局</span>
          <h2 style={pepStyles.artworkTitle}>{label}</h2>
        </div>
      </div>

      {summary ? <p style={pepStyles.summary}>{summary}</p> : null}

      <div style={pepStyles.actions}>
        <button className="ts-btn ts-btn--primary ts-btn--lg" onClick={() => void shareEnding()}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            style={{ marginRight: 6 }}
          >
            <path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1" strokeLinecap="round" />
            <path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1" strokeLinecap="round" />
          </svg>
          分享我的结局
        </button>
        <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onCreate}>
          写我自己的 world
        </button>
        <button
          className="ts-btn ts-btn--ghost ts-btn--lg"
          onClick={onHome}
          style={{ color: "var(--text-faint)" }}
        >
          回首页
        </button>
      </div>

      <div
        style={{
          ...pepStyles.shareUrl,
          background: pulse ? "rgba(212,168,83,0.18)" : "transparent",
          color: pulse ? "var(--accent)" : "var(--text-faint)",
        }}
      >
        {shareUrl}
      </div>

      <div
        style={{
          ...pepStyles.toast,
          opacity: toast ? 1 : 0,
          transform: toast ? "translate(-50%, 0)" : "translate(-50%, 8px)",
        }}
      >
        <span style={{ color: "var(--accent)" }}>✓</span> 已复制 replay 链接
      </div>
    </div>
  )
}

function SimpleHeader({ onHome }: { onHome: () => void }) {
  return (
    <header style={ppStyles.simpleHeader}>
      <button style={ppStyles.brandLink} onClick={onHome}>
        <span
          style={{
            color: "var(--accent)",
            fontSize: 22,
            lineHeight: 1,
            transform: "translateY(-2px)",
            display: "inline-block",
          }}
        >
          ·
        </span>
        <span style={{ fontFamily: "var(--font-narrative)", fontSize: 18 }}>Tiny Stories</span>
      </button>
    </header>
  )
}

const ppStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  meta: {
    position: "sticky",
    top: 0,
    zIndex: 4,
    background: "rgba(12,12,16,0.86)",
    backdropFilter: "blur(14px)",
    borderBottom: "1px solid var(--line)",
  },
  metaInner: {
    maxWidth: 1100,
    margin: "0 auto",
    padding: "12px 28px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    fontSize: 13,
  },
  metaLeft: { display: "flex", alignItems: "center", gap: 8 },
  metaRight: { display: "flex", alignItems: "center", gap: 14 },
  brandLink: { display: "inline-flex", alignItems: "center", gap: 6 },
  divider: { color: "var(--text-faint)" },
  storyTitle: { color: "var(--text)", fontFamily: "var(--font-narrative)", fontSize: 14 },
  beatTitle: { color: "var(--text-muted)" },
  dot: { color: "var(--text-faint)", margin: "0 6px" },
  progress: { color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" },
  metaBtn: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    height: 30,
    padding: "0 12px",
    border: "1px solid var(--line)",
    borderRadius: 999,
    color: "var(--text-muted)",
    fontSize: 12,
    transition: "all 160ms",
  },

  simpleHeader: {
    padding: "16px 40px",
    borderBottom: "1px solid var(--line)",
    display: "flex",
    alignItems: "center",
  },

  main: { maxWidth: 820, margin: "0 auto", padding: "48px 32px 100px" },
  loading: { padding: "48px 0", color: "var(--text-muted)" },
  narration: { marginBottom: 36, minHeight: 200 },
  para: {
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    lineHeight: 1.65,
    color: "var(--text)",
    margin: "0 0 18px",
    letterSpacing: "0.005em",
    animation: "tsFadeUp 420ms ease",
  },
  caret: {
    color: "var(--accent)",
    marginLeft: 2,
    animation: "tsBlink 1s steps(2) infinite",
  },

  playerBubble: {
    borderLeft: "2px solid var(--accent)",
    background: "var(--accent-softer)",
    padding: "12px 18px",
    borderRadius: "0 10px 10px 0",
    marginBottom: 28,
    animation: "tsFadeUp 320ms ease",
  },
  playerEyebrow: {
    fontSize: 10,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  playerText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 15,
    color: "var(--text)",
    lineHeight: 1.5,
  },

  actionsLabel: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 14,
  },
  actionsGrid: { display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, marginBottom: 24 },
  actionCard: {
    textAlign: "left",
    padding: "18px 20px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    transition: "all 180ms",
    color: "var(--text)",
  },
  actionLabel: {
    fontSize: 10,
    color: "var(--text-faint)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 6,
  },
  actionTitle: { fontSize: 14, fontWeight: 600, marginBottom: 6, color: "var(--text)" },
  actionPrompt: { fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 },

  freeToggle: {
    width: "100%",
    padding: "14px 20px",
    background: "transparent",
    border: "1px dashed var(--line-strong)",
    borderRadius: "var(--radius-md)",
    color: "var(--text-muted)",
    fontSize: 13,
    transition: "all 160ms",
  },
  freeBox: {
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    padding: 14,
  },
  freeText: {
    width: "100%",
    minHeight: 88,
    padding: "10px 12px",
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    borderRadius: 10,
    fontSize: 14,
    lineHeight: 1.55,
    color: "var(--text)",
    resize: "vertical",
    outline: "none",
    fontFamily: "var(--font-narrative)",
  },
  freeActions: { display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 10 },

  error: {
    marginTop: 16,
    fontSize: 13,
    color: "var(--warn)",
  },
}

const pdStyles: Record<string, CSSProperties> = {
  host: { position: "fixed", inset: 0, zIndex: 50 },
  scrim: {
    position: "absolute",
    inset: 0,
    background: "rgba(0,0,0,0.58)",
    backdropFilter: "blur(2px)",
    transition: "opacity 240ms ease",
  },
  drawer: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    width: 420,
    background: "var(--bg-elev)",
    borderLeft: "1px solid var(--line)",
    boxShadow: "var(--shadow-drawer)",
    display: "flex",
    flexDirection: "column",
    transition: "transform 320ms cubic-bezier(0.32,0.72,0.24,1), opacity 280ms ease",
  },
  head: {
    padding: "16px 22px 12px",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    borderBottom: "1px solid var(--line)",
  },
  eyebrow: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
  },
  close: {
    width: 30,
    height: 30,
    borderRadius: 999,
    color: "var(--text-muted)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },

  segwrap: { padding: "14px 22px 0" },
  seg: { display: "flex", padding: 4, background: "var(--bg-elev-2)", borderRadius: 999 },
  segBtn: {
    flex: 1,
    height: 30,
    padding: "0 8px",
    fontSize: 12,
    color: "var(--text-muted)",
    borderRadius: 999,
    transition: "all 160ms",
  },
  segBtnActive: { background: "var(--bg-elev-3)", color: "var(--text)" },

  body: { flex: 1, overflowY: "auto", padding: "20px 22px 32px" },
  section: { marginBottom: 20 },
  sectionLabel: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.14em",
    textTransform: "uppercase",
    margin: "16px 0 10px",
  },

  charCard: {
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    padding: "14px 16px",
  },
  charHead: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 },
  charName: { fontWeight: 600, fontSize: 14, color: "var(--text)" },

  miniRow: {
    display: "grid",
    gridTemplateColumns: "56px 1fr 32px",
    alignItems: "center",
    gap: 10,
  },
  miniLabel: { fontSize: 11, color: "var(--text-muted)" },
  miniValue: {
    fontSize: 11,
    color: "var(--text-faint)",
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
  },

  barTrack: { height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999, transition: "width 320ms ease" },

  consequence: {
    borderLeft: "2px solid var(--accent)",
    background: "var(--accent-softer)",
    padding: "9px 14px",
    borderRadius: "0 8px 8px 0",
    fontSize: 13,
    color: "var(--text)",
    lineHeight: 1.55,
  },
  latent: {
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    borderRadius: 10,
    padding: "10px 14px",
  },
  latentNote: { fontSize: 12, color: "var(--text-muted)", marginBottom: 8, lineHeight: 1.5 },

  bubblePlayer: {
    background: "var(--accent-softer)",
    borderLeft: "2px solid var(--accent)",
    padding: "10px 14px",
    borderRadius: "0 10px 10px 0",
  },
  bubbleGM: {
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    padding: "10px 14px",
    borderRadius: 10,
  },
  bubbleLabel: {
    fontSize: 10,
    color: "var(--text-faint)",
    letterSpacing: "0.14em",
    textTransform: "uppercase",
    marginBottom: 4,
  },
  bubbleText: {
    fontSize: 13,
    color: "var(--text)",
    lineHeight: 1.55,
    fontFamily: "var(--font-narrative)",
  },

  empty: {
    padding: "24px 0",
    fontSize: 13,
    color: "var(--text-faint)",
    textAlign: "center",
  },
}

const pepStyles: Record<string, CSSProperties> = {
  panel: {
    position: "relative",
    paddingTop: 32,
    marginTop: 16,
    borderTop: "1px solid var(--line)",
  },
  artwork: {
    position: "relative",
    width: "100%",
    height: 280,
    borderRadius: 14,
    overflow: "hidden",
    marginBottom: 28,
    border: "1px solid var(--line)",
    boxShadow: "0 30px 60px rgba(0,0,0,0.45)",
  },
  artworkImg: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.85) saturate(0.92)",
  },
  artworkDarken: {
    position: "absolute",
    inset: 0,
    background: "rgba(12,12,16,0.18)",
  },
  artworkGradient: {
    position: "absolute",
    inset: 0,
    background:
      "linear-gradient(to bottom, rgba(12,12,16,0) 30%, rgba(12,12,16,0.55) 60%, rgba(12,12,16,0.92) 100%)",
  },
  artworkInner: {
    position: "absolute",
    left: 28,
    right: 28,
    bottom: 24,
  },
  artworkEyebrow: {
    display: "inline-block",
    fontSize: 10,
    color: "var(--accent)",
    letterSpacing: "0.22em",
    textTransform: "uppercase",
    marginBottom: 10,
    fontWeight: 600,
  },
  artworkTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 32,
    fontWeight: 400,
    color: "var(--accent)",
    margin: 0,
    letterSpacing: "0.04em",
  },
  summary: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.7,
    color: "var(--text)",
    margin: "0 0 32px",
    maxWidth: 680,
  },
  actions: {
    display: "flex",
    gap: 12,
    flexWrap: "wrap",
    marginBottom: 22,
  },
  shareUrl: {
    fontSize: 11,
    fontFamily: "ui-monospace, SF Mono, Menlo, monospace",
    letterSpacing: "0.02em",
    padding: "6px 10px",
    borderRadius: 6,
    display: "inline-block",
    transition: "background 400ms ease, color 400ms ease",
  },
  toast: {
    position: "fixed",
    left: "50%",
    bottom: 60,
    padding: "10px 18px",
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line-strong)",
    borderRadius: 999,
    fontSize: 13,
    transition: "opacity 220ms ease, transform 220ms ease",
    pointerEvents: "none",
    boxShadow: "0 12px 32px rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    gap: 8,
    zIndex: 10,
  },
}
