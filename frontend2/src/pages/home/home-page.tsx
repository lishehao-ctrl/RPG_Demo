import { type CSSProperties, useEffect, useState } from "react"
import type {
  NarrativeSessionSummary,
  NarrativeTemplateSummary,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { PAGE_BG, getCoverForTemplate } from "../../shared/lib/webtoon-assets"
import { friendlyError } from "../../shared/lib/friendly-error"

type Tab = "plaza" | "my-templates"

export function HomePage({
  onOpenCreate,
  onOpenTemplate,
  onOpenPlay,
}: {
  onOpenCreate: () => void
  onOpenTemplate: (templateId: string) => void
  onOpenPlay: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [tab, setTab] = useState<Tab>("plaza")
  const [publicTemplates, setPublicTemplates] = useState<NarrativeTemplateSummary[] | null>(null)
  const [myTemplates, setMyTemplates] = useState<NarrativeTemplateSummary[] | null>(null)
  const [mySessions, setMySessions] = useState<NarrativeSessionSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .listPublicNarrativeTemplates()
      .then((res) => {
        if (cancelled) return
        setPublicTemplates(res.items)
      })
      .catch((err) => {
        if (cancelled) return
        setError(friendlyError(err, "广场加载失败。"))
      })
    return () => {
      cancelled = true
    }
  }, [api])

  useEffect(() => {
    if (auth.loading || auth.isAnonymous) return
    let cancelled = false
    api
      .listMyNarrativeSessions()
      .then((res) => {
        if (cancelled) return
        setMySessions(res.items)
      })
      .catch(() => {
        if (cancelled) return
        setMySessions([])
      })
    api
      .listMyNarrativeTemplates()
      .then((res) => {
        if (cancelled) return
        setMyTemplates(res.items)
      })
      .catch(() => {
        if (cancelled) return
        setMyTemplates([])
      })
    return () => {
      cancelled = true
    }
  }, [api, auth.loading, auth.isAnonymous])

  return (
    <div style={hpStyles.page}>
      <Header onHome={() => {}} onCreate={onOpenCreate} />

      <main style={hpStyles.main}>
        <section style={hpStyles.hero}>
          <div style={hpStyles.heroTagline}>互动短剧 · 你来决定</div>
          <h1 style={hpStyles.heroTitle}>
            一句话起头，
            <br />
            AI 给你一整集短剧。
          </h1>
          <p style={hpStyles.heroSub}>
            15 分钟一局 · 朋友们玩同一个开场，看谁玩出什么结局。
          </p>
          <ul style={hpStyles.heroBullets}>
            <li><span style={hpStyles.heroBulletDot}>·</span>写一个戏剧瞬间，AI 立刻搭起场景、人物、第一段</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>每回合 300 字叙述 + 选项 / 自由输入</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>右下角私聊"局外人朋友"——TA 不替你做决定，会陪你想清楚</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>结局可分享，可看朋友走出什么版本</li>
          </ul>
          <div style={hpStyles.heroActions}>
            <button
              className="ts-btn ts-btn--primary ts-btn--lg"
              onClick={onOpenCreate}
              type="button"
            >
              写一个新故事 →
            </button>
          </div>
        </section>

        {/* My sessions split into in-progress + completed groups. Only
            shown when signed in and at least one exists. */}
        {!auth.isAnonymous && mySessions && mySessions.length > 0 ? (
          <MySessionsSection sessions={mySessions} onOpenPlay={onOpenPlay} />
        ) : null}

        <section style={hpStyles.section}>
          <div style={hpStyles.tabs}>
            <button
              style={{ ...hpStyles.tab, ...(tab === "plaza" ? hpStyles.tabActive : {}) }}
              onClick={() => setTab("plaza")}
              type="button"
            >
              广场
            </button>
            {!auth.isAnonymous ? (
              <button
                style={{
                  ...hpStyles.tab,
                  ...(tab === "my-templates" ? hpStyles.tabActive : {}),
                }}
                onClick={() => setTab("my-templates")}
                type="button"
              >
                我创建的
              </button>
            ) : null}
          </div>

          {tab === "plaza" ? (
            <TemplateGrid
              templates={publicTemplates}
              error={error}
              emptyText="还没有公开作品。写一个让所有人来玩？"
              onOpenTemplate={onOpenTemplate}
            />
          ) : (
            <TemplateGrid
              templates={myTemplates}
              error={null}
              emptyText="你还没有创建过故事。"
              onOpenTemplate={onOpenTemplate}
            />
          )}
        </section>

        <footer style={hpStyles.footer}>
          <span style={hpStyles.footerBrand}>Tiny Stories</span>
          <span style={hpStyles.footerSep}>·</span>
          <a
            href="#/about"
            style={hpStyles.footerLink}
            onClick={(e) => {
              e.preventDefault()
              window.location.hash = "#/about"
            }}
          >
            关于 / 隐私
          </a>
          <span style={hpStyles.footerSep}>·</span>
          <a
            href="mailto:hello@tinystories.app"
            style={hpStyles.footerLink}
          >
            联系我们
          </a>
        </footer>
      </main>
    </div>
  )
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div style={hpStyles.sectionHeader}>
      <h2 style={hpStyles.sectionTitle}>{title}</h2>
    </div>
  )
}

