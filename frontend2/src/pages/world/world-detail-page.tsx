import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react"
import type { PublishedStoryDetailResponse, StoryVisibility } from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { HeaderUserMenu } from "../../shared/ui/header-user-menu"
import { localizeTheme, shellCover } from "../../shared/lib/format"

type EndingRow = {
  endingId: string
  label: string
  count: number
  isOther?: boolean
}

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
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [toast, setToast] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [visibility, setVisibility] = useState<StoryVisibility>("unlisted")

  useEffect(() => {
    let active = true
    setLoading(true)
    setLoadError(null)
    const load = async () => {
      try {
        const response = await api.getStory(storyId)
        if (active) {
          setDetail(response)
          setVisibility(response.story.visibility)
        }
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

  const story = detail?.story
  const isAuthor = story?.viewer_can_manage === true
  const playCount = story?.play_count ?? 0
  const hasPlays = playCount > 0
  const endingDistribution = story?.ending_distribution ?? {}
  // viewer-has-played heuristic: backend doesn't expose this yet, so default to false.
  // (Author always sees endings; non-author sees only if they've played.)
  const viewerHasPlayedBefore = false

  const endingsToShow = useMemo<EndingRow[]>(() => {
    const list: EndingRow[] = Object.entries(endingDistribution)
      .map(([endingId, count]) => ({ endingId, label: endingId, count: Number(count) }))
      .sort((a, b) => b.count - a.count)
    if (list.length <= 5) return list
    const head = list.slice(0, 4)
    const tail = list.slice(4)
    const tailSum = tail.reduce((s, e) => s + e.count, 0)
    return [...head, { endingId: "_other", label: `其它 · ${tail.length}`, count: tailSum, isOther: true }]
  }, [endingDistribution])

  const showEndings = hasPlays && (isAuthor || viewerHasPlayedBefore) && endingsToShow.length > 0
  const maxEndingCount = endingsToShow.reduce((m, e) => Math.max(m, e.count), 0) || 1

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

  const handleCopy = async () => {
    const url = `${window.location.origin}${window.location.pathname}#/world/${storyId}`
    try {
      await navigator.clipboard.writeText(url)
    } catch {
      window.prompt("复制这个链接发给朋友：", url)
    }
    setToast(true)
    window.setTimeout(() => setToast(false), 2000)
  }

  const handleVisibility = async (next: StoryVisibility) => {
    if (next === visibility) return
    setVisibility(next)
    try {
      await api.updateStoryVisibility(storyId, { visibility: next })
      const refreshed = await api.getStory(storyId)
      setDetail(refreshed)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "切换可见性失败")
    }
  }

  const handleDelete = async () => {
    setConfirmingDelete(false)
    try {
      await api.deleteStory(storyId)
      onBackHome()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除失败")
    }
  }

  if (loading) {
    return (
      <div style={wdStyles.page}>
        <WorldHeader isAuthor={false} authorHandle={null} onCreate={onOpenCreate} authedUser={auth.user?.display_name} />
        <main style={wdStyles.main}>
          <div style={wdStyles.loading}>正在拉取这个 world…</div>
        </main>
      </div>
    )
  }

  if (!story || !detail) {
    return (
      <div style={wdStyles.page}>
        <WorldHeader isAuthor={false} authorHandle={null} onCreate={onOpenCreate} authedUser={auth.user?.display_name} />
        <main style={wdStyles.main}>
          <div style={wdStyles.empty}>
            <div style={wdStyles.emptyTitle}>{loadError ?? "找不到这个 world"}</div>
            <button className="ts-btn ts-btn--primary" onClick={onBackHome} style={{ marginTop: 18 }}>
              返回首页
            </button>
          </div>
        </main>
      </div>
    )
  }

  const themeLabel = localizeTheme(story.theme)
  const coverUrl = shellCover(detail.preview?.story_shell_id ?? story.theme ?? null)
  // owner_user_id is not on the public card today; fall back to current user's display_name when isAuthor.
  const authorHandle = isAuthor ? auth.user?.display_name ?? "你" : "unknown"
  const shareTail = `tinystories.app/w/${storyId}`

  return (
    <div style={wdStyles.page}>
      <WorldHeader
        isAuthor={isAuthor}
        authorHandle={authorHandle}
        onCreate={onOpenCreate}
        authedUser={auth.user?.display_name}
      />

      <main style={wdStyles.main}>
        <section style={wdStyles.hero}>
          <div style={wdStyles.heroLeft}>
            <div style={wdStyles.tagRow}>
              <span className="ts-tag ts-tag--muted">{themeLabel}</span>
              <span className="ts-tag ts-tag--muted">{story.npc_count} 个角色</span>
              <span className="ts-tag ts-tag--muted">{story.beat_count} 幕</span>
            </div>

            <h1 style={wdStyles.title}>{story.title}</h1>

            <div style={wdStyles.author}>
              作者：<span style={wdStyles.authorHandle}>@{authorHandle}</span>
            </div>

            <div style={wdStyles.decisionBlock}>
              {hasPlays ? (
                <div style={wdStyles.proof}>
                  <span style={wdStyles.proofNum}>{playCount}</span>
                  <span> 人玩过 </span>
                  <span style={wdStyles.proofSep}>·</span>
                  <span style={wdStyles.proofNum}>{Object.keys(endingDistribution).length}</span>
                  <span> 种结局</span>
                </div>
              ) : (
                <div style={wdStyles.proofEmpty}>还没有人玩过这个 world —— 你可以是第一个</div>
              )}

              <div style={wdStyles.ctaRow}>
                <button
                  className="ts-btn ts-btn--primary ts-btn--lg"
                  style={{ minWidth: 132, opacity: starting ? 0.6 : 1, pointerEvents: starting ? "none" : "auto" }}
                  onClick={() => void handleStart()}
                >
                  {starting ? "进入中…" : "开玩"}
                </button>
                <button className="ts-btn ts-btn--ghost" onClick={() => void handleCopy()}>
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    style={{ marginRight: 2 }}
                  >
                    <path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1" strokeLinecap="round" />
                    <path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1" strokeLinecap="round" />
                  </svg>
                  复制分享链接
                </button>
              </div>
              <div
                style={{
                  ...wdStyles.shareUrl,
                  background: toast ? "rgba(212,168,83,0.18)" : "transparent",
                  color: toast ? "var(--accent)" : "var(--text-faint)",
                  transition: "background 400ms ease, color 400ms ease",
                }}
              >
                {shareTail}
              </div>
              {actionError ? <div style={wdStyles.error}>{actionError}</div> : null}
            </div>
          </div>

          <CoverCard coverUrl={coverUrl} />
        </section>

        {isAuthor && (
          <section style={wdStyles.authorPanel}>
            <div style={wdStyles.panelHeader}>
              <div style={wdStyles.panelEyebrow}>仅作者可见</div>
              <h3 style={wdStyles.panelTitle}>谁能看到这个 world</h3>
              <p style={wdStyles.panelSub}>
                <strong style={wdStyles.panelSubStrong}>私密</strong>=只有你能玩；
                <strong style={wdStyles.panelSubStrong}>仅链接</strong>=朋友点链接能玩，但不出现在首页；
                <strong style={wdStyles.panelSubStrong}>公开</strong>=出现在首页推荐池。
              </p>
            </div>

            <div style={wdStyles.segmented}>
              {(
                [
                  { id: "private", label: "私密" },
                  { id: "unlisted", label: "仅链接" },
                  { id: "public", label: "公开" },
                ] as const
              ).map((v) => (
                <button
                  key={v.id}
                  onClick={() => void handleVisibility(v.id)}
                  style={{
                    ...wdStyles.segBtn,
                    ...(visibility === v.id ? wdStyles.segBtnActive : {}),
                  }}
                >
                  {v.label}
                </button>
              ))}
            </div>

            <div style={wdStyles.panelDanger}>
              <button style={wdStyles.deleteBtn} onClick={() => setConfirmingDelete(true)}>
                删除这个 world
              </button>
            </div>
          </section>
        )}

        <section style={wdStyles.section}>
          <div style={wdStyles.eyebrow}>故事简介</div>
          <p style={wdStyles.premise}>{story.premise}</p>
        </section>

        {showEndings && (
          <section style={wdStyles.section}>
            <div style={wdStyles.eyebrowRow}>
              <div style={wdStyles.eyebrow}>别人玩出过什么结局</div>
              <div style={wdStyles.eyebrowMeta}>
                {isAuthor ? "仅作者可见" : "你玩过这个 world，所以可以看见"}
              </div>
            </div>
            <div style={wdStyles.endings}>
              {endingsToShow.map((e) => {
                const w = (e.count / maxEndingCount) * 100
                return (
                  <div key={e.endingId} style={wdStyles.endingRow}>
                    <div
                      style={{
                        ...wdStyles.endingLabel,
                        color: e.isOther ? "var(--text-faint)" : "var(--text)",
                      }}
                    >
                      {e.label}
                    </div>
                    <div style={wdStyles.endingBarTrack}>
                      <div
                        style={{
                          ...wdStyles.endingBarFill,
                          width: `${w}%`,
                          background: e.isOther ? "rgba(212,168,83,0.22)" : "var(--accent)",
                        }}
                      />
                    </div>
                    <div style={wdStyles.endingCount}>{e.count}</div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* TODO: "其它 worlds by 同一作者" — backend's listStories doesn't yet take an
            owner_user_id filter, so we omit this section until that lands. */}

        <footer style={wdStyles.footer}>
          <span style={{ color: "var(--text-faint)" }}>· Tiny Stories</span>
          <span style={{ color: "var(--text-faint)" }}>分享一个 world，让朋友玩出自己的故事。</span>
        </footer>
      </main>

      <div
        style={{
          ...wdStyles.toast,
          opacity: toast ? 1 : 0,
          transform: `translate(-50%, ${toast ? 0 : 8}px)`,
        }}
      >
        已复制
      </div>

      {confirmingDelete && (
        <DeleteConfirmDialog
          worldTitle={story.title}
          onCancel={() => setConfirmingDelete(false)}
          onConfirm={() => void handleDelete()}
        />
      )}
    </div>
  )
}

function WorldHeader({
  isAuthor,
  authorHandle,
  onCreate,
  authedUser,
}: {
  isAuthor: boolean
  authorHandle: string | null
  onCreate: () => void
  authedUser?: string
}) {
  return (
    <header style={wdStyles.header}>
      <div style={wdStyles.brand}>
        <span style={wdStyles.brandDot}>·</span>
        <span style={wdStyles.brandName}>Tiny Stories</span>
      </div>
      <div style={wdStyles.headerRight}>
        {isAuthor ? (
          <HeaderUserMenu user={{ name: authedUser ?? authorHandle ?? "你", world_count: 0 }} />
        ) : (
          <>
            <button className="ts-btn ts-btn--ghost" onClick={onCreate}>
              写一个 world
            </button>
            <HeaderUserMenu user={authedUser ? { name: authedUser } : null} />
          </>
        )}
      </div>
    </header>
  )
}

function CoverCard({ coverUrl }: { coverUrl: string }) {
  return (
    <div style={wdStyles.coverWrap}>
      <div
        style={{
          ...wdStyles.coverImg,
          backgroundImage: `url(${coverUrl})`,
        }}
      />
      <div style={wdStyles.coverDarken} />
      <div style={wdStyles.coverRadial} />
      <div style={wdStyles.coverEdges} />
      <div style={wdStyles.coverTag}>WORLD</div>
    </div>
  )
}

function DeleteConfirmDialog({
  worldTitle,
  onCancel,
  onConfirm,
}: {
  worldTitle: string
  onCancel: () => void
  onConfirm: () => void
}): ReactNode {
  return (
    <div style={wdStyles.modalScrim} onClick={onCancel}>
      <div style={wdStyles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={wdStyles.modalEyebrow}>这个动作不可撤销</div>
        <h3 style={wdStyles.modalTitle}>删除《{worldTitle}》？</h3>
        <p style={wdStyles.modalBody}>已有玩家走过这个 world —— 删除之后，他们的回放链接也会失效。</p>
        <div style={wdStyles.modalActions}>
          <button className="ts-btn ts-btn--ghost" onClick={onCancel}>
            取消
          </button>
          <button style={wdStyles.modalDelete} onClick={onConfirm}>
            删除
          </button>
        </div>
      </div>
    </div>
  )
}

const wdStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)", position: "relative", color: "var(--text)" },

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
  headerRight: { display: "flex", alignItems: "center", gap: 12 },

  main: { maxWidth: 1080, margin: "0 auto", padding: "56px 40px 80px" },

  loading: { padding: "60px 0", color: "var(--text-muted)", textAlign: "center" },

  hero: {
    display: "grid",
    gridTemplateColumns: "1fr 0.72fr",
    gap: 56,
    alignItems: "center",
    marginBottom: 64,
  },
  heroLeft: { minWidth: 0 },
  tagRow: { display: "flex", gap: 6, marginBottom: 22, flexWrap: "wrap" },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 42,
    lineHeight: 1.12,
    fontWeight: 400,
    margin: "0 0 14px",
    letterSpacing: "-0.005em",
  },
  author: { fontSize: 14, color: "var(--text-muted)", marginBottom: 28 },
  authorHandle: { color: "var(--text)", borderBottom: "1px dashed var(--line-strong)", paddingBottom: 1 },

  decisionBlock: { display: "flex", flexDirection: "column", gap: 10 },
  proof: {
    fontSize: 15,
    color: "var(--text)",
    lineHeight: 1.5,
  },
  proofNum: {
    color: "var(--accent)",
    fontWeight: 600,
    fontVariantNumeric: "tabular-nums",
    fontSize: 16,
  },
  proofSep: { color: "var(--text-faint)", margin: "0 8px" },
  proofEmpty: {
    fontSize: 14,
    color: "var(--text-muted)",
    lineHeight: 1.5,
    fontStyle: "italic",
  },
  ctaRow: { display: "flex", alignItems: "center", gap: 10 },
  shareUrl: {
    display: "inline-block",
    fontSize: 11,
    color: "var(--text-faint)",
    fontFamily: "var(--font-ui)",
    letterSpacing: "0.04em",
    marginTop: 2,
    padding: "3px 8px",
    marginLeft: -8,
    borderRadius: 6,
    alignSelf: "flex-start",
  },
  error: {
    marginTop: 8,
    fontSize: 12,
    color: "var(--warn)",
  },

  coverWrap: {
    position: "relative",
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
  coverTag: {
    position: "absolute",
    left: 16,
    bottom: 16,
    padding: "5px 10px",
    background: "rgba(12,12,16,0.78)",
    border: "1px solid rgba(212,168,83,0.45)",
    color: "var(--accent)",
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "0.18em",
    borderRadius: 999,
  },

  authorPanel: {
    marginBottom: 56,
    padding: "24px 26px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
  },
  panelHeader: { marginBottom: 16 },
  panelEyebrow: {
    fontSize: 11,
    color: "var(--accent)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 8,
  },
  panelTitle: { fontFamily: "var(--font-narrative)", fontSize: 20, fontWeight: 500, margin: "0 0 8px" },
  panelSub: { fontSize: 13, color: "var(--text-muted)", lineHeight: 1.65, margin: 0 },
  panelSubStrong: { color: "var(--text)", fontWeight: 500 },

  segmented: {
    display: "inline-flex",
    background: "var(--bg-elev-2)",
    border: "1px solid var(--line)",
    borderRadius: 999,
    padding: 4,
    gap: 0,
    marginTop: 4,
  },
  segBtn: {
    height: 34,
    padding: "0 18px",
    borderRadius: 999,
    fontSize: 13,
    color: "var(--text-muted)",
    transition: "all 160ms",
  },
  segBtnActive: {
    background: "var(--accent)",
    color: "#1a1408",
    fontWeight: 600,
  },
  panelDanger: {
    marginTop: 22,
    paddingTop: 18,
    borderTop: "1px solid var(--line)",
  },
  deleteBtn: {
    height: 36,
    padding: "0 16px",
    borderRadius: 8,
    color: "var(--warn)",
    fontSize: 13,
    border: "1px solid rgba(224,122,95,0.32)",
    background: "transparent",
    transition: "all 160ms",
  },

  section: { marginBottom: 56 },
  eyebrow: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 16,
  },
  eyebrowRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    marginBottom: 16,
  },
  eyebrowMeta: { fontSize: 11, color: "var(--text-faint)" },
  premise: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.75,
    color: "var(--text)",
    margin: 0,
    maxWidth: 720,
  },

  endings: { display: "flex", flexDirection: "column", gap: 10, maxWidth: 720 },
  endingRow: {
    display: "grid",
    gridTemplateColumns: "150px 1fr 32px",
    alignItems: "center",
    gap: 16,
  },
  endingLabel: {
    fontFamily: "var(--font-narrative)",
    fontSize: 15,
  },
  endingBarTrack: {
    height: 4,
    background: "rgba(255,255,255,0.05)",
    borderRadius: 999,
    overflow: "hidden",
  },
  endingBarFill: { height: "100%", borderRadius: 999, transition: "width 320ms ease" },
  endingCount: {
    fontSize: 12,
    color: "var(--text-muted)",
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
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
  },

  footer: {
    marginTop: 32,
    paddingTop: 24,
    borderTop: "1px solid var(--line)",
    display: "flex",
    justifyContent: "space-between",
    fontSize: 12,
  },

  toast: {
    position: "fixed",
    left: "50%",
    bottom: 32,
    padding: "10px 18px",
    background: "rgba(15,15,20,0.96)",
    border: "1px solid var(--line-strong)",
    borderRadius: 999,
    fontSize: 13,
    color: "var(--text)",
    transition: "opacity 220ms ease, transform 220ms ease",
    pointerEvents: "none",
    boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
  },

  modalScrim: {
    position: "fixed",
    inset: 0,
    zIndex: 50,
    background: "rgba(8,8,12,0.66)",
    backdropFilter: "blur(6px)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  modal: {
    width: 420,
    background: "var(--bg-elev)",
    border: "1px solid var(--line-strong)",
    borderRadius: "var(--radius-md)",
    padding: "26px 28px",
    boxShadow: "0 30px 80px rgba(0,0,0,0.5)",
  },
  modalEyebrow: {
    fontSize: 11,
    color: "var(--warn)",
    letterSpacing: "0.16em",
    textTransform: "uppercase",
    marginBottom: 10,
  },
  modalTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    fontWeight: 500,
    margin: "0 0 12px",
  },
  modalBody: {
    fontSize: 14,
    color: "var(--text-muted)",
    lineHeight: 1.6,
    margin: "0 0 22px",
  },
  modalActions: { display: "flex", justifyContent: "flex-end", gap: 10 },
  modalDelete: {
    height: 40,
    padding: "0 18px",
    borderRadius: 10,
    background: "var(--warn)",
    color: "#1a0a05",
    fontSize: 14,
    fontWeight: 600,
    transition: "all 160ms",
  },
}
