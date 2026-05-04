import { useEffect, useState } from "react"
import { motion } from "motion/react"
import type { PublishedStoryDetailResponse, StoryVisibility } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { Button, EmptyState, ErrorState, Tag } from "../../shared/ui/primitives"
import { localizeTheme } from "../../shared/lib/format"

export function WorldDetailPage({
  storyId,
  onBackHome,
  onOpenCreate,
  onOpenPlay,
}: {
  storyId: string
  onBackHome: () => void
  onOpenCreate: () => void
  onOpenPlay: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [detail, setDetail] = useState<PublishedStoryDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [copyHint, setCopyHint] = useState(false)
  const [visibilityBusy, setVisibilityBusy] = useState(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setLoadError(null)
    const load = async () => {
      try {
        const response = await api.getStory(storyId)
        if (active) setDetail(response)
      } catch (err) {
        if (active) setLoadError(err instanceof Error ? err.message : "World 不存在或不可见")
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [api, storyId])

  const handleStart = async () => {
    if (starting) return
    setStarting(true)
    setActionError(null)
    try {
      const session = await api.createPlaySession({ story_id: storyId })
      onOpenPlay(session.session_id)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "无法开始游玩")
      setStarting(false)
    }
  }

  const handleCopyShare = async () => {
    const url = `${window.location.origin}${window.location.pathname}#/world/${storyId}`
    try {
      await navigator.clipboard.writeText(url)
      setCopyHint(true)
      window.setTimeout(() => setCopyHint(false), 1800)
    } catch {
      window.prompt("复制这个链接发给朋友：", url)
    }
  }

  const handleVisibilityChange = async (next: StoryVisibility) => {
    if (visibilityBusy) return
    setVisibilityBusy(true)
    try {
      await api.updateStoryVisibility(storyId, { visibility: next })
      const refreshed = await api.getStory(storyId)
      setDetail(refreshed)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "无法更新可见性")
    } finally {
      setVisibilityBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="page page-world">
        <Header onHome={onBackHome} onCreate={onOpenCreate} showCreateButton={!auth.isAnonymous} />
        <main className="world-main">
          <p className="world-loading">正在拉开 world...</p>
        </main>
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="page page-world">
        <Header onHome={onBackHome} onCreate={onOpenCreate} showCreateButton={!auth.isAnonymous} />
        <main className="world-main">
          <EmptyState title={loadError ?? "World 不可见"} hint="可能链接错了，或这个 world 是私密的。" />
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" onClick={onBackHome}>返回首页</Button>
          </div>
        </main>
      </div>
    )
  }

  const story = detail.story
  const canManage = Boolean(detail.presentation?.viewer_can_manage)
  const visibility = story.visibility

  return (
    <div className="page page-world">
      <Header onHome={onBackHome} onCreate={onOpenCreate} />

      <main className="world-main">
        <motion.section
          className="world-hero"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
        >
          <div className="world-hero__cover">
            <span className="world-hero__cover-glyph">{story.title.slice(0, 1)}</span>
          </div>
          <div className="world-hero__body">
            <div className="world-hero__tags">
              <Tag tone="accent">{localizeTheme(story.theme)}</Tag>
              <Tag tone="muted">{`${story.npc_count} 个角色`}</Tag>
              <Tag tone="muted">{`${story.beat_count} 幕`}</Tag>
              {visibility === "private" ? <Tag tone="muted">私密</Tag> : null}
              {visibility === "unlisted" ? <Tag tone="muted">仅链接</Tag> : null}
              {visibility === "public" ? <Tag tone="muted">公开</Tag> : null}
            </div>
            <h1>{story.title}</h1>
            <p className="world-hero__lede">{story.one_liner}</p>

            {story.play_count > 0 ? (
              <div className="world-stats">
                <span>★ 被玩过 {story.play_count} 次</span>
                {story.unique_player_count > 0 ? (
                  <span>· {story.unique_player_count} 人</span>
                ) : null}
                {Object.keys(story.ending_distribution ?? {}).length > 0 ? (
                  <span>· {Object.keys(story.ending_distribution).length} 种结局</span>
                ) : null}
              </div>
            ) : (
              <div className="world-stats world-stats--quiet">
                <span>还没有人玩过</span>
              </div>
            )}

            {actionError ? <ErrorState message={actionError} /> : null}

            <div className="world-hero__actions">
              <Button variant="primary" size="lg" disabled={starting} onClick={() => void handleStart()}>
                {starting ? "正在开场..." : "开玩"}
              </Button>
              <Button variant="secondary" onClick={() => void handleCopyShare()}>
                {copyHint ? "已复制 ✓" : "复制分享链接"}
              </Button>
            </div>
          </div>
        </motion.section>

        <section className="world-premise">
          <span className="world-premise__label">故事简介</span>
          <p>{story.premise}</p>
        </section>

        {canManage ? (
          <section className="world-author">
            <h2>作者面板</h2>
            <p className="world-author__sub">这些只有你（创作者）能看见。</p>

            <div className="world-author__row">
              <span>可见性</span>
              <div className="world-author__visibility">
                {(["private", "unlisted", "public"] as StoryVisibility[]).map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    className={`visibility-chip ${visibility === opt ? "is-active" : ""}`}
                    disabled={visibilityBusy}
                    onClick={() => void handleVisibilityChange(opt)}
                  >
                    <strong>
                      {opt === "private" ? "私密" : opt === "unlisted" ? "仅链接" : "公开"}
                    </strong>
                    <span>
                      {opt === "private"
                        ? "只有我能玩"
                        : opt === "unlisted"
                          ? "有链接的人可以玩，不出现在首页"
                          : "出现在首页推荐"}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {Object.keys(story.ending_distribution ?? {}).length > 0 ? (
              <div className="world-author__endings">
                <span>玩家走出过的结局</span>
                <ul>
                  {Object.entries(story.ending_distribution)
                    .sort(([, a], [, b]) => b - a)
                    .map(([endingId, count]) => (
                      <li key={endingId}>
                        <strong>{endingId}</strong>
                        <span>{count} 次</span>
                      </li>
                    ))}
                </ul>
              </div>
            ) : null}
          </section>
        ) : null}
      </main>
    </div>
  )
}
