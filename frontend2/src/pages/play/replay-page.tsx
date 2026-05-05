import { type CSSProperties, useEffect, useState } from "react"
import type { PlaySessionReplayResponse } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { shellCover } from "../../shared/lib/format"

export function ReplayPage({
  sessionId,
  onBackHome,
  onOpenCreate,
}: {
  sessionId: string
  onBackHome: () => void
  onOpenCreate: () => void
}) {
  const api = useApi()
  const [data, setData] = useState<PlaySessionReplayResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    setLoadError(null)
    const load = async () => {
      try {
        const replay = await api.getPlaySessionReplay(sessionId)
        if (active) setData(replay)
      } catch (err) {
        if (active) setLoadError(err instanceof Error ? err.message : "Replay 不可见")
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [api, sessionId])

  const handlePlayThisWorld = () => {
    if (!data) return
    window.location.hash = `#/world/${data.story_id}`
  }
  const handleViewWorld = () => {
    if (!data) return
    window.location.hash = `#/world/${data.story_id}`
  }

  if (loading) {
    return (
      <div style={rpStyles.page}>
        <Header onBackHome={onBackHome} onOpenCreate={onOpenCreate} />
        <main style={rpStyles.main}>
          <div style={rpStyles.loading}>正在调取这场故事…</div>
        </main>
      </div>
    )
  }

  if (!data) {
    return (
      <div style={rpStyles.page}>
        <Header onBackHome={onBackHome} onOpenCreate={onOpenCreate} />
        <main style={rpStyles.main}>
          <div style={rpStyles.loading}>{loadError ?? "Replay 不可见"}</div>
          <div style={{ marginTop: 16 }}>
            <button className="ts-btn ts-btn--primary" onClick={onBackHome}>
              返回首页
            </button>
          </div>
        </main>
      </div>
    )
  }

  // Player handle isn't on the replay payload; show a generic "玩家".
  const playerHandle = "玩家"
  const endingLabel = data.ending?.label ?? (data.completed ? "故事到这里" : "尚未走到结局")
  const endingSummary = data.ending?.summary ?? data.final_narration ?? ""
  const endingArtwork = shellCover(null) // TODO: backend doesn't expose ending artwork URL on replay; fall back to default shell cover

  return (
    <div style={rpStyles.page}>
      <Header onBackHome={onBackHome} onOpenCreate={onOpenCreate} />

      <main style={rpStyles.main}>
        <section style={rpStyles.hero}>
          <div style={rpStyles.heroLeft}>
            <div style={rpStyles.eyebrow}>
              <span style={{ color: "var(--accent)" }}>@{playerHandle}</span>
              <span> 在《{data.story_title}》里玩出的故事</span>
            </div>
            <h1 style={rpStyles.title}>{endingLabel}</h1>
            <button style={rpStyles.worldLink} onClick={handleViewWorld}>
              查看这个 world 的设定 →
            </button>
          </div>
          <div style={rpStyles.heroRight}>
            <div style={rpStyles.coverWrap}>
              <div style={{ ...rpStyles.coverImg, backgroundImage: `url(${endingArtwork})` }} />
              <div style={rpStyles.coverDarken} />
              <div style={rpStyles.coverRadial} />
              <div style={rpStyles.coverEdges} />
            </div>
          </div>
        </section>

        <section style={rpStyles.transcript}>
          {data.entries.map((m, i) =>
            m.speaker === "player" ? (
              <div key={`p-${i}`} style={rpStyles.bubblePlayer}>
                <div style={rpStyles.playerEyebrow}>@{playerHandle}</div>
                <div style={rpStyles.playerText}>{m.text}</div>
              </div>
            ) : (
              <div key={`g-${i}`} style={rpStyles.bubbleGM}>
                <p style={rpStyles.gmText}>{m.text}</p>
              </div>
            ),
          )}
        </section>

        <section style={rpStyles.endingSection}>
          <div style={rpStyles.endingArtwork}>
            <div style={{ ...rpStyles.endingArtworkImg, backgroundImage: `url(${endingArtwork})` }} />
            <div style={rpStyles.endingArtworkDarken} />
            <div style={rpStyles.endingArtworkGradient} />
            <div style={rpStyles.endingArtworkInner}>
              <span style={rpStyles.endingArtworkEyebrow}>结局</span>
              <h2 style={rpStyles.endingArtworkTitle}>{endingLabel}</h2>
            </div>
          </div>
          {endingSummary ? <p style={rpStyles.endingSummary}>{endingSummary}</p> : null}
        </section>

        <footer style={rpStyles.footer}>
          <span style={{ color: "var(--text-faint)" }}>· Tiny Stories</span>
          <span style={{ color: "var(--text-faint)" }}>同一个 world,每个人都会玩出不一样的故事。</span>
        </footer>
      </main>

      <div style={rpStyles.stickyBar}>
        <div style={rpStyles.stickyInner}>
          <span style={rpStyles.stickyMeta}>喜欢这个 world?</span>
          <button className="ts-btn ts-btn--primary ts-btn--lg" onClick={handlePlayThisWorld}>
            也来玩这个 world →
          </button>
        </div>
      </div>
    </div>
  )
}

function Header({ onBackHome, onOpenCreate }: { onBackHome: () => void; onOpenCreate: () => void }) {
  return (
    <header style={rpStyles.header}>
      <button style={rpStyles.brandLink} onClick={onBackHome}>
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
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
        <button className="ts-btn ts-btn--ghost" onClick={onOpenCreate}>
          写一个 world
        </button>
      </div>
    </header>
  )
}

const rpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)", position: "relative", paddingBottom: 88 },
  header: {
    position: "sticky",
    top: 0,
    zIndex: 5,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "16px 40px",
    background: "rgba(12,12,16,0.82)",
    backdropFilter: "blur(14px)",
    borderBottom: "1px solid var(--line)",
  },
  brandLink: { display: "inline-flex", alignItems: "center", gap: 8 },

  main: { maxWidth: 880, margin: "0 auto", padding: "56px 40px 40px" },

  loading: { padding: "48px 0", color: "var(--text-muted)", textAlign: "center" },

  hero: {
    display: "grid",
    gridTemplateColumns: "1fr 0.62fr",
    gap: 48,
    alignItems: "center",
    marginBottom: 64,
  },
  heroLeft: { minWidth: 0 },
  eyebrow: {
    fontSize: 13,
    color: "var(--text-muted)",
    marginBottom: 24,
    lineHeight: 1.55,
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 48,
    lineHeight: 1.05,
    fontWeight: 400,
    color: "var(--text)",
    margin: "0 0 24px",
    letterSpacing: "0.02em",
  },
  worldLink: {
    color: "var(--accent)",
    fontSize: 13,
    borderBottom: "1px dashed rgba(212,168,83,0.4)",
    paddingBottom: 2,
    background: "none",
  },
  heroRight: { display: "flex", justifyContent: "center" },
  coverWrap: {
    position: "relative",
    width: "100%",
    aspectRatio: "4/5",
    borderRadius: "var(--radius-md)",
    overflow: "hidden",
    border: "1px solid var(--line)",
    boxShadow: "0 30px 60px rgba(0,0,0,0.5)",
  },
  coverImg: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.83) saturate(0.92)",
  },
  coverDarken: {
    position: "absolute",
    inset: 0,
    background: "rgba(12,12,16,0.32)",
  },
  coverRadial: {
    position: "absolute",
    inset: 0,
    background: "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 30%, rgba(12,12,16,0.55) 100%)",
  },
  coverEdges: {
    position: "absolute",
    inset: 0,
    boxShadow: "inset 0 -90px 80px -40px rgba(12,12,16,0.85), inset 0 0 60px rgba(12,12,16,0.4)",
  },

  transcript: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
    padding: "8px 0 40px",
    marginBottom: 24,
  },
  bubblePlayer: {
    background: "rgba(212,168,83,0.10)",
    borderLeft: "2px solid var(--accent)",
    padding: "14px 18px",
    borderRadius: "0 10px 10px 0",
    maxWidth: 620,
  },
  playerEyebrow: {
    fontSize: 10,
    color: "var(--accent)",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    marginBottom: 6,
    fontWeight: 600,
  },
  playerText: {
    fontFamily: "var(--font-ui)",
    fontSize: 15,
    lineHeight: 1.6,
    color: "var(--text)",
  },
  bubbleGM: {},
  gmText: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.7,
    color: "var(--text)",
    margin: 0,
    letterSpacing: "0.005em",
  },

  endingSection: {
    paddingTop: 32,
    marginTop: 8,
    borderTop: "1px solid var(--line)",
  },
  endingArtwork: {
    position: "relative",
    width: "100%",
    height: 280,
    borderRadius: 14,
    overflow: "hidden",
    marginBottom: 28,
    border: "1px solid var(--line)",
    boxShadow: "0 30px 60px rgba(0,0,0,0.45)",
  },
  endingArtworkImg: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.85) saturate(0.92)",
  },
  endingArtworkDarken: {
    position: "absolute",
    inset: 0,
    background: "rgba(12,12,16,0.18)",
  },
  endingArtworkGradient: {
    position: "absolute",
    inset: 0,
    background:
      "linear-gradient(to bottom, rgba(12,12,16,0) 30%, rgba(12,12,16,0.55) 60%, rgba(12,12,16,0.92) 100%)",
  },
  endingArtworkInner: {
    position: "absolute",
    left: 28,
    right: 28,
    bottom: 24,
  },
  endingArtworkEyebrow: {
    display: "inline-block",
    fontSize: 10,
    color: "var(--accent)",
    letterSpacing: "0.22em",
    textTransform: "uppercase",
    marginBottom: 10,
    fontWeight: 600,
  },
  endingArtworkTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 32,
    fontWeight: 400,
    color: "var(--accent)",
    margin: 0,
    letterSpacing: "0.04em",
  },
  endingSummary: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.7,
    color: "var(--text)",
    margin: 0,
    maxWidth: 680,
  },

  footer: {
    marginTop: 56,
    padding: "20px 0",
    borderTop: "1px solid var(--line)",
    display: "flex",
    justifyContent: "space-between",
    fontSize: 12,
  },

  stickyBar: {
    position: "fixed",
    left: 0,
    right: 0,
    bottom: 0,
    height: 64,
    background: "rgba(12,12,16,0.92)",
    backdropFilter: "blur(16px)",
    borderTop: "1px solid rgba(212,168,83,0.45)",
    zIndex: 5,
  },
  stickyInner: {
    height: "100%",
    maxWidth: 880,
    margin: "0 auto",
    padding: "0 40px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
  },
  stickyMeta: {
    fontSize: 14,
    color: "var(--text-muted)",
    fontFamily: "var(--font-narrative)",
  },
}
