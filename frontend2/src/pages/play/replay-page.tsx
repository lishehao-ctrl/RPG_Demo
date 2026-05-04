import { useEffect, useState } from "react"
import { motion } from "motion/react"
import type { PlaySessionReplayResponse } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { Header } from "../../shared/ui/header"
import { Button, EmptyState, Tag } from "../../shared/ui/primitives"

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

  if (loading) {
    return (
      <div className="page page-replay">
        <Header onHome={onBackHome} onCreate={onOpenCreate} showCreateButton={false} />
        <main className="replay-main">
          <p className="world-loading">正在调取这场故事...</p>
        </main>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="page page-replay">
        <Header onHome={onBackHome} onCreate={onOpenCreate} showCreateButton={false} />
        <main className="replay-main">
          <EmptyState title={loadError ?? "Replay 不可见"} hint="可能链接错了。" />
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" onClick={onBackHome}>返回首页</Button>
          </div>
        </main>
      </div>
    )
  }

  return (
    <div className="page page-replay">
      <Header onHome={onBackHome} onCreate={onOpenCreate} />

      <main className="replay-main">
        <motion.section
          className="replay-hero"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Tag tone="accent">{data.completed ? "玩出的结局" : "玩到了一半"}</Tag>
          <h1>{data.story_title}</h1>
          {data.ending ? (
            <p className="replay-hero__ending">结局：{data.ending.label}</p>
          ) : null}
        </motion.section>

        <section className="replay-transcript">
          {data.entries.length === 0 ? (
            <EmptyState title="还没有内容" />
          ) : (
            data.entries.map((entry, idx) => (
              <article
                key={`${entry.speaker}-${entry.turn_index}-${idx}`}
                className={`transcript-entry transcript-entry--${entry.speaker}`}
              >
                <span>{entry.speaker === "player" ? "玩家" : "故事"}</span>
                <p>{entry.text}</p>
              </article>
            ))
          )}
        </section>

        {data.ending ? (
          <section className="replay-ending">
            <h2>结局：{data.ending.label}</h2>
            <p>{data.ending.summary}</p>
          </section>
        ) : null}

        <section className="replay-cta">
          <h3>也来玩这个 world</h3>
          <p>同样的世界，你会做出不同的选择。</p>
          <Button variant="primary" size="lg" onClick={handlePlayThisWorld}>
            进入 world 自己玩
          </Button>
        </section>
      </main>
    </div>
  )
}
