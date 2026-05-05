import { type CSSProperties, useEffect, useMemo, useState } from "react"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { HeaderUserMenu } from "../../shared/ui/header-user-menu"
import { readContinueSession, type ContinueSession } from "../../shared/lib/continue-session"
import { formatRelativeTime } from "../../shared/lib/format"
import { adaptStory, type UiStory } from "./adapt"
import { StoryDrawer } from "./story-drawer"

type Group = {
  id: "mine" | "popular" | "latest"
  eyebrow: string
  title: string
  stories: UiStory[]
}

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
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [continueSession, setContinueSession] = useState<ContinueSession | null>(null)
  const [continueIgnored, setContinueIgnored] = useState(false)
  const [query, setQuery] = useState("")
  const [drawerStory, setDrawerStory] = useState<UiStory | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    setContinueSession(readContinueSession())
  }, [])

  // Deep link to specific world (e.g. shared link arrives with #/?story=xyz).
  useEffect(() => {
    if (initialOpenStoryId) {
      window.location.hash = `#/world/${initialOpenStoryId}`
    }
  }, [initialOpenStoryId])

  // Initial load.
  useEffect(() => {
    if (auth.loading) return
    let active = true
    setLoadError(null)

    const load = async () => {
      try {
        const popularReq = api.listStories({ view: "public", sort: "play_count_desc", limit: 12 })
        const latestReq = api.listStories({ view: "public", sort: "published_at_desc", limit: 12 })
        const mineReq = !auth.isAnonymous ? api.listMyWorlds({ limit: 12 }) : null

        const [popular, latest, mine] = await Promise.all([popularReq, latestReq, mineReq])
        if (!active) return

        const handle = auth.user?.display_name ?? null
        const out: Group[] = []
        if (mine && mine.stories.length > 0) {
          out.push({
            id: "mine",
            eyebrow: "你的",
            title: "你写的 worlds",
            stories: mine.stories.map((s) => adaptStory(s, handle)),
          })
        }
        out.push({
          id: "popular",
          eyebrow: "热门",
          title: "热门",
          stories: popular.stories.map((s) => adaptStory(s, null)),
        })
        out.push({
          id: "latest",
          eyebrow: "最新",
          title: "最新",
          stories: latest.stories.map((s) => adaptStory(s, null)),
        })
        setGroups(out)
      } catch (err) {
        if (!active) return
        setLoadError(err instanceof Error ? err.message : "无法加载故事")
        setGroups([])
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [api, auth.loading, auth.isAnonymous, auth.user?.display_name])

  const searching = query.trim().length > 0
  const searchResults = useMemo(() => {
    if (!searching || !groups) return []
    const q = query.trim().toLowerCase()
    const seen = new Set<string>()
    const all: UiStory[] = []
    groups.forEach((g) =>
      g.stories.forEach((s) => {
        if (seen.has(s.id)) return
        const hit =
          s.title.toLowerCase().includes(q) ||
          s.theme.toLowerCase().includes(q) ||
          s.lede.toLowerCase().includes(q) ||
          s.authorUsername.toLowerCase().includes(q)
        if (hit) {
          seen.add(s.id)
          all.push(s)
        }
      }),
    )
    return all
  }, [searching, query, groups])

  const handleOpenStory = (story: UiStory) => {
    setStartError(null)
    setDrawerStory(story)
    setDrawerOpen(true)
  }

  const handlePlay = async () => {
    if (!drawerStory || starting) return
    setStarting(true)
    setStartError(null)
    try {
      const session = await api.createPlaySession({ story_id: drawerStory.id })
      onOpenPlay(session.session_id)
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "无法开始游玩")
      setStarting(false)
    }
  }

  const handleOpenFullPage = () => {
    if (!drawerStory) return
    window.location.hash = `#/world/${drawerStory.id}`
  }

  const continueAgo = continueSession ? formatRelativeTime(continueSession.saved_at) : ""
  const headerUser = auth.isAnonymous || !auth.user
    ? null
    : { name: auth.user.display_name, world_count: groups?.find((g) => g.id === "mine")?.stories.length ?? 0 }

  return (
    <div style={hpStyles.page}>
      <header style={hpStyles.header}>
        <div style={hpStyles.brand}>
          <span style={hpStyles.brandDot}>·</span>
          <span style={hpStyles.brandName}>Tiny Stories</span>
        </div>
        <div style={hpStyles.headerRight}>
          <button className="ts-btn ts-btn--primary" onClick={onOpenCreate}>
            写一个 world
          </button>
          <HeaderUserMenu user={headerUser} />
        </div>
      </header>

      <main style={hpStyles.main}>
        {continueSession && !continueIgnored && (
          <div style={hpStyles.continue}>
            <div style={hpStyles.continueBg} />
            <div style={hpStyles.continueInner}>
              <div>
                <div style={hpStyles.continueEyebrow}>继续上次</div>
                <div style={hpStyles.continueTitle}>
                  <span style={hpStyles.continueWorld}>{continueSession.story_title}</span>
                  <span style={hpStyles.continueDot}>·</span>
                  <span style={hpStyles.continueAgo}>
                    {continueSession.beat_title} · {continueAgo}
                  </span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="ts-btn ts-btn--primary"
                  onClick={() => onOpenPlay(continueSession.session_id)}
                >
                  继续游玩
                </button>
                <button className="ts-btn ts-btn--ghost" onClick={() => setContinueIgnored(true)}>
                  忽略
                </button>
              </div>
            </div>
          </div>
        )}

        <section style={hpStyles.hero}>
          <div style={hpStyles.heroAmbient} />
          <div style={hpStyles.heroLeft}>
            <h1 style={hpStyles.heroTitle}>
              写一个 world,
              <br />
              朋友来玩。
            </h1>
            <p style={hpStyles.heroSub}>
              把一个故事开头交给 AI,几分钟内变成一份可以分享的剧本。每个朋友进来玩,都会写出他们自己的版本。
            </p>
            <div style={hpStyles.heroCtas}>
              <button className="ts-btn ts-btn--primary ts-btn--lg" onClick={onOpenCreate}>
                写一个 world
              </button>
              <a
                className="ts-link-dashed"
                href="#stories"
                onClick={(e) => {
                  e.preventDefault()
                  document.getElementById("hp-stories")?.scrollIntoView({ behavior: "smooth", block: "start" })
                }}
              >
                先看朋友们做了什么 ↓
              </a>
            </div>
          </div>
        </section>

        <section id="hp-stories" style={hpStyles.storiesSection}>
          {loadError ? <div style={hpStyles.error}>{loadError}</div> : null}

          {!groups ? (
            <div style={hpStyles.empty}>
              <div style={hpStyles.emptyTitle}>正在拉取故事…</div>
            </div>
          ) : searching ? (
            <div>
              <GroupHeader
                eyebrow="搜索"
                title={`搜索结果 · ${searchResults.length}`}
                sub={searchResults.length === 0 ? null : `匹配 "${query}"`}
                rightSlot={<SearchInput value={query} onChange={setQuery} />}
              />
              {searchResults.length === 0 ? (
                <div style={hpStyles.empty}>
                  <div style={hpStyles.emptyTitle}>没找到 — 试试别的词</div>
                  <div style={hpStyles.emptySub}>
                    或者,
                    <button style={hpStyles.emptyLink} onClick={onOpenCreate}>
                      写一个新的 world →
                    </button>
                  </div>
                </div>
              ) : (
                <div style={hpStyles.grid}>
                  {searchResults.map((s) => (
                    <StoryCard key={s.id} story={s} onClick={() => handleOpenStory(s)} />
                  ))}
                </div>
              )}
            </div>
          ) : (
            groups.map((g, gi) => {
              const isPopular = g.id === "popular"
              const isMine = g.id === "mine"
              const sub =
                g.id === "mine"
                  ? `${g.stories.length} 个 world · 累计被玩 ${g.stories.reduce(
                      (a, s) => a + s.played_count,
                      0,
                    )} 次`
                  : g.id === "popular"
                    ? "这周最多人玩"
                    : null
              return (
                <div key={g.id} style={{ marginBottom: gi < groups.length - 1 ? 64 : 0 }}>
                  <GroupHeader
                    eyebrow={g.eyebrow}
                    title={g.title}
                    sub={sub}
                    rightSlot={isPopular ? <SearchInput value={query} onChange={setQuery} /> : null}
                  />
                  {g.stories.length === 0 ? (
                    <div style={hpStyles.empty}>
                      <div style={hpStyles.emptyTitle}>还没有人玩 — 你的 world 可以是第一个</div>
                    </div>
                  ) : (
                    <div style={hpStyles.grid}>
                      {g.stories.map((s) => (
                        <StoryCard key={s.id} story={s} mine={isMine} onClick={() => handleOpenStory(s)} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </section>

        <footer style={hpStyles.footer}>
          <span style={{ color: "var(--text-faint)" }}>· Tiny Stories</span>
          <span style={{ color: "var(--text-faint)" }}>一个 world,无数个版本。</span>
        </footer>
      </main>

      <StoryDrawer
        story={drawerStory}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onPlay={() => void handlePlay()}
        onOpenFullPage={handleOpenFullPage}
        starting={starting}
        mode={drawerStory?.isOwnWorld ? "mine" : "default"}
      />
      {startError ? <div style={hpStyles.toast}>{startError}</div> : null}
    </div>
  )
}

function GroupHeader({
  eyebrow,
  title,
  sub,
  rightSlot,
}: {
  eyebrow: string
  title: string
  sub: string | null
  rightSlot: React.ReactNode
}) {
  return (
    <div style={hpStyles.groupHeader}>
      <div style={hpStyles.groupHeaderLeft}>
        <div style={hpStyles.groupEyebrow}>{eyebrow}</div>
        <h3 style={hpStyles.groupTitle}>{title}</h3>
        {sub && <div style={hpStyles.groupSub}>{sub}</div>}
      </div>
      {rightSlot && <div style={hpStyles.groupHeaderRight}>{rightSlot}</div>}
    </div>
  )
}

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div style={hpStyles.searchWrap}>
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        style={hpStyles.searchIcon}
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" strokeLinecap="round" />
      </svg>
      <input
        style={hpStyles.search}
        placeholder="搜索 world、作者、主题"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button style={hpStyles.searchClear} onClick={() => onChange("")} aria-label="清除">
          ×
        </button>
      )}
    </div>
  )
}

function StoryCard({
  story,
  onClick,
  mine = false,
}: {
  story: UiStory
  onClick: () => void
  mine?: boolean
}) {
  const [hover, setHover] = useState(false)
  const hasProof = story.played_count > 0
  return (
    <button
      style={{
        ...hpStyles.card,
        borderColor: hover ? "rgba(212,168,83,0.55)" : "var(--line)",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        boxShadow: hover ? "0 18px 40px rgba(0,0,0,0.45)" : "0 0 0 rgba(0,0,0,0)",
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={onClick}
    >
      <div style={hpStyles.cardCover}>
        <div
          style={{
            ...hpStyles.cardCoverImg,
            backgroundImage: `url(${story.cover_url})`,
            transform: hover ? "scale(1.04)" : "scale(1)",
          }}
        />
        <div style={hpStyles.cardCoverDarken} />
        <div style={hpStyles.cardCoverGrad} />
        <span style={hpStyles.cardCoverTag}>{story.theme}</span>
        {mine && <span style={hpStyles.cardMineTag}>你写的</span>}
        <h3 style={hpStyles.cardCoverTitle}>{story.title}</h3>
      </div>
      <div style={hpStyles.cardBody}>
        <p style={hpStyles.cardLede}>{story.lede}</p>
        {hasProof && (
          <div style={hpStyles.cardProof}>
            <span style={hpStyles.cardProofNum}>{story.played_count}</span>
            <span> 人玩过</span>
            <span style={hpStyles.cardProofDot}>·</span>
            <span style={hpStyles.cardProofNum}>{story.unique_ending_count}</span>
            <span> 种结局</span>
          </div>
        )}
      </div>
    </button>
  )
}

const hpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)", color: "var(--text)" },
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
  brand: { display: "flex", alignItems: "center", gap: 8 },
  brandDot: { color: "var(--accent)", fontSize: 22, lineHeight: 1, transform: "translateY(-2px)" },
  brandName: { fontFamily: "var(--font-narrative)", fontSize: 18, letterSpacing: "0.01em" },
  headerRight: { display: "flex", alignItems: "center", gap: 14 },

  main: { maxWidth: 1180, margin: "0 auto", padding: "32px 40px 80px" },

  continue: {
    position: "relative",
    borderRadius: "var(--radius-md)",
    overflow: "hidden",
    border: "1px solid rgba(212,168,83,0.32)",
    marginBottom: 56,
  },
  continueBg: {
    position: "absolute",
    inset: 0,
    background:
      "linear-gradient(90deg, rgba(212,168,83,0.14) 0%, rgba(212,168,83,0.04) 50%, rgba(212,168,83,0.0) 100%)",
  },
  continueInner: {
    position: "relative",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "16px 22px",
  },
  continueEyebrow: {
    fontSize: 11,
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    color: "var(--accent)",
    marginBottom: 4,
    fontWeight: 600,
  },
  continueTitle: { fontSize: 15, color: "var(--text)" },
  continueWorld: { fontWeight: 600, fontFamily: "var(--font-narrative)", fontSize: 17 },
  continueDot: { color: "var(--text-faint)", margin: "0 8px" },
  continueAgo: { color: "var(--text-muted)" },

  hero: {
    position: "relative",
    padding: "72px 0 80px",
    minHeight: 360,
    overflow: "hidden",
    marginBottom: 24,
  },
  heroAmbient: {
    position: "absolute",
    right: -40,
    top: -20,
    width: 540,
    height: 480,
    backgroundImage: "url(/webtoons/ui/library_bg.jpg)",
    backgroundSize: "cover",
    backgroundPosition: "center",
    filter: "brightness(0.42) saturate(0.85)",
    WebkitMaskImage:
      "radial-gradient(ellipse at 60% 50%, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.5) 50%, rgba(0,0,0,0) 80%)",
    maskImage: "radial-gradient(ellipse at 60% 50%, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.5) 50%, rgba(0,0,0,0) 80%)",
    pointerEvents: "none",
  },
  heroLeft: { position: "relative", maxWidth: 720 },
  heroTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 60,
    lineHeight: 1.1,
    letterSpacing: "-0.01em",
    fontWeight: 400,
    margin: "0 0 24px",
  },
  heroSub: {
    fontSize: 18,
    lineHeight: 1.6,
    color: "var(--text-muted)",
    margin: "0 0 36px",
    maxWidth: 580,
  },
  heroCtas: { display: "flex", alignItems: "center", gap: 24 },

  storiesSection: { paddingTop: 8 },
  groupHeader: {
    display: "flex",
    alignItems: "flex-end",
    justifyContent: "space-between",
    gap: 24,
    marginBottom: 24,
    paddingBottom: 4,
  },
  groupHeaderLeft: { minWidth: 0 },
  groupHeaderRight: { flexShrink: 0 },
  groupEyebrow: {
    fontSize: 11,
    color: "var(--accent)",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    marginBottom: 8,
    fontWeight: 600,
  },
  groupTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 26,
    fontWeight: 500,
    margin: "0 0 6px",
    letterSpacing: "0.005em",
  },
  groupSub: {
    fontSize: 13,
    color: "var(--text-muted)",
  },

  searchWrap: {
    position: "relative",
    display: "flex",
    alignItems: "center",
  },
  searchIcon: {
    position: "absolute",
    left: 14,
    color: "var(--text-faint)",
    pointerEvents: "none",
  },
  search: {
    width: 280,
    height: 38,
    padding: "0 36px 0 38px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
    color: "var(--text)",
    fontSize: 13,
    outline: "none",
    transition: "border-color 160ms",
  },
  searchClear: {
    position: "absolute",
    right: 12,
    width: 22,
    height: 22,
    borderRadius: 999,
    color: "var(--text-faint)",
    fontSize: 14,
    lineHeight: 1,
    background: "transparent",
    border: "none",
  },

  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 20,
  },
  card: {
    textAlign: "left",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    overflow: "hidden",
    transition: "border-color 240ms ease, transform 240ms ease, box-shadow 240ms ease",
    padding: 0,
    color: "var(--text)",
    display: "flex",
    flexDirection: "column",
  },
  cardCover: {
    position: "relative",
    aspectRatio: "4/5",
    overflow: "hidden",
    background: "#11121a",
  },
  cardCoverImg: {
    position: "absolute",
    inset: 0,
    backgroundSize: "cover",
    backgroundPosition: "center",
    transition: "transform 320ms ease",
    filter: "brightness(0.78) saturate(0.95)",
  },
  cardCoverDarken: {
    position: "absolute",
    inset: 0,
    background: "rgba(12,12,16,0.18)",
  },
  cardCoverGrad: {
    position: "absolute",
    inset: 0,
    background: "linear-gradient(to bottom, rgba(12,12,16,0) 50%, rgba(12,12,16,0.55) 75%, rgba(12,12,16,0.95) 100%)",
  },
  cardCoverTag: {
    position: "absolute",
    left: 12,
    top: 12,
    padding: "4px 9px",
    background: "rgba(12,12,16,0.78)",
    border: "1px solid rgba(212,168,83,0.5)",
    color: "var(--accent)",
    fontSize: 9,
    fontWeight: 600,
    letterSpacing: "0.18em",
    borderRadius: 999,
    textTransform: "uppercase",
  },
  cardMineTag: {
    position: "absolute",
    right: 12,
    top: 12,
    padding: "4px 9px",
    background: "var(--accent)",
    color: "var(--bg)",
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: "0.16em",
    borderRadius: 999,
    textTransform: "uppercase",
  },
  cardCoverTitle: {
    position: "absolute",
    left: 16,
    right: 16,
    bottom: 14,
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    fontWeight: 500,
    lineHeight: 1.2,
    margin: 0,
    color: "var(--text)",
    letterSpacing: "0.005em",
  },
  cardBody: {
    padding: "14px 18px 18px",
    flex: 1,
    display: "flex",
    flexDirection: "column",
    justifyContent: "space-between",
    gap: 10,
  },
  cardLede: {
    fontSize: 13.5,
    lineHeight: 1.5,
    color: "var(--text-muted)",
    margin: 0,
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  },
  cardProof: {
    fontSize: 12,
    color: "var(--text-faint)",
    fontVariantNumeric: "tabular-nums",
  },
  cardProofNum: {
    color: "var(--accent)",
    fontWeight: 600,
  },
  cardProofDot: {
    margin: "0 6px",
    color: "var(--text-faint)",
  },

  empty: {
    padding: "56px 24px",
    background: "var(--bg-elev)",
    border: "1px dashed var(--line-strong)",
    borderRadius: "var(--radius-md)",
    textAlign: "center",
  },
  emptyTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    color: "var(--text)",
    marginBottom: 8,
  },
  emptySub: {
    fontSize: 13,
    color: "var(--text-muted)",
  },
  emptyLink: {
    background: "none",
    color: "var(--accent)",
    borderBottom: "1px dashed rgba(212,168,83,0.4)",
    padding: 0,
    fontSize: 13,
  },
  error: {
    padding: "14px 18px",
    background: "rgba(224,122,95,0.08)",
    border: "1px solid rgba(224,122,95,0.32)",
    color: "var(--warn)",
    borderRadius: "var(--radius-md)",
    marginBottom: 24,
    fontSize: 13,
  },

  footer: {
    marginTop: 80,
    padding: "24px 0",
    borderTop: "1px solid var(--line)",
    display: "flex",
    justifyContent: "space-between",
    fontSize: 12,
  },

  toast: {
    position: "fixed",
    left: "50%",
    bottom: 32,
    transform: "translateX(-50%)",
    padding: "10px 18px",
    background: "rgba(15,15,20,0.96)",
    border: "1px solid var(--line-strong)",
    borderRadius: 999,
    fontSize: 13,
    color: "var(--warn)",
    zIndex: 60,
  },
}