function MySessionsSection({
  sessions,
  onOpenPlay,
}: {
  sessions: NarrativeSessionSummary[]
  onOpenPlay: (sessionId: string) => void
}) {
  // Split: in-progress (no ending) above, completed (has ending) below.
  const inProgress = sessions.filter((s) => !s.ending_label)
  const completed = sessions.filter((s) => Boolean(s.ending_label))
  return (
    <>
      {inProgress.length > 0 ? (
        <section style={hpStyles.section}>
          <SectionHeader title="继续未完成的故事" />
          <div style={hpStyles.sessionRow}>
            {inProgress.slice(0, 6).map((s) => (
              <SessionCard
                key={s.session_id}
                session={s}
                onClick={() => onOpenPlay(s.session_id)}
              />
            ))}
          </div>
        </section>
      ) : null}
      {completed.length > 0 ? (
        <section style={hpStyles.section}>
          <SectionHeader title="我玩完的故事" />
          <div style={hpStyles.sessionRow}>
            {completed.slice(0, 6).map((s) => (
              <SessionCard
                key={s.session_id}
                session={s}
                onClick={() => onOpenPlay(s.session_id)}
              />
            ))}
          </div>
        </section>
      ) : null}
    </>
  )
}

function SessionCard({
  session,
  onClick,
}: {
  session: NarrativeSessionSummary
  onClick: () => void
}) {
  const completed = Boolean(session.ending_label)
  return (
    <button style={hpStyles.sessionCard} onClick={onClick} type="button">
      <div style={hpStyles.sessionTitle}>{session.template_title}</div>
      {completed ? (
        <>
          <div style={hpStyles.sessionEndingLine}>
            <span style={hpStyles.sessionEndingLabel}>{session.ending_label}</span>
            <span style={hpStyles.sessionEndingSubtitle}>
              「{session.ending_subtitle}」
            </span>
          </div>
          <div style={hpStyles.sessionMeta}>
            完结 · {formatRelative(session.last_active_at)}
          </div>
        </>
      ) : (
        <div style={hpStyles.sessionMeta}>
          第 {session.turn_count + 1} / {session.turn_budget} 段 ·{" "}
          {formatRelative(session.last_active_at)}
        </div>
      )}
    </button>
  )
}

function TemplateGrid({
  templates,
  error,
  emptyText,
  onOpenTemplate,
}: {
  templates: NarrativeTemplateSummary[] | null
  error: string | null
  emptyText: string
  onOpenTemplate: (templateId: string) => void
}) {
  if (error) {
    return <div style={hpStyles.errorBox}>{error}</div>
  }
  if (!templates) {
    return <div style={hpStyles.loading}>加载中…</div>
  }
  if (templates.length === 0) {
    return <div style={hpStyles.empty}>{emptyText}</div>
  }
  return (
    <div style={hpStyles.grid}>
      {templates.map((t) => (
        <TemplateCard
          key={t.template_id}
          template={t}
          onClick={() => onOpenTemplate(t.template_id)}
        />
      ))}
    </div>
  )
}

