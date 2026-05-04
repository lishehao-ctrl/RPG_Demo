import { useEffect, useMemo, useState } from "react"
import { motion } from "motion/react"
import type { PublishedStoryCard } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { Button, Card, EmptyState, ErrorState, Skeleton, Tag } from "../../shared/ui/primitives"
import { readContinueSession, clearContinueSession, type ContinueSession } from "../../shared/lib/continue-session"
import { formatRelativeTime, localizeTheme } from "../../shared/lib/format"

type StoryGroups = {
  mine: PublishedStoryCard[]
  hot: PublishedStoryCard[]
  latest: PublishedStoryCard[]
}

const EMPTY_GROUPS: StoryGroups = { mine: [], hot: [], latest: [] }

export function HomePage({
  initialOpenStoryId,
  onOpenCreate,
  onOpenPlay,
}: {
  initialOpenStoryId?: string
  onOpenCreate: () => void
  onOpenPlay: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [groups, setGroups] = useState<StoryGroups | null>(null)
  const [searching, setSearching] = useState<PublishedStoryCard[] | null>(null)
  const [search, setSearch] = useState("")
  const [loadError, setLoadError] = useState<string | null>(null)
  const [continueSession, setContinueSession] = useState<ContinueSession | null>(null)

  useEffect(() => {
    setContinueSession(readContinueSession())
  }, [])

  // If a story_id was deep-linked, jump to its world page.
  useEffect(() => {
    if (initialOpenStoryId) {
      window.location.hash = `#/world/${initialOpenStoryId}`
    }
  }, [initialOpenStoryId])

  // Initial load: hot + latest in parallel; mine only if signed in.
  useEffect(() => {
    if (auth.loading) return
    let active = true
    const load = async () => {
      setLoadError(null)
      try {
        const requests: Array<Promise<PublishedStoryCard[]>> = [
          api.listStories({ view: "public", sort: "play_count_desc", limit: 8 }).then((r) => r.stories),
          api.listStories({ view: "public", sort: "published_at_desc", limit: 12 }).then((r) => r.stories),
        ]
        if (!auth.isAnonymous) {
          requests.push(api.listMyWorlds({ limit: 12 }).then((r) => r.stories))
        }
        const [hot, latest, mine = []] = await Promise.all(requests)
        if (!active) return
        setGroups({ mine, hot, latest })
      } catch (err) {
        if (!active) return
        setLoadError(err instanceof Error ? err.message : "无法加载故事")
        setGroups(EMPTY_GROUPS)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [api, auth.loading, auth.isAnonymous])

  // Debounced search across the public set.
  useEffect(() => {
    const trimmed = search.trim()
    if (!trimmed) {
      setSearching(null)
      return
    }
    let active = true
    const handle = window.setTimeout(async () => {
      try {
        const result = await api.listStories({ view: "public", q: trimmed, limit: 30 })
        if (active) setSearching(result.stories)
      } catch {
        if (active) setSearching([])
      }
    }, 240)
    return () => {
      active = false
      window.clearTimeout(handle)
    }
  }, [api, search])

  const handleContinueDismiss = () => {
    clearContinueSession()
    setContinueSession(null)
  }

  const groupSafe = groups ?? EMPTY_GROUPS
  const showMine = !auth.isAnonymous && groupSafe.mine.length > 0
  const totalMyPlays = useMemo(
    () => groupSafe.mine.reduce((acc, w) => acc + (w.play_count ?? 0), 0),
    [groupSafe.mine],
  )

  return (
    <div className="page page-home">
      <Header onHome={() => undefined} onCreate={onOpenCreate} />

      <main className="home-main">
        {continueSession ? (
          <motion.section
            className="continue-banner"
            initial={{ y: -8, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.3 }}
          >
            <div className="continue-banner__copy">
              <Tag tone="accent">继续上次</Tag>
              <strong>{continueSession.story_title}</strong>
              <span>
                {continueSession.beat_title} · 第 {continueSession.turn_index} 轮 · {formatRelativeTime(continueSession.saved_at)}
              </span>
            </div>
            <div className="continue-banner__actions">
              <Button variant="primary" onClick={() => onOpenPlay(continueSession.session_id)}>
                继续游玩
              </Button>
              <Button variant="ghost" onClick={handleContinueDismiss}>
                忽略
              </Button>
            </div>
          </motion.section>
        ) : null}

        <section className="home-hero">
          <motion.div
            className="home-hero__copy"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <h1>写一个 world，朋友来玩。</h1>
            <p>
              把一个故事开头交给 AI，几分钟内变成一份可以分享的剧本。每个朋友进来玩，都会写出他们自己的版本。
            </p>
            <div className="home-hero__actions">
              <Button variant="primary" size="lg" onClick={onOpenCreate}>
                写一个 world
              </Button>
              <a className="home-hero__scroll-hint" href="#stories">
                先看朋友们做了什么 ↓
              </a>
            </div>
          </motion.div>
        </section>

        <section className="home-stories" id="stories">
          <div className="home-stories__header">
            <h2>挑一个开始</h2>
            <input
              className="home-search"
              type="search"
              placeholder="搜 world 标题、主题..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {loadError ? <ErrorState message={loadError} /> : null}

          {searching !== null ? (
            <StorySection
              title={`「${search}」的搜索结果`}
              stories={searching}
              emptyHint="没匹配上 — 换个关键词试试"
            />
          ) : !groups ? (
            <SkeletonGrid />
          ) : (
            <>
              {showMine ? (
                <StorySection
                  title="我的 worlds"
                  subtitle={`${groupSafe.mine.length} 个 world · 累计被玩 ${totalMyPlays} 次`}
                  stories={groupSafe.mine}
                  emphasizeStats
                />
              ) : null}

              <StorySection
                title="热门"
                subtitle="这周最多人玩"
                stories={groupSafe.hot}
                emptyHint="还没有人玩 — 你的 world 可以是第一个"
                emphasizeStats
              />

              <StorySection
                title="最近发布"
                stories={groupSafe.latest}
                emptyHint="第一个公开 world 的位置在等你"
              />
            </>
          )}
        </section>
      </main>
    </div>
  )
}

function StorySection({
  title,
  subtitle,
  stories,
  emptyHint,
  emphasizeStats,
}: {
  title: string
  subtitle?: string
  stories: PublishedStoryCard[]
  emptyHint?: string
  emphasizeStats?: boolean
}) {
  return (
    <section className="story-section">
      <div className="story-section__header">
        <h3>{title}</h3>
        {subtitle ? <span>{subtitle}</span> : null}
      </div>
      {stories.length === 0 ? (
        <EmptyState title={emptyHint ?? "暂时没有"} />
      ) : (
        <div className="story-grid">
          {stories.map((story) => (
            <StoryCard key={story.story_id} story={story} emphasizeStats={emphasizeStats} />
          ))}
        </div>
      )}
    </section>
  )
}

function StoryCard({ story, emphasizeStats }: { story: PublishedStoryCard; emphasizeStats?: boolean }) {
  const handleOpen = () => {
    window.location.hash = `#/world/${story.story_id}`
  }

  return (
    <motion.button
      className="story-card"
      type="button"
      onClick={handleOpen}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.18 }}
    >
      <div className="story-card__cover">
        <span className="story-card__cover-glyph">{story.title.slice(0, 1)}</span>
      </div>
      <div className="story-card__body">
        <div className="story-card__tags">
          <Tag tone="muted">{localizeTheme(story.theme)}</Tag>
          {story.visibility === "private" ? <Tag tone="muted">私密</Tag> : null}
          {story.visibility === "unlisted" ? <Tag tone="muted">仅链接</Tag> : null}
        </div>
        <h3>{story.title}</h3>
        <p>{story.one_liner}</p>
        {emphasizeStats && story.play_count > 0 ? (
          <div className="story-card__stats">
            <span>★ 被玩过 {story.play_count} 次</span>
            {story.unique_player_count > 0 ? <span>{story.unique_player_count} 人</span> : null}
          </div>
        ) : null}
      </div>
    </motion.button>
  )
}

function SkeletonGrid() {
  return (
    <section className="story-section">
      <div className="story-grid">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="story-card-skeleton">
            <Skeleton height={140} />
            <div className="story-card-skeleton__body">
              <Skeleton height={20} width="60%" />
              <Skeleton height={14} />
              <Skeleton height={14} width="80%" />
            </div>
          </Card>
        ))}
      </div>
    </section>
  )
}
