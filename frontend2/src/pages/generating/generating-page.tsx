import { type CSSProperties, useEffect, useRef, useState } from "react"
import type { AuthorJobStatusResponse, AuthorPreviewFlashcard } from "../../api/contracts"
import { useApi } from "../../app/api-context"

type Stage = {
  until: number
  title: string
  sub: string
  label: string
}

const STAGES: Stage[] = [
  { until: 0.25, title: "在脑海里搭世界…", sub: "AI 正在选定氛围、地点和时间。", label: "构筑" },
  { until: 0.55, title: "写人物…", sub: "给每个人一份秘密、一份愿望,再给他们彼此。", label: "塑形" },
  { until: 0.8, title: "编排节奏…", sub: "把开端、转折、爆点、余波摆到合适的拍子上。", label: "节拍" },
  { until: 0.98, title: "准备开场…", sub: "把镜头交给你。", label: "上幕" },
  { until: 1.01, title: "正在拉开帷幕…", sub: "几秒后进入。", label: "登场" },
]

function pickStage(progress: number): Stage {
  return STAGES.find((s) => progress < s.until) || STAGES[STAGES.length - 1]
}

function ratioOf(job: AuthorJobStatusResponse | null): number {
  if (!job) return 0
  const snap = job.progress_snapshot
  if (snap) {
    const r = snap.completion_ratio || (snap.stage_index + 1) / Math.max(1, snap.stage_total)
    return Math.max(0, Math.min(1, r))
  }
  if (job.progress) {
    return Math.max(0, Math.min(1, (job.progress.stage_index + 1) / Math.max(1, job.progress.stage_total)))
  }
  return 0
}

function pickHighlightCard(cards: AuthorPreviewFlashcard[] | undefined): AuthorPreviewFlashcard | null {
  if (!cards || cards.length === 0) return null
  const stable = cards.filter((c) => c.kind === "stable")
  return stable[stable.length - 1] ?? cards[cards.length - 1] ?? null
}

