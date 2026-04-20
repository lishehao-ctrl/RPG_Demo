import { useState } from "react"
import { motion } from "motion/react"
import type { StoryVisibility } from "../../index"
import { useAuthorLoading } from "../../features/authoring/loading/model/use-author-loading"
import { getEditorialBackdropByView } from "../../shared/lib/editorial-assets"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const VISIBILITY_OPTIONS: StoryVisibility[] = ["private", "public"]

export function AuthorLoadingPage({
  jobId,
  onOpenCreateStory,
  onOpenLibrary,
}: {
  jobId: string
  onOpenCreateStory: () => void
  onOpenLibrary: (storyId: string) => void
}) {
  const loading = useAuthorLoading(jobId)
  const motionPreset = useStorylineMotion()
  const [publishVisibility, setPublishVisibility] = useState<StoryVisibility>("private")

  const handlePublish = async () => {
    const storyId = await loading.publishStory(publishVisibility)
    if (storyId) {
      onOpenLibrary(storyId)
    }
  }

  const summary = loading.result?.summary
  const previewTheme = loading.job?.preview.theme.primary_theme
  const backdrop = getEditorialBackdropByView("loading", summary?.theme ?? previewTheme)
  const stageLabel = loading.progressSnapshot?.stage_label ?? loading.job?.progress.stage ?? "正在整理档案"
  const activeCard = loading.activeCard
  const loadingCards = loading.cardPool.slice(0, 8)
  const completed = loading.job?.status === "completed"

  return (
    <main className="mag-page">
      <section className="mag-detail-hero mag-hero--compact">
        <div className="mag-hero__media" style={{ backgroundImage: `url("${backdrop}")` }} />
        <div className="mag-hero__veil" />
        <div className="mag-detail-hero__inner">
          <motion.div className="mag-detail-hero__copy" {...motionPreset.reveal({ y: 24, duration: 0.72 })}>
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">编译中</span>
              <span className="mag-chip mag-chip--gold">{stageLabel}</span>
            </div>
            <span className="mag-kicker">Author loading 已切成 flashcard 驱动的上线壳</span>
            <h1 className="mag-stage-title">{summary?.title ?? loading.job?.preview.story.title ?? "正在编写你的案卷"}</h1>
            <p>{summary?.premise ?? loading.progressSnapshot?.preview_premise ?? loading.job?.preview.story.premise ?? "系统正在收束人物、场面和终局压力。"}</p>

            <div className="mag-progress-shell">
              <div className="mag-loading-stage">
                <div className="mag-spinner" />
                <div>
                  <span className="mag-overline">当前阶段</span>
                  <strong>{stageLabel}</strong>
                </div>
              </div>
              <div className="mag-progress-bar">
                <div className="mag-progress-bar__fill" style={{ width: `${loading.completionPercent}%` }} />
              </div>
              <div className="mag-stat-row">
                <span className="mag-stat-pill">{`${loading.completionPercent}% 完成`}</span>
                <span className="mag-stat-pill">{completed ? "可发布" : "生成中"}</span>
              </div>
            </div>
          </motion.div>

          <motion.aside className="mag-detail-rail" {...motionPreset.reveal({ delay: 0.12, x: 18, y: 0, duration: 0.72 })}>
            <span className="mag-overline">当前闪卡</span>
            {activeCard ? (
              <div className="mag-side-stack">
                <div className="mag-flashcard">
                  <span className="mag-label">{activeCard.label}</span>
                  <strong>{activeCard.value}</strong>
                </div>
                <div className="mag-mini-stat">
                  <span>Job ID</span>
                  <strong>{jobId}</strong>
                </div>
              </div>
            ) : (
              <div className="mag-flashcard">
                <span className="mag-label">等待卡片</span>
                <strong>后端返回进度卡后会自动轮播</strong>
              </div>
            )}
          </motion.aside>
        </div>
      </section>

      <section className="mag-section">
        <div className="mag-section__inner">
          <div className="mag-form-layout">
            <motion.section className="mag-progress-card" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
              <div className="mag-section__header">
                <span className="mag-panel__eyebrow">编译卡片</span>
                <h2>把生成过程做成一张张逐步成形的档案卡</h2>
                <p>这部分继续由 live progress snapshot 驱动，不再是老的 dashboard 组件。</p>
              </div>

              <div className="mag-flashcard-stack">
                {loadingCards.length > 0 ? (
                  loadingCards.map((card) => (
                    <article className="mag-flashcard" key={card.card_id}>
                      <span className="mag-label">{card.label}</span>
                      <strong>{card.value}</strong>
                    </article>
                  ))
                ) : (
                  <article className="mag-flashcard">
                    <span className="mag-label">等待后端返回</span>
                    <strong>当前还没有可展示的 loading cards。</strong>
                  </article>
                )}
              </div>
            </motion.section>

            <motion.aside className="mag-result-card" {...motionPreset.inView({ delay: 0.12, x: 18, y: 0, duration: 0.58 })}>
              <div className="mag-section__header">
                <span className="mag-panel__eyebrow">发布收口</span>
                <h2>{completed ? "已经可以发布" : "等待编译完成"}</h2>
              </div>

              <div className="mag-side-stack">
                <div className="mag-mini-stat">
                  <span>标题</span>
                  <strong>{summary?.title ?? loading.job?.preview.story.title ?? "待生成"}</strong>
                </div>
                <div className="mag-mini-stat">
                  <span>题材</span>
                  <strong>{summary?.theme ?? previewTheme ?? "待生成"}</strong>
                </div>
                <div className="mag-mini-stat">
                  <span>角色数</span>
                  <strong>{summary?.npc_count ?? loading.progressSnapshot?.expected_npc_count ?? "--"}</strong>
                </div>
                <div className="mag-mini-stat">
                  <span>章节数</span>
                  <strong>{summary?.beat_count ?? loading.progressSnapshot?.expected_beat_count ?? "--"}</strong>
                </div>
              </div>

              <div className="mag-form-field">
                <label>发布可见性</label>
                <div className="mag-chip-select">
                  {VISIBILITY_OPTIONS.map((option) => (
                    <button
                      className={`mag-chip-button ${publishVisibility === option ? "is-active" : ""}`}
                      key={option}
                      onClick={() => setPublishVisibility(option)}
                      type="button"
                    >
                      {option === "private" ? "私密" : "公开"}
                    </button>
                  ))}
                </div>
              </div>

              {loading.error ? <p className="editorial-error">{loading.error}</p> : null}

              <div className="mag-action-row">
                <button className="mag-button mag-button--secondary" onClick={onOpenCreateStory} type="button">
                  返回重写
                </button>
                <button
                  className="mag-button mag-button--primary"
                  disabled={!completed || loading.publishLoading}
                  onClick={() => {
                    void handlePublish()
                  }}
                  type="button"
                >
                  {loading.publishLoading ? "发布中..." : "发布案卷"}
                </button>
              </div>
            </motion.aside>
          </div>
        </div>
      </section>
    </main>
  )
}
