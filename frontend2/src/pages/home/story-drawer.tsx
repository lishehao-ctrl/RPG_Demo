import { type CSSProperties, useEffect, useState } from "react"
import type { UiStory } from "./adapt"

export type StoryDrawerMode = "default" | "fresh" | "mine"

export function StoryDrawer({
  story,
  open,
  onClose,
  onPlay,
  onOpenFullPage,
  starting = false,
  mode = "default",
}: {
  story: UiStory | null
  open: boolean
  onClose: () => void
  onPlay: () => void
  onOpenFullPage?: () => void
  starting?: boolean
  mode?: StoryDrawerMode
}) {
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

  if (!mounted || !story) return null

  const isMine = mode === "mine" || story.isOwnWorld === true
  const isFresh = !isMine && story.played_count === 0

  return (
    <div style={{ ...sdStyles.host, pointerEvents: visible ? "auto" : "none" }}>
      <div style={{ ...sdStyles.scrim, opacity: visible ? 1 : 0 }} onClick={onClose} />
      <aside
        style={{
          ...sdStyles.drawer,
          transform: visible ? "translateX(0)" : "translateX(24px)",
          opacity: visible ? 1 : 0,
        }}
      >
        <div style={sdStyles.cover}>
          <div style={{ ...sdStyles.coverImg, backgroundImage: `url(${story.cover_url})` }} />
          <div style={sdStyles.coverDarken} />
          <div style={sdStyles.coverGrad} />
          <button style={sdStyles.close} onClick={onClose} aria-label="关闭">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M6 6l12 12M18 6l-12 12" strokeLinecap="round" />
            </svg>
          </button>
          <div style={sdStyles.coverTag}>{story.theme}</div>
          <div style={sdStyles.coverInner}>
            <div style={sdStyles.coverTags}>
              <span style={sdStyles.coverPill}>{story.npc_count} 个角色</span>
              <span style={sdStyles.coverPillDot}>·</span>
              <span style={sdStyles.coverPill}>{story.beat_count} 幕</span>
            </div>
            <h2 style={sdStyles.title}>{story.title}</h2>
          </div>
        </div>

        <div style={sdStyles.body}>
          <div style={sdStyles.author}>
            <span style={sdStyles.authorHandle}>@{story.authorUsername}</span>
            <span style={sdStyles.authorDot}>·</span>
            <span>{story.createdAt}</span>
          </div>

          {isMine && <div style={sdStyles.mineNote}>这是你创作的 world。</div>}

          {isFresh ? (
            <div style={sdStyles.proofMuted}>还没有人玩过 — 你可以是第一个。</div>
          ) : (
            <div style={sdStyles.proof}>
              <span style={sdStyles.proofNum}>{story.played_count}</span>
              <span style={sdStyles.proofText}> 人玩过</span>
              <span style={sdStyles.proofDot}>·</span>
              <span style={sdStyles.proofNum}>{story.unique_ending_count}</span>
              <span style={sdStyles.proofText}> 种结局</span>
            </div>
          )}

          <div style={sdStyles.label}>故事开头</div>
          <p style={sdStyles.premise}>{story.premise}</p>
        </div>

        <div style={sdStyles.actions}>
          <button
            className="ts-btn ts-btn--primary ts-btn--lg"
            style={{ ...sdStyles.actionBtn, opacity: starting ? 0.6 : 1, pointerEvents: starting ? "none" : "auto" }}
            onClick={onPlay}
          >
            {starting ? "进入中…" : "开玩"}
          </button>
          <button
            className="ts-btn ts-btn--ghost ts-btn--lg"
            style={sdStyles.actionBtn}
            onClick={onOpenFullPage || onClose}
          >
            {isMine ? "管理这个 world →" : "打开完整页 →"}
          </button>
        </div>
      </aside>
    </div>
  )
}

