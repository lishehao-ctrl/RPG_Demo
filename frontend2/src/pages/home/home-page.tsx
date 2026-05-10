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
        {/* Webtoon-cinematic hero — full-bleed splash background, text
            left-aligned over a vertical fade. Style brief: like Naver
            webtoon / Solo Leveling landing — single sustained scene
            anchored by a serif title. Bullet list moved to a smaller
            "how it works" rail under plaza so the hero stays as a
            single dramatic beat. */}
        <motion.section
          style={hpStyles.hero}
          initial="initial"
          animate="animate"
          transition={{ staggerChildren: 0.08, delayChildren: 0.05 }}
        >
          <div style={hpStyles.heroInner}>
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
              <motion.button
                className="ts-btn ts-btn--ghost ts-btn--lg"
                onClick={() => {
                  window.location.hash = "#/portfolio"
                }}
                type="button"
                whileHover={{ scale: 1.03 }}
                whileTap={tapPress}
              >
                {t("home.cta_portfolio")}
              </motion.button>
            </motion.div>
          </div>
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
            href="#/portfolio"
            style={hpStyles.footerLink}
            onClick={(e) => {
              e.preventDefault()
              window.location.hash = "#/portfolio"
            }}
          >
            {t("home.footer_portfolio")}
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
          {/* Personal-archive header: title + accumulated count.
              Gives the user a sense of "this is mounting up." Without
              the count, every visit looks the same; with it, finishing
              a 7th run reads as crossing a threshold. */}
          <div style={hpStyles.archiveHeader}>
            <h2 style={hpStyles.sectionTitle}>{t("home.section_completed")}</h2>
            <span style={hpStyles.archiveCount}>
              {t("home.archive_count", { n: completed.length })}
            </span>
          </div>
          <div style={hpStyles.sessionRow}>
            {/* Chronological newest-first; reverse-index gives each
                entry a stable "#N" marker that increments as the user
                accumulates more runs. */}
            {completed.slice(0, 6).map((s, idx) => (
              <SessionCard
                key={s.session_id}
                session={s}
                index={idx}
                archiveNumber={completed.length - idx}
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
  archiveNumber,
}: {
  session: NarrativeSessionSummary
  onClick: () => void
  index?: number
  /** When set, render the card as an archive entry — "#N" marker
   *  in the corner + tier-colored ending chip. Only completed runs
   *  receive this. */
  archiveNumber?: number
}) {
  const { lang } = useLanguage()
  const t = useT()
  const completed = Boolean(session.ending_label)
  const endingLabelDisplay = session.ending_label
    ? ENDING_LABEL_DISPLAY[lang]?.[session.ending_label] ?? session.ending_label
    : null
  // Tier drives the chip's color treatment so "Vengeance" reads
  // visually different from "Sink" — finished-runs grid becomes a
  // legible archive instead of a wall of identical pills.
  const tierChipStyle: CSSProperties =
    session.ending_tier === "victory"
      ? hpStyles.endingChipVictory
      : session.ending_tier === "collapsed"
        ? hpStyles.endingChipCollapsed
        : hpStyles.endingChipCompromised
  const tierGlyph =
    session.ending_tier === "victory"
      ? "✦"
      : session.ending_tier === "collapsed"
        ? "✕"
        : "◇"
  return (
    <motion.button
      style={{
        ...hpStyles.sessionCard,
        ...(archiveNumber != null ? hpStyles.sessionCardArchive : null),
      }}
      onClick={onClick}
      type="button"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, ...itemTransition }}
      whileHover={hoverLift}
      whileTap={tapPress}
    >
      {archiveNumber != null ? (
        <span style={hpStyles.archiveBadge} aria-hidden>
          #{archiveNumber}
        </span>
      ) : null}
      <Truncated style={hpStyles.sessionTitle}>{session.template_title}</Truncated>
      {completed ? (
        <>
          <div style={hpStyles.sessionEndingLine}>
            <span style={{ ...hpStyles.sessionEndingLabel, ...tierChipStyle }}>
              <span style={hpStyles.endingChipGlyph} aria-hidden>{tierGlyph}</span>
              {endingLabelDisplay}
            </span>
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
          // Stronger 3-stop gradient: top stays clear (let the
          // illustration breathe), middle drops in, bottom is near-
          // black so the serif title reads cleanly. Manhwa-panel
          // convention for title cards.
          backgroundImage: `linear-gradient(180deg, rgba(12,12,16,0) 0%, rgba(12,12,16,0) 38%, rgba(12,12,16,0.55) 70%, rgba(12,12,16,0.94) 100%), url(${cover})`,
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
    minHeight: 480,
    padding: 0,
    borderRadius: "var(--radius-lg)",
    overflow: "hidden",
    // Vertical gradient: keep the upper half of the splash visible,
    // fade to product bg at the bottom so cards slide up underneath
    // without a hard seam. Horizontal gradient on the left so text
    // sits on solid darkness regardless of where the figures land
    // in the source painting.
    backgroundImage: `linear-gradient(90deg, rgba(12,12,16,0.92) 0%, rgba(12,12,16,0.55) 38%, rgba(12,12,16,0.18) 70%, rgba(12,12,16,0) 100%), linear-gradient(180deg, rgba(12,12,16,0.05) 0%, rgba(12,12,16,0.45) 80%, var(--bg) 100%), url(${PAGE_BG.splash})`,
    backgroundSize: "cover",
    backgroundPosition: "center 30%",
    color: "white",
    marginBottom: 32,
    display: "flex",
    alignItems: "center",
  },
  heroInner: {
    width: "100%",
    maxWidth: 720,
    padding: "88px 56px 96px",
    textAlign: "left" as const,
  },
  heroTagline: {
    display: "inline-block",
    fontSize: 11,
    letterSpacing: "0.22em",
    textTransform: "uppercase" as const,
    color: "var(--accent)",
    marginBottom: 24,
    fontWeight: 600,
  },
  heroTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 56,
    lineHeight: 1.08,
    fontWeight: 400,
    margin: "0 0 22px",
    color: "white",
    textShadow: "0 2px 28px rgba(0,0,0,0.55)",
    letterSpacing: "-0.01em",
  },
  heroSub: {
    fontSize: 16,
    lineHeight: 1.65,
    color: "rgba(244,239,230,0.82)",
    maxWidth: 540,
    margin: "0 0 32px",
    fontWeight: 400,
  },
  heroActions: { display: "flex", justifyContent: "flex-start", gap: 12, flexWrap: "wrap" },

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
    position: "relative",
  },
  // Archive treatment for completed runs — slightly heavier border,
  // top-right "#N" badge. Reads as a stamped catalog entry rather
  // than just a hover-able card.
  sessionCardArchive: {
    borderColor: "var(--line-strong)",
    background: "linear-gradient(180deg, var(--bg-elev), rgba(255,255,255,0.01))",
  },
  archiveHeader: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    marginBottom: 18,
    gap: 16,
  },
  archiveCount: {
    fontSize: 11.5,
    color: "var(--text-faint)",
    letterSpacing: "0.08em",
    textTransform: "uppercase" as const,
    fontVariantNumeric: "tabular-nums",
  },
  archiveBadge: {
    position: "absolute",
    top: 10,
    right: 12,
    fontSize: 10.5,
    color: "var(--text-faint)",
    fontVariantNumeric: "tabular-nums",
    letterSpacing: "0.06em",
  },
  endingChipGlyph: {
    marginRight: 4,
    fontSize: 11,
  },
  // Tier-colored ending chips. Each one signals the broad category
  // (win / muddied / disaster) at a glance, so a list of completed
  // runs reads as a record of varied outcomes, not a uniform pill row.
  endingChipVictory: {
    background: "linear-gradient(90deg, rgba(212,168,83,0.32), rgba(212,168,83,0.18))",
    color: "rgba(245,210,140,0.96)",
    border: "1px solid rgba(212,168,83,0.4)",
  },
  endingChipCompromised: {
    background: "rgba(255,255,255,0.08)",
    color: "var(--text)",
    border: "1px solid var(--line-strong)",
  },
  endingChipCollapsed: {
    background: "rgba(220,80,60,0.18)",
    color: "rgba(245,180,170,0.95)",
    border: "1px solid rgba(220,80,60,0.42)",
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

  // Manhwa-panel grid: tighter cards (200-240 wide) so 4-5 fit per
  // row on a typical desktop, like a webtoon platform's catalog
  // landing. Cover-dominant aspect (~9:11) reads as a vertical
  // panel, not a square thumbnail.
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
    gap: 14,
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
  // Cover takes the visual majority of the card (240px tall).
  // Title sits in a strong gradient mask at the bottom, white
  // serif on near-black — webtoon catalog aesthetic.
  cardCover: {
    height: 240,
    backgroundSize: "cover",
    backgroundPosition: "center",
    display: "flex",
    alignItems: "flex-end",
    padding: "14px 14px 12px",
    position: "relative" as const,
  },
  cardCoverFade: {
    width: "100%",
    position: "relative" as const,
    zIndex: 1,
  },
  cardBody: {
    padding: "10px 14px 12px",
    display: "flex",
    flexDirection: "column",
    gap: 8,
    background: "var(--bg-elev)",
  },
  cardTitle: {
    fontFamily: "var(--font-narrative)",
    fontSize: 17,
    lineHeight: 1.25,
    fontWeight: 500,
    color: "white",
    textShadow: "0 2px 14px rgba(0,0,0,0.85), 0 1px 2px rgba(0,0,0,0.6)",
    marginBottom: 3,
    letterSpacing: "-0.005em",
  },
  cardSeed: {
    fontSize: 12.5,
    color: "var(--text-muted)",
    fontStyle: "italic",
    lineHeight: 1.5,
  },
  cardCast: {
    fontSize: 11,
    color: "rgba(255,255,255,0.72)",
    textShadow: "0 1px 6px rgba(0,0,0,0.85)",
    letterSpacing: "0.02em",
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
