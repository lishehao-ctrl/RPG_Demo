import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type { AuthorJobResultResponse, AuthorJobStatusResponse, AuthorPreviewFlashcard } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { Header } from "../../shared/ui/header"
import { Button, ErrorState, Tag } from "../../shared/ui/primitives"

type Phase = {
  threshold: number
  caption: string
  detail: string
}

const PHASES: Phase[] = [
  { threshold: 0, caption: "在脑海里搭世界...", detail: "AI 正在选定氛围、地点和故事的发力方向。" },
  { threshold: 0.25, caption: "写人物...", detail: "给每个角色找名字、欲望、和不能说出口的事。" },
  { threshold: 0.55, caption: "编排节奏...", detail: "把冲突切成一幕一幕，决定什么时候揭开秘密。" },
  { threshold: 0.8, caption: "准备开场...", detail: "把一切收拢成第一句话，等你开始。" },
]

function pickPhase(ratio: number): Phase {
  let chosen = PHASES[0]
  for (const p of PHASES) {
    if (ratio >= p.threshold) chosen = p
  }
  return chosen
}

function pickHighlightCard(cards: AuthorPreviewFlashcard[] | undefined): AuthorPreviewFlashcard | null {
  if (!cards || cards.length === 0) return null
  // Prefer "stable" cards once they show up — they're the parts that won't change.
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
  const [transitioning, setTransitioning] = useState(false)
  const handlingCompletionRef = useRef(false)

  // Subscribe to SSE
  useEffect(() => {
    let cancelled = false

    const run = async () => {
      try {
        // Initial pull so we render something immediately even before first SSE event
        const initial = await api.getAuthorJob(jobId)
        if (cancelled) return
        setJob(initial)
        if (initial.status === "completed" || initial.status === "failed") {
          // Skip stream — we already know the terminal state.
          return
        }
        for await (const event of api.streamAuthorJobEvents(jobId)) {
          if (cancelled) break
          if (event.event === "job_failed") {
            const data = event.data as { error?: { message?: string } }
            setError(data?.error?.message ?? "生成失败")
            break
          }
          // For any other event, re-pull job state (cheaper than parsing event.data shapes).
          try {
            const fresh = await api.getAuthorJob(jobId)
            if (!cancelled) setJob(fresh)
            if (fresh.status === "completed" || fresh.status === "failed") break
          } catch {
            // transient — keep streaming
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

  // When job completes successfully → publish as unlisted (default share-friendly visibility)
  // → jump to the World Detail page so the author sees the public-facing surface and can grab
  // the share link before they (or anyone else) starts a play session.
  useEffect(() => {
    if (!job) return
    if (job.status !== "completed") return
    if (handlingCompletionRef.current) return
    handlingCompletionRef.current = true

    const handoff = async () => {
      setTransitioning(true)
      try {
        const published = await api.publishAuthorJob(jobId, "unlisted")
        onOpenWorld(published.story_id)
      } catch (err) {
        setError(err instanceof Error ? err.message : "无法准备 world，请稍后重试。")
        setTransitioning(false)
        handlingCompletionRef.current = false
      }
    }

    void handoff()
  }, [job, api, jobId, onOpenWorld])

  const snapshot = job?.progress_snapshot ?? null
  const ratio = snapshot
    ? Math.max(0, Math.min(1, snapshot.completion_ratio || (snapshot.stage_index + 1) / Math.max(1, snapshot.stage_total)))
    : job?.progress
      ? Math.max(0, Math.min(1, (job.progress.stage_index + 1) / Math.max(1, job.progress.stage_total)))
      : 0
  const phase = pickPhase(ratio)
  const percent = Math.round(ratio * 100)
  const highlight = pickHighlightCard(snapshot?.flashcards)
  const previewTitle = snapshot?.preview_title || job?.preview?.story.title
  const previewPremise = snapshot?.preview_premise || job?.preview?.story.premise

  return (
    <div className="page page-generating">
      <Header onHome={onBackHome} onCreate={() => undefined} showCreateButton={false} />

      <main className="generating-main">
        <motion.div
          className="generating-card"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="generating-card__phase">
            <Tag tone="accent">{transitioning ? "准备进入" : "生成中"}</Tag>
            <AnimatePresence mode="wait">
              <motion.h1
                key={transitioning ? "handoff" : phase.caption}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.35 }}
              >
                {transitioning ? "正在拉开帷幕..." : phase.caption}
              </motion.h1>
            </AnimatePresence>
            <p className="generating-card__detail">{transitioning ? "故事就绪，马上开场。" : phase.detail}</p>
          </div>

          <div className="progress-bar">
            <motion.div
              className="progress-bar__fill"
              initial={{ width: 0 }}
              animate={{ width: `${percent}%` }}
              transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>
          <div className="progress-bar__meta">
            <span>{percent}%</span>
            <span>{snapshot?.stage_label ?? "正在准备..."}</span>
          </div>

          {previewTitle ? (
            <motion.section
              className="generating-preview"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4 }}
            >
              <span className="generating-preview__label">这次的故事看起来叫</span>
              <h2>{previewTitle}</h2>
              {previewPremise ? <p>{previewPremise}</p> : null}
            </motion.section>
          ) : null}

          {highlight ? (
            <AnimatePresence mode="wait">
              <motion.div
                key={highlight.card_id}
                className="generating-highlight"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.4 }}
              >
                <span className="generating-highlight__label">{highlight.label}</span>
                <strong>{highlight.value}</strong>
              </motion.div>
            </AnimatePresence>
          ) : null}

          {error ? (
            <div className="generating-error">
              <ErrorState message={error} />
              <div className="generating-error__actions">
                <Button variant="primary" onClick={onBackHome}>
                  返回首页
                </Button>
              </div>
            </div>
          ) : null}
        </motion.div>
      </main>
    </div>
  )
}

// Mark unused import as used to satisfy noUnusedParameters when result is later wired.
export type { AuthorJobResultResponse }
