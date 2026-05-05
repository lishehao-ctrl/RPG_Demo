import { type CSSProperties, useEffect, useState } from "react"
import type {
  NarrativeSessionSummary,
  NarrativeTemplateSummary,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"

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
        setError(err instanceof Error ? err.message : "广场加载失败。")
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
          <h1 style={hpStyles.heroTitle}>
            一句话起头，
            <br />
            AI 给你一整个故事。
          </h1>
          <p style={hpStyles.heroSub}>
            写下任何一个人物关系的瞬间——
            豪门家宴、办公室博弈、初恋重逢、深夜电话——
            AI 立刻为你搭起场景、人物、第一个戏剧时刻，然后你接手往下玩。
          </p>
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

        {/* Continue playing (my sessions) — only when signed in and has sessions */}
        {!auth.isAnonymous && mySessions && mySessions.length > 0 ? (
          <section style={hpStyles.section}>
            <SectionHeader title="继续未完成的故事" />
            <div style={hpStyles.sessionRow}>
              {mySessions.slice(0, 6).map((s) => (
                <SessionCard
                  key={s.session_id}
                  session={s}
                  onClick={() => onOpenPlay(s.session_id)}
                />
              ))}
            </div>
          </section>
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

function SessionCard({
  session,
  onClick,
}: {
  session: NarrativeSessionSummary
  onClick: () => void
}) {
  return (
    <button style={hpStyles.sessionCard} onClick={onClick} type="button">
      <div style={hpStyles.sessionTitle}>{session.template_title}</div>
      <div style={hpStyles.sessionMeta}>
        第 {session.turn_count + 1} 段 · {formatRelative(session.last_active_at)}
      </div>
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
  return (
    <button style={hpStyles.card} onClick={onClick} type="button">
      <div style={hpStyles.cardTitle}>{template.title}</div>
      <div style={hpStyles.cardSeed}>"{template.seed}"</div>
      <div style={hpStyles.cardCast}>
        {template.cast.map((c) => c.display_name).join(" · ")}
      </div>
      <div style={hpStyles.cardFooter}>
        <span style={hpStyles.cardBadge}>{visibilityLabel(template.visibility)}</span>
        <span style={hpStyles.cardPlays}>· 已玩 {template.play_count} 局</span>
        {template.is_owner ? (
          <span style={hpStyles.cardOwnerBadge}>我创建的</span>
        ) : null}
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

  hero: { textAlign: "center", padding: "32px 0 56px" },
  heroTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 48,
    lineHeight: 1.15,
    fontWeight: 400,
    margin: "0 0 20px",
  },
  heroSub: {
    fontSize: 16,
    lineHeight: 1.65,
    color: "var(--text-muted)",
    maxWidth: 600,
    margin: "0 auto 32px",
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

  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
    gap: 16,
  },
  card: {
    textAlign: "left",
    padding: "20px 22px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-md)",
    cursor: "pointer",
    transition: "all 180ms",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    minHeight: 180,
  },
  cardTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 18,
    lineHeight: 1.3,
    color: "var(--text)",
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
    color: "var(--text-faint)",
    marginTop: "auto",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
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
}
