import { type CSSProperties, useEffect, useState } from "react"
import type {
  NarrativeTemplateSummary,
  NarrativeTemplateVisibility,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"

export function TemplateDetailPage({
  templateId,
  onBackHome,
  onOpenCreate,
  onSessionStarted,
}: {
  templateId: string
  onBackHome: () => void
  onOpenCreate: () => void
  onSessionStarted: (sessionId: string) => void
}) {
  const api = useApi()
  const auth = useAuth()
  const [template, setTemplate] = useState<NarrativeTemplateSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [visBusy, setVisBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    setError(null)
    api
      .getNarrativeTemplate(templateId)
      .then((res) => {
        if (cancelled) return
        setTemplate(res)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : "故事不见了。")
      })
    return () => {
      cancelled = true
    }
  }, [api, templateId])

  const handleStart = async () => {
    if (busy || !template) return
    if (auth.isAnonymous) {
      window.location.hash = `#/login?next=template/${templateId}`
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await api.startNarrativeSession(templateId)
      onSessionStarted(res.session.session_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : "开始游戏失败，请重试。")
      setBusy(false)
    }
  }

  const handleVisibility = async (next: NarrativeTemplateVisibility) => {
    if (visBusy || !template) return
    setVisBusy(true)
    try {
      const updated = await api.updateNarrativeTemplateVisibility(templateId, {
        visibility: next,
      })
      setTemplate(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : "可见性修改失败。")
    } finally {
      setVisBusy(false)
    }
  }

  if (!template) {
    return (
      <div style={tdStyles.page}>
        <Header onHome={onBackHome} onCreate={onOpenCreate} />
        <div style={tdStyles.center}>{error ? `加载失败：${error}` : "加载中…"}</div>
      </div>
    )
  }

  return (
    <div style={tdStyles.page}>
      <Header onHome={onBackHome} onCreate={onOpenCreate} />

      <main style={tdStyles.main}>
        <div style={tdStyles.titleBlock}>
          <button style={tdStyles.crumb} onClick={onBackHome} type="button">
            ← 回到首页
          </button>
          <h1 style={tdStyles.title}>{template.title}</h1>
          <div style={tdStyles.metaRow}>
            <span style={tdStyles.badge}>{visibilityLabel(template.visibility)}</span>
            <span style={tdStyles.metaItem}>已被玩 {template.play_count} 局</span>
            {template.is_owner ? (
              <span style={{ ...tdStyles.badge, ...tdStyles.ownerBadge }}>我创建的</span>
            ) : null}
          </div>
        </div>

        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>原始种子</div>
          <div style={tdStyles.seedQuote}>"{template.seed}"</div>
        </section>

        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>出场人物</div>
          <div style={tdStyles.castList}>
            {template.cast.map((c) => (
              <div key={c.character_id} style={tdStyles.castRow}>
                <div style={tdStyles.castName}>{c.display_name}</div>
                <div style={tdStyles.castRole}>{c.role}</div>
                <div style={tdStyles.castRelation}>{c.relation_to_protagonist}</div>
              </div>
            ))}
          </div>
        </section>

        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>你的局外人朋友</div>
          <div style={tdStyles.advisorBlock}>{template.advisor_persona}</div>
        </section>

        {error ? <div style={tdStyles.errorBox}>{error}</div> : null}

        <div style={tdStyles.actions}>
          <button
            className="ts-btn ts-btn--primary ts-btn--lg"
            onClick={() => void handleStart()}
            disabled={busy}
            style={{
              minWidth: 240,
              opacity: busy ? 0.5 : 1,
              pointerEvents: busy ? "none" : "auto",
            }}
            type="button"
          >
            {busy ? "开始中…" : "开始一局新故事 →"}
          </button>
          <p style={tdStyles.actionHint}>
            每个人的玩法都不同，开局相同，剧情走向取决于你。
          </p>
        </div>

        {/* Owner-only: visibility controls */}
        {template.is_owner ? (
          <section style={tdStyles.ownerSection}>
            <div style={tdStyles.sectionLabel}>谁能玩</div>
            <div style={tdStyles.visControls}>
              {(["private", "unlisted", "public"] as NarrativeTemplateVisibility[]).map((v) => (
                <button
                  key={v}
                  style={{
                    ...tdStyles.visBtn,
                    ...(template.visibility === v ? tdStyles.visBtnActive : {}),
                  }}
                  onClick={() => void handleVisibility(v)}
                  disabled={visBusy || template.visibility === v}
                  type="button"
                >
                  {visibilityLabel(v)}
                </button>
              ))}
            </div>
          </section>
        ) : null}
      </main>
    </div>
  )
}