const sdStyles: Record<string, CSSProperties> = {
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
    width: 480,
    background: "var(--bg-elev)",
    borderLeft: "1px solid var(--line)",
    boxShadow: "var(--shadow-drawer)",
    transition: "transform 320ms cubic-bezier(0.32, 0.72, 0.24, 1), opacity 280ms ease",
    display: "flex",
    flexDirection: "column",
  },

  cover: {
    position: "relative",
    width: "100%",
    aspectRatio: "4/5",
    flexShrink: 0,
    overflow: "hidden",
    background: "#11121a",
  },
  coverImg: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.82) saturate(0.95)",
  },
  coverDarken: {
    position: "absolute",
    inset: 0,
    background: "rgba(12,12,16,0.22)",
  },
  coverGrad: {
    position: "absolute",
    inset: 0,
    background: "linear-gradient(to bottom, rgba(12,12,16,0) 50%, rgba(12,12,16,0.6) 75%, rgba(21,22,28,0.98) 100%)",
  },
  coverTag: {
    position: "absolute",
    left: 18,
    top: 18,
    padding: "5px 10px",
    background: "rgba(12,12,16,0.78)",
    border: "1px solid rgba(212,168,83,0.5)",
    color: "var(--accent)",
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "0.2em",
    borderRadius: 999,
    textTransform: "uppercase",
  },
  coverInner: {
    position: "absolute",
    left: 28,
    right: 28,
    bottom: 24,
  },
  coverTags: {
    display: "flex",
    alignItems: "center",
    fontSize: 12,
    color: "var(--text-muted)",
    marginBottom: 14,
    letterSpacing: "0.04em",
  },
  coverPill: {},
  coverPillDot: { margin: "0 8px", color: "var(--text-faint)" },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 32,
    fontWeight: 500,
    margin: 0,
    letterSpacing: "0.005em",
    lineHeight: 1.15,
    color: "var(--text)",
  },
  close: {
    position: "absolute",
    top: 16,
    right: 16,
    width: 36,
    height: 36,
    borderRadius: 999,
    background: "rgba(12,12,16,0.6)",
    backdropFilter: "blur(8px)",
    color: "var(--text)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "background 160ms",
    border: "1px solid rgba(255,255,255,0.08)",
    zIndex: 2,
  },

  body: {
    padding: "26px 32px 24px",
    overflowY: "auto",
    flex: 1,
  },
  author: {
    fontSize: 13,
    color: "var(--text-muted)",
    marginBottom: 14,
  },
  authorHandle: { color: "var(--accent)", fontWeight: 500 },
  authorDot: { color: "var(--text-faint)", margin: "0 8px" },
  mineNote: {
    fontSize: 12,
    color: "var(--accent)",
    padding: "8px 12px",
    background: "rgba(212,168,83,0.08)",
    border: "1px solid rgba(212,168,83,0.22)",
    borderRadius: 8,
    marginBottom: 18,
    fontStyle: "italic",
  },
  proof: {
    fontSize: 14,
    marginBottom: 28,
    fontVariantNumeric: "tabular-nums",
    color: "var(--text-muted)",
  },
  proofNum: { color: "var(--accent)", fontWeight: 600, fontSize: 16 },
  proofText: {},
  proofDot: { margin: "0 10px", color: "var(--text-faint)" },
  proofMuted: {
    fontSize: 13,
    color: "var(--text-faint)",
    marginBottom: 28,
    fontStyle: "italic",
  },

  label: {
    fontSize: 11,
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    color: "var(--accent)",
    marginBottom: 12,
    fontWeight: 600,
  },
  premise: {
    fontFamily: "var(--font-narrative)",
    fontSize: 14.5,
    lineHeight: 1.7,
    color: "var(--text)",
    margin: 0,
  },

  actions: {
    flexShrink: 0,
    padding: "16px 28px 22px",
    background: "var(--bg-elev)",
    borderTop: "1px solid var(--line)",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  actionBtn: {
    width: "100%",
    justifyContent: "center",
  },
}
