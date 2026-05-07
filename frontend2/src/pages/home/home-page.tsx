import { type CSSProperties, useEffect, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
import type {
  NarrativeSessionSummary,
  NarrativeTemplateSummary,
} from "../../api/contracts"
import { useApi } from "../../app/api-context"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { LoadingShim } from "../../shared/ui/loading-shim"
import { Truncated } from "../../shared/ui/truncated"
import {
  PAGE_BG,
  getCoverForTemplate,
  getEmptyPlazaImage,
} from "../../shared/lib/webtoon-assets"
import { friendlyError } from "../../shared/lib/friendly-error"
import { ENDING_LABEL_DISPLAY, useLanguage, useT } from "../../shared/lib/i18n"
import { hoverLift, itemTransition, itemVariants, tapPress, transitions } from "../../shared/lib/motion-presets"

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
  const t = useT()
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
        setError(friendlyError(err, t("home.error_plaza")))
      })
    return () => {
      cancelled = true
    }
  }, [api, t])

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
        <motion.section
          style={hpStyles.hero}
          initial="initial"
          animate="animate"
          transition={{ staggerChildren: 0.08, delayChildren: 0.05 }}
        >
          <motion.div
            variants={itemVariants}
            transition={itemTransition}
            style={hpStyles.heroTagline}
          >
            {t("home.hero_tagline")}
          </motion.div>
          <motion.h1
            variants={itemVariants}
            transition={itemTransition}
            style={hpStyles.heroTitle}
          >
            {t("home.hero_title_l1")}
            <br />
            {t("home.hero_title_l2")}
          </motion.h1>
          <motion.p
            variants={itemVariants}
            transition={itemTransition}
            style={hpStyles.heroSub}
          >
            {t("home.hero_sub")}
          </motion.p>
          <motion.ul
            variants={itemVariants}
            transition={itemTransition}
            style={hpStyles.heroBullets}
          >
            <li><span style={hpStyles.heroBulletDot}>·</span>{t("home.hero_bullet_1")}</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>{t("home.hero_bullet_2")}</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>{t("home.hero_bullet_3")}</li>
            <li><span style={hpStyles.heroBulletDot}>·</span>{t("home.hero_bullet_4")}</li>
          </motion.ul>
          <motion.div
            variants={itemVariants}
            transition={itemTransition}
            style={hpStyles.heroActions}
          >
            <motion.button
              className="ts-btn ts-btn--primary ts-btn--lg"
              onClick={onOpenCreate}
              type="button"
              whileHover={{ scale: 1.03 }}
              whileTap={tapPress}
            >
              {t("home.cta_create")}
            </motion.button>
          </motion.div>
        </motion.section>

        {/* My sessions split into in-progress + completed groups. Only
            shown when signed in and at least one exists. */}
        {!auth.isAnonymous && mySessions && mySessions.length > 0 ? (
          <MySessionsSection sessions={mySessions} onOpenPlay={onOpenPlay} />
        ) : null}

        <section style={hpStyles.section}>
          <div style={hpStyles.tabs} role="tablist">
            <button
              style={{ ...hpStyles.tab, ...(tab === "plaza" ? hpStyles.tabActive : {}) }}
              onClick={() => setTab("plaza")}
              type="button"
              role="tab"
              aria-selected={tab === "plaza"}
            >
              {t("home.tab_plaza")}
            </button>
            {!auth.isAnonymous ? (
              <button
                style={{
                  ...hpStyles.tab,
                  ...(tab === "my-templates" ? hpStyles.tabActive : {}),
                }}
                onClick={() => setTab("my-templates")}
                type="button"
                role="tab"
                aria-selected={tab === "my-templates"}
              >
                {t("home.tab_my")}
              </button>
            ) : null}
          </div>

          {/* Cross-fade between plaza ↔ my-templates so switching feels
              like a sibling pivot, not a layout swap. mode="wait"
              keeps the height stable during the transition. */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={transitions.snap}
            >
              {tab === "plaza" ? (
                <TemplateGrid
                  templates={publicTemplates}
                  error={error}
                  emptyText={t("home.empty_plaza")}
                  onOpenTemplate={onOpenTemplate}
                />
              ) : (
                <TemplateGrid
                  templates={myTemplates}
                  error={null}
                  emptyText={t("home.empty_my")}
                  onOpenTemplate={onOpenTemplate}
                />
              )}
            </motion.div>
          </AnimatePresence>
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
            {t("home.footer_about")}
          </a>
          <span style={hpStyles.footerSep}>·</span>
          <a
            href="mailto:hello@tinystories.app"
            style={hpStyles.footerLink}
          >
            {t("home.footer_contact")}
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
  const t = useT()
  // Split: in-progress (no ending) above, completed (has ending) below.
  const inProgress = sessions.filter((s) => !s.ending_label)
  const completed = sessions.filter((s) => Boolean(s.ending_label))
  return (
    <>
      {inProgress.length > 0 ? (
        <section style={hpStyles.section}>
          <SectionHeader title={t("home.section_in_progress")} />
          <div style={hpStyles.sessionRow}>
            {inProgress.slice(0, 6).map((s, idx) => (
              <SessionCard
                key={s.session_id}
                session={s}
                index={idx}
                onClick={() => onOpenPlay(s.session_id)}
              />
            ))}
          </div>
        </section>
      ) : null}
      {completed.length > 0 ? (
        <section style={hpStyles.section}>
          <SectionHeader title={t("home.section_completed")} />
          <div style={hpStyles.sessionRow}>
            {completed.slice(0, 6).map((s, idx) => (
              <SessionCard
                key={s.session_id}
                session={s}
                index={idx}
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
  index = 0,
}: {
  session: NarrativeSessionSummary
  onClick: () => void
  index?: number
}) {
  const { lang } = useLanguage()
  const t = useT()
  const completed = Boolean(session.ending_label)
  const endingLabelDisplay = session.ending_label
    ? ENDING_LABEL_DISPLAY[lang]?.[session.ending_label] ?? session.ending_label
    : null
  return (
    <motion.button
      style={hpStyles.sessionCard}
      onClick={onClick}
      type="button"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, ...itemTransition }}
      whileHover={hoverLift}
      whileTap={tapPress}
    >
      <Truncated style={hpStyles.sessionTitle}>{session.template_title}</Truncated>
      {completed ? (
        <>
          <div style={hpStyles.sessionEndingLine}>
            <span style={hpStyles.sessionEndingLabel}>{endingLabelDisplay}</span>
            <Truncated style={hpStyles.sessionEndingSubtitle}>
              {`「${session.ending_subtitle ?? ""}」`}
            </Truncated>
          </div>
          <div style={hpStyles.sessionMeta}>
            {t("home.session_completed_meta")} · {formatRelative(session.last_active_at, t)}
          </div>
        </>
      ) : (
        <div style={hpStyles.sessionMeta}>
          {t("home.session_progress_meta", {
            current: session.turn_count + 1,
            total: session.turn_budget,
          })}{" "}
          · {formatRelative(session.last_active_at, t)}
        </div>
      )}
    </motion.button>
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
    return <LoadingShim variant="inline" />
  }
  if (templates.length === 0) {
    return (
      <motion.div
        style={hpStyles.emptyCard}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={itemTransition}
      >
        <div
          style={{
            ...hpStyles.emptyHero,
            backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0.05) 0%, rgba(20,16,12,0.55) 75%, var(--bg-elev) 100%), url(${getEmptyPlazaImage()})`,
          }}
        />
        <div style={hpStyles.emptyBody}>{emptyText}</div>
      </motion.div>
    )
  }
  return (
    <div style={hpStyles.grid}>
      {templates.map((t, idx) => (
        <TemplateCard
          key={t.template_id}
          template={t}
          index={idx}
          onClick={() => onOpenTemplate(t.template_id)}
        />
      ))}
    </div>
  )
}

function TemplateCard({
  template,
  onClick,
  index = 0,
}: {
  template: NarrativeTemplateSummary
  onClick: () => void
  index?: number
}) {
  const t = useT()
  const cover = getCoverForTemplate(template)
  return (
    <motion.button
      style={hpStyles.card}
      onClick={onClick}
      type="button"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, ...itemTransition }}
      whileHover={hoverLift}
      whileTap={tapPress}
    >
      <div
        style={{
          ...hpStyles.cardCover,
          backgroundImage: `linear-gradient(180deg, rgba(20,16,12,0) 30%, rgba(20,16,12,0.78) 100%), url(${cover})`,
        }}
      >
        <div style={hpStyles.cardCoverFade}>
          <Truncated lines={2} style={hpStyles.cardTitle}>
            {template.title}
          </Truncated>
          <Truncated style={hpStyles.cardCast}>
            {template.cast.map((c) => c.display_name).join(" · ")}
          </Truncated>
        </div>
      </div>
      <div style={hpStyles.cardBody}>
        <Truncated lines={2} style={hpStyles.cardSeed}>{`"${template.seed}"`}</Truncated>
        <div style={hpStyles.cardFooter}>
          <span style={hpStyles.cardBadge}>{visibilityLabel(template.visibility, t)}</span>
          <span style={hpStyles.cardPlays}>{t("home.played_count", { count: template.play_count })}</span>
          {template.is_owner ? (
            <span style={hpStyles.cardOwnerBadge}>{t("home.is_owner")}</span>
          ) : null}
        </div>
      </div>
    </motion.button>
  )
}

function visibilityLabel(v: NarrativeTemplateSummary["visibility"], t: ReturnType<typeof useT>): string {
  if (v === "public") return t("home.visibility_public")
  if (v === "unlisted") return t("home.visibility_unlisted")
  return t("home.visibility_private")
}

function formatRelative(isoString: string, t: ReturnType<typeof useT>): string {
  const date = new Date(isoString)
  const diffMs = Date.now() - date.getTime()
  const minutes = Math.floor(diffMs / 60000)
  if (minutes < 1) return t("home.relative_just_now")
  if (minutes < 60) return t("home.relative_minutes", { n: minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t("home.relative_hours", { n: hours })
  const days = Math.floor(hours / 24)
  if (days < 30) return t("home.relative_days", { n: days })
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
    flex: "1 1 0",
    minWidth: 0,
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
    marginBottom: 4,
  },
  cardSeed: {
    fontSize: 13,
    color: "var(--text-muted)",
    fontStyle: "italic",
    lineHeight: 1.5,
  },
  cardCast: {
    fontSize: 12,
    color: "rgba(255,255,255,0.78)",
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
  emptyCard: {
    background: "var(--bg-elev)",
    borderRadius: "var(--radius-md)",
    border: "1px solid var(--line)",
    overflow: "hidden",
  },
  emptyHero: {
    width: "100%",
    height: 180,
    backgroundSize: "cover",
    backgroundPosition: "center",
  },
  emptyBody: {
    padding: "20px 24px 28px",
    textAlign: "center",
    color: "var(--text-muted)",
    fontSize: 14,
    fontStyle: "italic",
    fontFamily: "var(--font-narrative)",
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