function visibilityLabel(v: NarrativeTemplateVisibility): string {
  if (v === "public") return "广场公开"
  if (v === "unlisted") return "凭链接"
  return "只有我"
}

const tdStyles: Record<string, CSSProperties> = {
  page: { minHeight: "100%", background: "var(--bg)" },
  center: { padding: 80, textAlign: "center", color: "var(--text-muted)" },
  main: { maxWidth: 720, margin: "0 auto", padding: "48px 32px 80px" },

  titleBlock: { marginBottom: 32 },
  crumb: {
    background: "none",
    border: "none",
    color: "var(--text-muted)",
    fontSize: 13,
    cursor: "pointer",
    padding: 0,
    marginBottom: 16,
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 36,
    lineHeight: 1.2,
    fontWeight: 400,
    margin: "0 0 14px",
  },
  metaRow: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  badge: {
    padding: "4px 10px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
    fontSize: 12,
    color: "var(--text-muted)",
  },
  ownerBadge: {
    background: "var(--accent-soft)",
    color: "var(--accent)",
    borderColor: "transparent",
  },
  metaItem: { fontSize: 12, color: "var(--text-faint)" },

  section: { marginBottom: 28 },
  sectionLabel: {
    fontSize: 11,
    color: "var(--text-faint)",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
    marginBottom: 10,
  },
  seedQuote: {
    fontFamily: "var(--font-narrative)",
    fontSize: 17,
    lineHeight: 1.6,
    color: "var(--text-muted)",
    fontStyle: "italic",
    padding: "14px 18px",
    borderLeft: "2px solid var(--line-strong)",
    background: "var(--bg-elev)",
    borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
  },

  castList: { display: "flex", flexDirection: "column", gap: 8 },
  castRow: {
    display: "grid",
    gridTemplateColumns: "120px 140px 1fr",
    alignItems: "baseline",
    gap: 12,
    padding: "12px 14px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
  },
  castName: { fontSize: 15, fontWeight: 500 },
  castRole: { fontSize: 12, color: "var(--accent)" },
  castRelation: { fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5 },

  advisorBlock: {
    padding: "14px 18px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
    fontSize: 14,
    lineHeight: 1.6,
    color: "var(--text)",
  },

  actions: { marginTop: 40, display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 },
  actionHint: { fontSize: 12, color: "var(--text-faint)", margin: 0 },

  errorBox: {
    padding: "12px 16px",
    background: "rgba(220,80,80,0.08)",
    border: "1px solid rgba(220,80,80,0.25)",
    borderRadius: "var(--radius-sm)",
    fontSize: 13,
    color: "var(--warn)",
    marginBottom: 16,
  },

  ownerSection: { marginTop: 56, paddingTop: 32, borderTop: "1px dashed var(--line)" },
  visControls: { display: "flex", gap: 8, flexWrap: "wrap" },
  visBtn: {
    padding: "8px 14px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: 999,
    fontSize: 13,
    color: "var(--text-muted)",
    cursor: "pointer",
  },
  visBtnActive: {
    background: "var(--accent-soft)",
    color: "var(--accent)",
    borderColor: "var(--accent)",
  },
}
