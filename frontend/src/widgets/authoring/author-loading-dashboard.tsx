import type { CSSProperties } from "react"
import { motion } from "motion/react"
import type { AuthorJobResultResponse, AuthorJobStatusResponse, AuthorLoadingCard, StoryVisibility } from "../../index"
import { LoadingCardSpotlight } from "../../entities/authoring/ui/loading-card-spotlight"
import { STORYLINE_ASSETS, loadingHeroAsset } from "../../shared/lib/storyline-assets"
import { localizeStorylineLabel, localizeStorylineValue } from "../../shared/lib/storyline"
import { StorylineAtmosphereTile, StorylineMetaStrip, StorylineSectionHeader, StorylineTag } from "../../shared/ui/storyline-primitives"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"
import { StudioFooter } from "../chrome/studio-footer"

export function AuthorLoadingDashboard({
  job,
  result,
  error,
  completionPercent,
  publishLoading,
  cardPool,
  activeCard,
  publishVisibility,
  onPublishVisibilityChange,
  onPublish,
}: {
  job: AuthorJobStatusResponse | null
  result: AuthorJobResultResponse | null
  error: string | null
  completionPercent: number
  publishLoading: boolean
  cardPool: AuthorLoadingCard[]
  activeCard: AuthorLoadingCard | null
  publishVisibility: StoryVisibility
  onPublishVisibilityChange: (visibility: StoryVisibility) => void
  onPublish: () => void
}) {
  const motionPreset = useStorylineMotion()
  const progressSnapshot = job?.progress_snapshot ?? result?.progress_snapshot ?? null
  const isReady = Boolean(result?.summary)

  return (
    <div className="editorial-page editorial-page--loading storyline-page storyline-page--loading">
      <section
        className="storyline-loading-stage"
        style={{ "--storyline-surface-image": `url("${loadingHeroAsset()}")` } as CSSProperties}
      >
        <div aria-hidden="true" className="storyline-loading-stage__veil" />

        <motion.div className="storyline-loading-stage__copy storyline-poster-stage" {...motionPreset.reveal({ y: 24, duration: 0.82 })}>
          <StorylineTag tone={isReady ? "gold" : "danger"}>{isReady ? "案卷就绪" : "案卷编译中"}</StorylineTag>
          <h1>{result?.summary?.title ?? job?.preview.story.title ?? "正在组装下一份危险案卷"}</h1>
          <p className="storyline-loading-stage__subtitle">
            {progressSnapshot?.stage_label ?? "等待开始"} · 角色关系、章节节奏和结局压力正在被收束成一份可以发布的正式案卷。
          </p>

          <div className="storyline-progress-track">
            <motion.div
              className="storyline-progress-track__fill"
              initial={{ width: 0 }}
              animate={{ width: `${completionPercent}%` }}
              transition={motionPreset.reduced ? { duration: 0 } : { duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
            />
          </div>

          <StorylineMetaStrip
            items={[
              { label: "进度", value: `${completionPercent}%` },
              { label: "主题", value: localizeStorylineValue(result?.summary?.theme ?? job?.preview.theme.primary_theme ?? "待定") },
              { label: "编号", value: job?.job_id.slice(0, 8).toUpperCase() ?? "00000000" },
            ]}
          />
        </motion.div>

        <motion.aside className="storyline-loading-stage__spotlight" {...motionPreset.reveal({ delay: 0.16, x: 24, y: 0, duration: 0.82 })}>
          <StorylineSectionHeader
            eyebrow={<StorylineTag tone="muted">实时卡片</StorylineTag>}
            title="桌上的这份案卷"
            subtitle={progressSnapshot?.stage_label ?? "等待第一张机密卡片送达。"}
          />

          {progressSnapshot ? (
            <LoadingCardSpotlight activeCard={activeCard} cardPool={cardPool} />
          ) : (
            <div className="editorial-empty-state">
              <h3>等待第一张卡片</h3>
              <p>编写任务已经开始，但第一张机密卡片还没有送达。</p>
            </div>
          )}

          {error ? <p className="editorial-error">{error}</p> : null}
        </motion.aside>
      </section>

      <section className="storyline-loading-dossier">
        <motion.section className="storyline-panel storyline-loading-context" {...motionPreset.inView({ y: 22, duration: 0.62 })}>
          <StorylineSectionHeader
            eyebrow={<StorylineTag tone="muted">案卷账本</StorylineTag>}
            title={result?.summary?.title ?? job?.preview.story.title ?? "当前路线"}
            subtitle={job?.preview.story.premise ?? "最新快照一到，这里就会继续补全这份关系案卷。"}
          />

          <StorylineMetaStrip
            items={[
              { label: "气质", value: localizeStorylineValue(result?.summary?.tone ?? job?.preview.story.tone ?? "待定") },
              { label: "人物", value: result?.summary?.npc_count ?? job?.preview.structure.expected_npc_count ?? 0 },
              { label: "章节", value: result?.summary?.beat_count ?? job?.preview.structure.expected_beat_count ?? 0 },
            ]}
          />

          <div className="storyline-chip-grid">
            {(job?.preview.flashcards ?? []).slice(0, 6).map((card) => (
              <StorylineTag key={card.card_id} tone={card.kind === "stable" ? "gold" : "default"}>
                {localizeStorylineLabel(card.label)}：{localizeStorylineValue(card.value)}
              </StorylineTag>
            ))}
          </div>

          {isReady ? (
            <div className="storyline-publish-box">
              <label className="storyline-input-inline">
                <span className="storyline-field-label">发布可见性</span>
                <select onChange={(event) => onPublishVisibilityChange(event.target.value as StoryVisibility)} value={publishVisibility}>
                  <option value="private">私密</option>
                  <option value="public">公开</option>
                </select>
              </label>
              <motion.button
                className="studio-button studio-button--primary"
                disabled={publishLoading}
                onClick={onPublish}
                type="button"
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
              >
                {publishLoading ? "发布中..." : "发布到档案库"}
              </motion.button>
            </div>
          ) : (
            <div className="storyline-note-box">
              <span className="storyline-field-label">状态</span>
              <p>请稍等，关系网络正在被收束成一份可发布的正式案卷。</p>
            </div>
          )}
        </motion.section>

        <motion.aside className="storyline-panel storyline-loading-note" {...motionPreset.inView({ delay: 0.12, y: 22, duration: 0.62 })}>
          <div
            className="storyline-loading-note__still"
            style={{ "--storyline-surface-image": `url("${STORYLINE_ASSETS.backgrounds.premiumStillLife}")` } as CSSProperties}
          />
          <StorylineAtmosphereTile
            asset={STORYLINE_ASSETS.backgrounds.evidenceDark}
            compact
            eyebrow="夜色桌面"
            summary="越像随手搁置的东西，越可能是最先让人改口的那件。"
            title="还没发布，证物就已经先替你发声"
          />
        </motion.aside>
      </section>

      <StudioFooter />
    </div>
  )
}
