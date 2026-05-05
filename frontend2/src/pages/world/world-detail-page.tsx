import { type CSSProperties, useEffect, useRef, useState } from "react"
import { motion } from "motion/react"
import type {
  NarrativeEndingDistributionResponse,
  NarrativeTemplateSummary,
  NarrativeTemplateVisibility,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { friendlyError } from "../../shared/lib/friendly-error"
import { hoverLift, itemTransition, tapPress } from "../../shared/lib/motion-presets"
import {
  getAdvisorAvatar,
  getAvatarForCastMember,
  getCoverForTemplate,
} from "../../shared/lib/webtoon-assets"

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
  const [distribution, setDistribution] = useState<NarrativeEndingDistributionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [visBusy, setVisBusy] = useState(false)
  const startInflightRef = useRef(false)

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
        setError(friendlyError(err, "故事不见了。"))
      })
    api
      .getNarrativeEndingDistribution(templateId)
      .then((res) => {
        if (cancelled) return
        setDistribution(res)
      })
      .catch(() => {
        // Distribution failure is non-fatal — just skip rendering it.
      })
    return () => {
      cancelled = true
    }
  }, [api, templateId])

  const handleStart = async () => {
    if (startInflightRef.current || !template) return
    if (auth.isAnonymous) {
      window.location.hash = `#/login?next=template/${templateId}`
      return
    }
    startInflightRef.current = true
    setBusy(true)
    setError(null)
    try {
      const res = await api.startNarrativeSession(templateId)
      onSessionStarted(res.session.session_id)
    } catch (err) {
      setError(friendlyError(err, "开始游戏失败，请重试。"))
      setBusy(false)
      startInflightRef.current = false
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
      setError(friendlyError(err, "可见性修改失败。"))
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

  const cover = getCoverForTemplate(template)
  const advisorAvatar = getAdvisorAvatar(template.template_id, template.advisor_persona)

  return (
    <div style={tdStyles.page}>
      <Header onHome={onBackHome} onCreate={onOpenCreate} />

      {/* Hero: shell cover with title overlay */}
      <div
        style={{
          ...tdStyles.hero,
          backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.18) 0%, rgba(20,16,12,0.6) 60%, var(--bg) 100%), url(${cover})`,
        }}
      >
        <div style={tdStyles.heroInner}>
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
      </div>

      <main style={tdStyles.main}>
        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>原始种子</div>
          <div style={tdStyles.seedQuote}>"{template.seed}"</div>
        </section>

        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>出场人物</div>
          <div style={tdStyles.castList}>
            {template.cast.map((c) => (
              <div key={c.character_id} style={tdStyles.castRow}>
                <img
                  src={getAvatarForCastMember(template.template_id, c)}
                  alt={c.display_name}
                  style={tdStyles.castAvatar}
                  loading="lazy"
                />
                <div style={tdStyles.castInfo}>
                  <div style={tdStyles.castName}>{c.display_name}</div>
                  <div style={tdStyles.castRole}>{c.role}</div>
                  <div style={tdStyles.castRelation}>{c.relation_to_protagonist}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section style={tdStyles.section}>
          <div style={tdStyles.sectionLabel}>你的局外人朋友</div>
          <div style={tdStyles.advisorBlock}>
            <img src={advisorAvatar} alt="" style={tdStyles.advisorAvatar} loading="lazy" />
            <div style={tdStyles.advisorText}>{template.advisor_persona}</div>
          </div>
        </section>

        {distribution && distribution.total_completed > 0 ? (
          <section style={tdStyles.section}>
            <div style={tdStyles.sectionLabel}>
              玩家走出来的结局 · 共 {distribution.total_completed} 局完结
            </div>
            <div style={tdStyles.distributionList}>
              {distribution.entries.map((entry, idx) => {
                const pct = (entry.count / distribution.total_completed) * 100
                return (
                  <motion.div
                    key={entry.label}
                    style={tdStyles.distributionRow}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.05 * idx + 0.15, ...itemTransition }}
                  >
                    <div style={tdStyles.distributionLabel}>{entry.label}</div>
                    <div style={tdStyles.distributionBarTrack}>
                      <motion.div
                        style={tdStyles.distributionBarFill}
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ delay: 0.05 * idx + 0.25, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                      />
                    </div>
                    <div style={tdStyles.distributionCount}>×{entry.count}</div>
                  </motion.div>
                )
              })}
            </div>
            <p style={tdStyles.distributionHint}>
              你能玩出哪个？或者一个还没人走过的？
            </p>
          </section>
        ) : null}

        {error ? <div style={tdStyles.errorBox}>{error}</div> : null}

        <div style={tdStyles.actions}>
          <motion.button
            className="ts-btn ts-btn--primary ts-btn--lg"
            onClick={() => void handleStart()}
            disabled={busy}
            style={{
              minWidth: 240,
              opacity: busy ? 0.5 : 1,
              pointerEvents: busy ? "none" : "auto",
            }}
            type="button"
            whileHover={busy ? undefined : hoverLift}
            whileTap={busy ? undefined : tapPress}
          >
            {busy ? "开始中…" : "开始一局新故事 →"}
          </motion.button>
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
  main: { maxWidth: 720, margin: "-48px auto 0", padding: "0 32px 80px", position: "relative", zIndex: 2 },

  hero: {
    width: "100%",
    minHeight: 280,
    backgroundSize: "cover",
    backgroundPosition: "center",
    color: "white",
    display: "flex",
    alignItems: "flex-end",
  },
  heroInner: {
    width: "100%",
    maxWidth: 720,
    margin: "0 auto",
    padding: "32px 32px 56px",
  },
  crumb: {
    background: "rgba(255,255,255,0.12)",
    border: "1px solid rgba(255,255,255,0.18)",
    color: "white",
    fontSize: 12.5,
    cursor: "pointer",
    padding: "5px 12px",
    borderRadius: 999,
    marginBottom: 18,
    backdropFilter: "blur(6px)",
  },
  title: {
    fontFamily: "var(--font-narrative)",
    fontSize: 38,
    lineHeight: 1.18,
    fontWeight: 400,
    margin: "0 0 16px",
    color: "white",
    textShadow: "0 2px 18px rgba(0,0,0,0.5)",
  },
  metaRow: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  badge: {
    padding: "4px 10px",
    background: "rgba(255,255,255,0.16)",
    border: "1px solid rgba(255,255,255,0.22)",
    borderRadius: 999,
    fontSize: 12,
    color: "white",
    backdropFilter: "blur(6px)",
  },
  ownerBadge: {
    background: "var(--accent)",
    color: "white",
    borderColor: "transparent",
  },
  metaItem: { fontSize: 12, color: "rgba(255,255,255,0.78)" },

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

  castList: { display: "flex", flexDirection: "column", gap: 10 },
  castRow: {
    display: "flex",
    alignItems: "center",
    gap: 14,
    padding: "12px 14px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
  },
  castAvatar: {
    width: 56,
    height: 56,
    borderRadius: "50%",
    objectFit: "cover",
    border: "1px solid var(--line)",
    flexShrink: 0,
  },
  castInfo: { flex: 1, minWidth: 0 },
  castName: { fontSize: 15, fontWeight: 500 },
  castRole: { fontSize: 12, color: "var(--accent)", marginTop: 3 },
  castRelation: { fontSize: 13, color: "var(--text-muted)", lineHeight: 1.5, marginTop: 4 },

  advisorBlock: {
    padding: "14px 18px",
    background: "var(--bg-elev)",
    border: "1px solid var(--line)",
    borderRadius: "var(--radius-sm)",
    display: "flex",
    alignItems: "center",
    gap: 14,
  },
  advisorAvatar: {
    width: 48,
    height: 48,
    borderRadius: "50%",
    objectFit: "cover",
    border: "1px solid var(--line)",
    flexShrink: 0,
  },
  advisorText: {
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

  distributionList: { display: "flex", flexDirection: "column", gap: 6 },
  distributionRow: {
    display: "grid",
    gridTemplateColumns: "70px 1fr 40px",
    alignItems: "center",
    gap: 12,
  },
  distributionLabel: { fontSize: 13, color: "var(--text)", fontWeight: 500 },
  distributionBarTrack: {
    height: 8,
    background: "var(--bg-elev)",
    borderRadius: 4,
    overflow: "hidden",
    border: "1px solid var(--line)",
  },
  distributionBarFill: {
    height: "100%",
    background: "var(--accent)",
    borderRadius: 4,
    transition: "width 480ms ease-out",
  },
  distributionCount: {
    fontSize: 12,
    color: "var(--text-muted)",
    textAlign: "right",
  },
  distributionHint: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    fontStyle: "italic",
    margin: "12px 0 0",
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
