import { useEffect, useState } from "react"
import { motion } from "motion/react"
import type { StoryVisibility } from "../../index"
import { useStoryDetail } from "../../features/play/story-detail/model/use-story-detail"
import { getEditorialCharacterImage, getEditorialThemeImage } from "../../shared/lib/editorial-assets"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

type DetailTab = "story" | "characters" | "beats" | "flashcards"

export function StoryDetailPage({
  isAuthenticated,
  storyId,
  onOpenLibrary,
  onDeleteToLibrary,
  onOpenPlaySession,
  onRequireAuth,
}: {
  isAuthenticated: boolean
  storyId: string
  onOpenLibrary: (storyId: string) => void
  onDeleteToLibrary: () => void
  onOpenPlaySession: (sessionId: string) => void
  onRequireAuth: () => void
}) {
  const detailState = useStoryDetail(storyId)
  const motionPreset = useStorylineMotion()
  const [activeTab, setActiveTab] = useState<DetailTab>("story")

  useEffect(() => {
    if (!detailState.loading && !detailState.detail && detailState.error) {
      onDeleteToLibrary()
    }
  }, [detailState.detail, detailState.error, detailState.loading, onDeleteToLibrary])

  const handleCreatePlaySession = async () => {
    if (!isAuthenticated) {
      onRequireAuth()
      return
    }

    const sessionId = await detailState.createPlaySession()
    if (sessionId) {
      onOpenPlaySession(sessionId)
    }
  }

  const handleDeleteStory = async () => {
    const confirmed = window.confirm("确定要删除这份案卷吗？这个操作不能撤销。")
    if (!confirmed) {
      return
    }
    const deleted = await detailState.deleteStory()
    if (deleted) {
      onDeleteToLibrary()
    }
  }

  if (detailState.loading) {
    return (
      <main className="mag-page">
        <div className="mag-empty">
          <div>
            <h3>正在载入案卷</h3>
            <p>正在调取正式详情与开局 framing。</p>
          </div>
        </div>
      </main>
    )
  }

  if (!detailState.detail) {
    return (
      <main className="mag-page">
        <div className="mag-error">
          <div>
            <h3>案卷暂不可见</h3>
            <p>{detailState.error ?? "这份故事当前不可访问。"}</p>
          </div>
        </div>
      </main>
    )
  }

  const detail = detailState.detail
  const featureImage = getEditorialThemeImage(detail.story.theme, 1)
  const canManageVisibility = Boolean(detail.presentation?.viewer_can_manage)
  const storyModeLabel = detail.presentation?.classification_label ?? detail.story.topology
  const opening = detail.play_overview?.opening_narration ?? detail.story.premise

  return (
    <main className="mag-page">
      <section className="mag-detail-hero">
        <div className="mag-hero__media" style={{ backgroundImage: `url("${featureImage}")` }} />
        <div className="mag-hero__veil" />
        <div className="mag-detail-hero__inner">
          <motion.div className="mag-detail-hero__copy" {...motionPreset.reveal({ y: 24, duration: 0.78 })}>
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">{detail.story.theme}</span>
              <span className="mag-chip mag-chip--gold">{detail.story.visibility === "public" ? "公开案卷" : "私密案卷"}</span>
            </div>
            <span className="mag-kicker">{detail.presentation?.dossier_ref ?? detail.story.story_id}</span>
            <h1 className="mag-stage-title">{detail.story.title}</h1>
            <div className="mag-hero__subtitle">{detail.story.one_liner}</div>
            <p>{opening}</p>
            <div className="mag-action-row">
              <button className="mag-button mag-button--primary" disabled={detailState.playLoading} onClick={() => void handleCreatePlaySession()} type="button">
                {detailState.playLoading ? "正在开启..." : isAuthenticated ? "立即入戏" : "登录后入戏"}
              </button>
              <button className="mag-button mag-button--secondary" onClick={() => onOpenLibrary(storyId)} type="button">
                返回档案库
              </button>
            </div>
          </motion.div>

          <motion.aside className="mag-detail-rail" {...motionPreset.reveal({ delay: 0.12, x: 18, y: 0, duration: 0.78 })}>
            <span className="mag-overline">案卷账本</span>
            <div className="mag-side-stack">
              <div className="mag-mini-stat">
                <span>结构标签</span>
                <strong>{storyModeLabel}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>引擎</span>
                <strong>{detail.presentation?.engine_label ?? "Relationship Drama"}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>篇幅</span>
                <strong>{detail.play_overview?.play_length_preset ?? "12_15"}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>角色 / 幕数</span>
                <strong>{`${detail.story.npc_count} 人 / ${detail.story.beat_count} 幕`}</strong>
              </div>
            </div>

            {canManageVisibility ? (
              <div className="mag-form-field">
                <label htmlFor="story-visibility">可见性</label>
                <select
                  className="mag-select"
                  disabled={detailState.visibilityLoading}
                  id="story-visibility"
                  onChange={(event) => {
                    void detailState.updateVisibility(event.target.value as StoryVisibility)
                  }}
                  value={detail.presentation?.visibility ?? detail.story.visibility}
                >
                  <option value="private">私密</option>
                  <option value="public">公开</option>
                </select>
              </div>
            ) : null}

            <div className="mag-action-row">
              {canManageVisibility ? (
                <button className="mag-button mag-button--secondary" disabled={detailState.deleteLoading} onClick={() => void handleDeleteStory()} type="button">
                  {detailState.deleteLoading ? "删除中..." : "删除案卷"}
                </button>
              ) : null}
            </div>

            {detailState.error ? <p className="editorial-error">{detailState.error}</p> : null}
          </motion.aside>
        </div>
      </section>

      <section className="mag-detail-body">
        <div className="mag-section__inner">
          <div className="mag-play-tabs">
            <button className={`mag-play-tab ${activeTab === "story" ? "is-active" : ""}`} onClick={() => setActiveTab("story")} type="button">
              案卷摘要
            </button>
            <button className={`mag-play-tab ${activeTab === "characters" ? "is-active" : ""}`} onClick={() => setActiveTab("characters")} type="button">
              人物档案
            </button>
            <button className={`mag-play-tab ${activeTab === "beats" ? "is-active" : ""}`} onClick={() => setActiveTab("beats")} type="button">
              场面梯度
            </button>
            <button className={`mag-play-tab ${activeTab === "flashcards" ? "is-active" : ""}`} onClick={() => setActiveTab("flashcards")} type="button">
              线索卡
            </button>
          </div>

          {activeTab === "story" ? (
            <div className="mag-detail-layout">
              <motion.section className="mag-panel" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
                <span className="mag-panel__eyebrow">故事主线</span>
                <h2 className="mag-panel__title">{detail.story.title}</h2>
                <p>{detail.story.premise}</p>
                <div className="mag-grid mag-grid--2">
                  <article className="mag-flashcard">
                    <span className="mag-label">关系钩子</span>
                    <strong>{detail.preview.relationship_hook ?? "等待后端提供"}</strong>
                  </article>
                  <article className="mag-flashcard">
                    <span className="mag-label">秘密引线</span>
                    <strong>{detail.preview.secret_hook ?? "等待后端提供"}</strong>
                  </article>
                </div>
                <blockquote className="mag-preview-paper">{detail.play_overview?.opening_narration ?? detail.story.one_liner}</blockquote>
              </motion.section>

              <motion.aside className="mag-side-card" {...motionPreset.inView({ delay: 0.12, x: 18, y: 0, duration: 0.58 })}>
                <div className="mag-side-stack">
                  <div className="mag-mini-stat">
                    <span>题材</span>
                    <strong>{detail.story.theme}</strong>
                  </div>
                  <div className="mag-mini-stat">
                    <span>气质</span>
                    <strong>{detail.story.tone}</strong>
                  </div>
                  <div className="mag-mini-stat">
                    <span>拓扑</span>
                    <strong>{detail.story.topology}</strong>
                  </div>
                </div>
              </motion.aside>
            </div>
          ) : null}

          {activeTab === "characters" ? (
            <motion.section className="mag-panel" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
              <span className="mag-panel__eyebrow">人物档案</span>
              <h2 className="mag-panel__title">被写进案卷的人</h2>
              <div className="mag-cast-grid">
                {detail.preview.cast_slots.map((slot, index) => (
                  <article className="mag-cast-card" key={slot.slot_label}>
                    <div className="mag-cast-card__visual">
                      <div className="mag-card-media" style={{ backgroundImage: `url("${getEditorialCharacterImage(index)}")` }} />
                      <strong>{slot.slot_label}</strong>
                    </div>
                    <p>{slot.public_role}</p>
                  </article>
                ))}
              </div>
            </motion.section>
          ) : null}

          {activeTab === "beats" ? (
            <motion.section className="mag-panel" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
              <span className="mag-panel__eyebrow">章节列表</span>
              <h2 className="mag-panel__title">关键场面梯度</h2>
              <div className="mag-beat-list">
                {detail.preview.beats.map((beat, index) => (
                  <article className="mag-beat-item" key={`${beat.title}-${index}`}>
                    <span className="mag-beat-item__index">{String(index + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{beat.title}</strong>
                      <p>{beat.goal}</p>
                    </div>
                  </article>
                ))}
              </div>
            </motion.section>
          ) : null}

          {activeTab === "flashcards" ? (
            <motion.section className="mag-panel" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
              <span className="mag-panel__eyebrow">线索卡</span>
              <h2 className="mag-panel__title">预览里已经锁定的信息</h2>
              <div className="mag-grid mag-grid--2">
                {detail.preview.flashcards.map((card) => (
                  <article className="mag-flashcard" key={card.card_id}>
                    <span className="mag-label">{card.label}</span>
                    <strong>{card.value}</strong>
                  </article>
                ))}
              </div>
            </motion.section>
          ) : null}
        </div>
      </section>
    </main>
  )
}