function TemplateCard({
  template,
  onClick,
}: {
  template: NarrativeTemplateSummary
  onClick: () => void
}) {
  const cover = getCoverForTemplate(template)
  return (
    <button style={hpStyles.card} onClick={onClick} type="button">
      <div
        style={{
          ...hpStyles.cardCover,
          backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0) 30%, rgba(20,16,12,0.78) 100%), url(${cover})`,
        }}
      >
        <div style={hpStyles.cardCoverFade}>
          <div style={hpStyles.cardTitle}>{template.title}</div>
          <div style={hpStyles.cardCast}>
            {template.cast.map((c) => c.display_name).join(" · ")}
          </div>
        </div>
      </div>
      <div style={hpStyles.cardBody}>
        <div style={hpStyles.cardSeed}>"{template.seed}"</div>
        <div style={hpStyles.cardFooter}>
          <span style={hpStyles.cardBadge}>{visibilityLabel(template.visibility)}</span>
          <span style={hpStyles.cardPlays}>· 已玩 {template.play_count} 局</span>
          {template.is_owner ? (
            <span style={hpStyles.cardOwnerBadge}>我创建的</span>
          ) : null}
        </div>
      </div>
    </button>
  )
}

function visibilityLabel(v: NarrativeTemplateSummary["visibility"]): string {
  if (v === "public") return "公开"
  if (v === "unlisted") return "凭链接"
  return "只有我"
}

function formatRelative(isoString: string): string {
  const date = new Date(isoString)
  const diffMs = Date.now() - date.getTime()
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return date.toLocaleDateString()
}

const hpStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  main: { maxWidth: 1100, margin: "0 auto", padding: "48px 32px 80px" },

  hero: {
    position: "relative",
    textAlign: "center",
    padding: "92px 32px 96px",
    borderRadius: "var(--radius-lg)",
    overflow: "hidden",
    backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.18) 0%, rgba(20,16,12,0.65) 70%, rgba(20,16,12,0.85) 100%), url(${PAGE_BG.splash})`,
    backgroundSize: "cover",
    backgroundPosition: "center 30%",
    color: "white",
    marginBottom: 12,
  },
  heroTagline: {
    display: "inline-block",
    fontSize: 12,
    letterSpacing: "0.18em",
    color: "rgba(255,255,255,0.75)",
    padding: "5px 14px",
    border: "1px solid rgba(255,255,255,0.22)",
    borderRadius: 999,
    marginBottom: 18,
    backdropFilter: "blur(6px)",
  },
  heroTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 52,
    lineHeight: 1.12,
    fontWeight: 400,
    margin: "0 0 18px",
    color: "white",
    textShadow: "0 2px 24px rgba(0,0,0,0.4)",
  },
  heroSub: {
    fontSize: 17,
    lineHeight: 1.6,
    color: "rgba(255,255,255,0.92)",
    maxWidth: 600,
    margin: "0 auto 28px",
    fontWeight: 500,
  },
  heroBullets: {
    listStyle: "none",
    padding: 0,
    margin: "0 auto 32px",
    maxWidth: 540,
    textAlign: "left",
    display: "inline-flex",
    flexDirection: "column",
    gap: 8,
    fontSize: 14,
    lineHeight: 1.55,
    color: "rgba(255,255,255,0.78)",
  },
  heroBulletDot: {
    color: "var(--accent)",
    marginRight: 8,
    fontWeight: 600,
  },
  heroActions: { display: "flex", justifyContent: "center", gap: 12 },

  section: { marginTop: 56 },
  sectionHeader: { marginBottom: 20 },
  sectionTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 22,
    fontWeight: 500,
    margin: 0,
  },

  tabs: {
    display: "flex",
    gap: 4,
    borderBottom: "1px solid var(--line)",
    marginBottom: 28,
  },
  tab: {
    background: "none",
    border: "none",
    padding: "12px 18px",
    fontSize: 14,
    color: "var(--text-muted)",
    cursor: "pointer",
    borderBottom: "2px solid transparent",
    marginBottom: -1,
  },
  tabActive: {
    color: "var(--text)",
    borderBottomColor: "var(--accent)",
  },

  sessionRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
    gap: 12,
  },
  sessionCard: {
    textAlign: "left",
    padding: "14px 16px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    transition: "all 160ms",
  },
  sessionTitle: {
    fontSize: 14.5,
    fontWeight: 500,
    color: "var(--text)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    display: "-webkit-box",
    WebkitLineClamp: 1,
    WebkitBoxOrient: "vertical",
  },
  sessionMeta: { fontSize: 12, color: "var(--text-faint)", marginTop: 6 },
  sessionEndingLine: {
    display: "flex",
    alignItems: "baseline",
    gap: 6,
    marginTop: 8,
    flexWrap: "wrap",
  },
  sessionEndingLabel: {
    padding: "2px 8px",
    background: "var(--accent-soft)",
    color: "var(--accent)",
    borderRadius: 999,
    fontSize: 11,
    fontWeight: 600,
    whiteSpace: "nowrap",
  },
  sessionEndingSubtitle: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    fontFamily: "var(--font-narrative)",
    fontStyle: "italic",
    overflow: "hidden",
    textOverflow: "ellipsis",
    display: "-webkit-box",
    WebkitLineClamp: 1,
    WebkitBoxOrient: "vertical",
  },

  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 16,
  },
  card: {
    textAlign: "left",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    transition: "all 220ms",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    padding: 0,
  },
  cardCover: {
    height: 168,
    backgroundSize: "cover",
    backgroundPosition: "center",
    display: "flex",
    alignItems: "flex-end",
    padding: 16,
  },
  cardCoverFade: {
    width: "100%",
  },
  cardBody: {
    padding: "14px 16px 16px",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  cardTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.3,
    color: "white",
    textShadow: "0 1px 10px rgba(0,0,0,0.5)",
    overflow: "hidden",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
    marginBottom: 4,
  },
  cardSeed: {
    fontSize: 13,
    color: "var(--text-muted)",
    fontStyle: "italic",
    lineHeight: 1.5,
    overflow: "hidden",
    display: "-webkit-box",
    WebkitLineClamp: 2,
    WebkitBoxOrient: "vertical",
  },
  cardCast: {
    fontSize: 12,
    color: "rgba(255,255,255,0.78)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    textShadow: "0 1px 4px rgba(0,0,0,0.6)",
  },
  cardFooter: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 11,
    color: "var(--text-faint)",
    paddingTop: 10,
    borderTop: "1px dashed var(--line)",
  },
  cardBadge: {
    padding: "3px 8px",
    background: "var(--bg)",
    border: "1px solid var(--line)",
    borderRadius: 999,
  },
  cardPlays: { fontSize: 11 },
  cardOwnerBadge: {
    marginLeft: "auto",
    padding: "3px 8px",
    background: "var(--accent-soft)",
    color: "var(--accent)",
    borderRadius: 999,
    fontSize: 11,
  },

  errorBox: {
    padding: 20,
    background: "rgba(220,80,80,0.08)",
    border: "1px solid rgba(220,80,80,0.25)",
    borderRadius: "var(--radius-md)",
    color: "var(--warn)",
    fontSize: 14,
  },
  loading: { padding: 40, textAlign: "center", color: "var(--text-faint)", fontSize: 14 },
  empty: {
    padding: 40,
    textAlign: "center",
    color: "var(--text-faint)",
    fontSize: 14,
    fontStyle: "italic",
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-md)",
    border: "1px dashed var(--line)",
  },

  footer: {
    marginTop: 80,
    paddingTop: 32,
    borderTop: "1px dashed var(--line)",
    textAlign: "center",
    fontSize: 12,
    color: "var(--text-faint)",
    display: "flex",
    justifyContent: "center",
    gap: 8,
    alignItems: "center",
  },
  footerBrand: { fontFamily: "var(--font-narrative)", color: "var(--text-muted)" },
  footerSep: { color: "var(--line-strong)" },
  footerLink: {
    color: "var(--text-muted)",
    textDecoration: "none",
    cursor: "pointer",
  },
}