export function GeneratingPage({
  jobId,
  onBackHome,
  onOpenWorld,
}: {
  jobId: string
  onBackHome: () => void
  onOpenWorld: (storyId: string) => void
}) {
  const api = useApi()
  const [job, setJob] = useState<AuthorJobStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [completing, setCompleting] = useState(false)
  const handlingCompletionRef = useRef(false)

  // SSE subscription, with initial pull.
  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        const initial = await api.getAuthorJob(jobId)
        if (cancelled) return
        setJob(initial)
        if (initial.status === "completed" || initial.status === "failed") return
        for await (const event of api.streamAuthorJobEvents(jobId)) {
          if (cancelled) break
          if (event.event === "job_failed") {
            const data = event.data as { error?: { message?: string } }
            setError(data?.error?.message ?? "生成失败")
            break
          }
          try {
            const fresh = await api.getAuthorJob(jobId)
            if (!cancelled) setJob(fresh)
            if (fresh.status === "completed" || fresh.status === "failed") break
          } catch {
            // transient
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "无法连接生成服务")
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [api, jobId])

  // On completion → publish unlisted, then open world detail.
  useEffect(() => {
    if (!job) return
    if (job.status !== "completed") return
    if (handlingCompletionRef.current) return
    handlingCompletionRef.current = true

    const handoff = async () => {
      setCompleting(true)
      try {
        const published = await api.publishAuthorJob(jobId, "unlisted")
        // Tiny delay so the "拉开帷幕" frame is visible.
        window.setTimeout(() => onOpenWorld(published.story_id), 600)
      } catch (err) {
        setError(err instanceof Error ? err.message : "无法准备 world，请稍后重试。")
        setCompleting(false)
        handlingCompletionRef.current = false
      }
    }
    void handoff()
  }, [job, api, jobId, onOpenWorld])

  const progress = ratioOf(job)
  const current = completing ? STAGES[STAGES.length - 1] : pickStage(progress)
  const snapshot = job?.progress_snapshot ?? null
  const previewTitle = snapshot?.preview_title || job?.preview?.story.title
  const previewPremise = snapshot?.preview_premise || job?.preview?.story.premise
  const highlight = pickHighlightCard(snapshot?.flashcards)

  const failed = job?.status === "failed" || (error !== null && !completing)

  if (failed) {
    return (
      <div style={gpStyles.page}>
        <div style={gpStyles.ambientBg} />
        <div style={gpStyles.ambientRadial} />
        <header style={gpStyles.header}>
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
          <span style={gpStyles.brandName}>Tiny Stories</span>
        </header>
        <main style={gpStyles.main}>
          <div style={gpStyles.card}>
            <span
              className="ts-tag"
              style={{ marginBottom: 28, color: "var(--warn)", borderColor: "rgba(224,122,95,0.45)" }}
            >
              <span style={{ ...gpStyles.dot, background: "var(--warn)" }} /> 失败
            </span>
            <h1 style={gpStyles.title}>这次没写出来。</h1>
            <p style={gpStyles.sub}>
              {error ?? "AI 这次没写出来 — 你可以换个开头再试。"}
              <br />
              <span style={{ color: "var(--text-faint)", fontSize: 13 }}>
                通常是因为开头太短或太抽象。试试加一句具体的场景或角色。
              </span>
            </p>
            <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
              <button
                className="ts-btn ts-btn--primary ts-btn--lg"
                onClick={() => {
                  window.location.hash = "#/create"
                }}
              >
                换个开头再试
              </button>
              <button className="ts-btn ts-btn--ghost ts-btn--lg" onClick={onBackHome}>
                返回首页
              </button>
            </div>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div style={gpStyles.page}>
      <div
        style={{
          ...gpStyles.ambientBg,
          opacity: completing ? 0.55 : 1,
          transition: "opacity 700ms ease",
        }}
      />
      <div style={gpStyles.ambientRadial} />
      <header style={gpStyles.header}>
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
        <span style={gpStyles.brandName}>Tiny Stories</span>
      </header>

      <main style={{ ...gpStyles.main, opacity: completing ? 0 : 1, transition: "opacity 500ms ease 200ms" }}>
        <div style={gpStyles.card}>
          <span className="ts-tag" style={{ marginBottom: 28 }}>
            <span style={gpStyles.dot} /> 生成中
          </span>

          <h1 key={current.title} style={gpStyles.title}>
            {current.title}
          </h1>
          <p key={current.sub} style={gpStyles.sub}>
            {current.sub}
          </p>

          <div style={gpStyles.progressRow}>
            <span style={gpStyles.progressPct}>{Math.round(progress * 100)}%</span>
            <div style={gpStyles.progressTrack}>
              <div style={{ ...gpStyles.progressFill, width: `${progress * 100}%` }} />
            </div>
            <span style={gpStyles.progressLabel}>{current.label}</span>
          </div>

          {previewTitle ? (
            <div style={gpStyles.preview}>
              <div style={gpStyles.previewEyebrow}>这次的 world 看起来叫</div>
              <div style={gpStyles.previewTitle}>{previewTitle}</div>
              {previewPremise ? <div style={gpStyles.previewPremise}>{previewPremise}</div> : null}
            </div>
          ) : null}

          {highlight ? (
            <div style={gpStyles.highlights}>
              <div style={gpStyles.highlight}>
                <div style={gpStyles.highlightText}>
                  <div style={gpStyles.highlightLabel}>{highlight.label}</div>
                  <div style={gpStyles.highlightValue}>{highlight.value}</div>
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <p style={gpStyles.hint}>这个过程通常在一分钟左右。可以离开页面,回来时它会自己进入。</p>
      </main>
    </div>
  )
}

const gpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)", position: "relative" },
  ambientBg: {
    position: "absolute",
    inset: 0,
    backgroundImage: "url(/webtoons/ui/library_bg.jpg)",
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.32) saturate(0.85)",
    pointerEvents: "none",
  },
  ambientRadial: {
    position: "absolute",
    inset: 0,
    background:
      "radial-gradient(ellipse at 50% 38%, rgba(12,12,16,0.0) 0%, rgba(12,12,16,0.55) 60%, rgba(12,12,16,0.92) 100%)",
    pointerEvents: "none",
  },
  header: {
    position: "relative",
    zIndex: 2,
    padding: "18px 40px",
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  brandName: { fontFamily: "var(--font-narrative)", fontSize: 17 },
  main: {
    position: "relative",
    zIndex: 2,
    padding: "60px 40px 60px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  card: {
    width: "100%",
    maxWidth: 720,
    background: "rgba(21,22,28,0.85)",
    backdropFilter: "blur(36px)",
    WebkitBackdropFilter: "blur(36px)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-lg)",
    padding: 40,
    boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 999,
    background: "var(--accent)",
    boxShadow: "0 0 0 0 rgba(212,168,83,0.5)",
    animation: "tsPulse 1.6s ease-in-out infinite",
    display: "inline-block",
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 32,
    fontWeight: 400,
    lineHeight: 1.2,
    margin: "0 0 12px",
    animation: "tsFadeUp 380ms ease",
  },
  sub: {
    fontSize: 15,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    margin: "0 0 36px",
    animation: "tsFadeUp 480ms ease",
  },
  progressRow: { display: "flex", alignItems: "center", gap: 14, marginBottom: 32 },
  progressPct: { fontSize: 12, color: "var(--accent)", fontVariantNumeric: "tabular-nums", minWidth: 32 },
  progressTrack: { flex: 1, height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" },
  progressFill: { height: "100%", background: "var(--accent)", borderRadius: 999, transition: "width 200ms linear" },
  progressLabel: {
    fontSize: 11,
    color: "var(--text-muted)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    minWidth: 36,
    textAlign: "right",
  },

  preview: {
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    padding: "20px 22px",
    marginBottom: 20,
    animation: "tsFadeUp 480ms ease",
  },
  previewEyebrow: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.12em",
    textTransform: "uppercase",
    marginBottom: 8,
  },
  previewTitle: { fontFamily: "var(--font-narrative)", fontSize: 22, margin: "0 0 10px" },
  previewPremise: { fontFamily: "var(--font-narrative)", fontSize: 14, lineHeight: 1.65, color: "var(--text-muted)" },

  highlights: { display: "flex", flexDirection: "column", gap: 10, marginTop: 4 },
  highlight: {
    borderLeft: "2px solid var(--accent)",
    background: "var(--accent-softer)",
    padding: "12px 14px",
    borderRadius: "0 8px 8px 0",
    animation: "tsSwapIn 380ms ease",
    display: "flex",
    alignItems: "center",
    gap: 14,
  },
  highlightText: { flex: 1, minWidth: 0 },
  highlightLabel: {
    fontSize: 11,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 4,
    fontWeight: 600,
  },
  highlightValue: { fontSize: 14, color: "var(--text)", lineHeight: 1.5 },

  hint: { marginTop: 28, fontSize: 12, color: "var(--text-faint)" },
}
