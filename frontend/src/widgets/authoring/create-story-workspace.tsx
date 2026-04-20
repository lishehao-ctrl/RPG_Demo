import type { CSSProperties, FormEvent } from "react"
import { AnimatePresence, motion } from "motion/react"
import type { AuthorPreviewResponse, PlayLengthPreset, TargetGenderPref } from "../../index"
import { STORYLINE_ASSETS, createHeroAsset } from "../../shared/lib/storyline-assets"
import { PLAY_LENGTH_OPTIONS, formatPlayLengthPreset, localizeStorylineLabel, localizeStorylineValue } from "../../shared/lib/storyline"
import { StorylineActionRow, StorylineAtmosphereTile, StorylineMetaStrip, StorylineSectionHeader, StorylineTag } from "../../shared/ui/storyline-primitives"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"
import { StreamingText } from "../../shared/ui/streaming-text"
import { StudioFooter } from "../chrome/studio-footer"

const TARGET_GENDER_OPTIONS: Array<{
  value: TargetGenderPref | null
  label: string
  description: string
}> = [
  { value: null, label: "不限", description: "先放开选角，让后端按故事张力自由匹配。" },
  { value: "female", label: "女性优先", description: "把女性偏好作为硬筛选先行，再进入后续打分。" },
  { value: "male", label: "男性优先", description: "把男性偏好作为硬筛选先行，再进入后续打分。" },
]

export function CreateStoryWorkspace({
  seed,
  playLengthPreset,
  targetGenderPref,
  preview,
  previewLoading,
  jobLoading,
  error,
  onSeedChange,
  onPlayLengthPresetChange,
  onTargetGenderPrefChange,
  onRequestPreview,
  onCreateAuthorJob,
  onOpenLibrary,
}: {
  seed: string
  playLengthPreset: PlayLengthPreset
  targetGenderPref: TargetGenderPref | null
  preview: AuthorPreviewResponse | null
  previewLoading: boolean
  jobLoading: boolean
  error: string | null
  onSeedChange: (value: string) => void
  onPlayLengthPresetChange: (value: PlayLengthPreset) => void
  onTargetGenderPrefChange: (value: TargetGenderPref | null) => void
  onRequestPreview: () => void
  onCreateAuthorJob: () => void
  onOpenLibrary: () => void
}) {
  const motionPreset = useStorylineMotion()
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onRequestPreview()
  }

  const handleStagePrimaryAction = () => {
    if (preview) {
      onCreateAuthorJob()
      return
    }
    if (!seed.trim()) {
      document.getElementById("storyline-create-form")?.scrollIntoView({ behavior: "smooth", block: "start" })
      return
    }
    onRequestPreview()
  }

  const primaryActionLabel = preview ? (jobLoading ? "开启编写..." : "开始编写") : previewLoading ? "正在生成预览..." : "生成预览"
  const previewFlashcards = preview?.flashcards.slice(0, 4) ?? []

  return (
    <div className="editorial-page editorial-page--create storyline-page storyline-page--create">
      <section
        className="storyline-create-stage"
        style={{ "--storyline-surface-image": `url("${createHeroAsset()}")` } as CSSProperties}
      >
        <div aria-hidden="true" className="storyline-create-stage__veil" />

        <motion.div className="storyline-create-stage__copy storyline-poster-stage" {...motionPreset.reveal({ y: 24, duration: 0.82 })}>
          <StorylineTag tone="danger">机密提要</StorylineTag>
          <h1 className="storyline-create-stage__title">起草新的危险关系</h1>
          <p className="storyline-create-stage__subtitle">
            从一个带压力的故事种子开始，把它编译成一份可游玩的高端案卷，里面有绯闻、诱惑，也有无法回头的选择。
          </p>
          <StorylineMetaStrip
            items={[
              { label: "默认篇幅", value: "12-15 分钟" },
              { label: "当前剪裁", value: formatPlayLengthPreset(playLengthPreset) },
              { label: "选角偏好", value: targetGenderPref === "female" ? "女性优先" : targetGenderPref === "male" ? "男性优先" : "不限" },
            ]}
          />
        </motion.div>

        <motion.aside className="storyline-create-stage__summary" {...motionPreset.reveal({ delay: 0.16, x: 28, y: 0, duration: 0.82 })}>
          <StorylineSectionHeader
            eyebrow={<StorylineTag tone={preview ? "gold" : "muted"}>{preview ? "预览案卷" : "等待种子"}</StorylineTag>}
            title={preview?.story.title ?? "下一份危险档案"}
            subtitle={preview?.story.premise ?? "第一屏先决定气味，真正的起草工作在下一屏完成。"}
          />

          <AnimatePresence mode="wait">
            <motion.div
              className="storyline-create-stage__summary-body"
              key={preview?.story.title ?? "create-draft"}
              {...motionPreset.fade({ duration: 0.34 })}
            >
              <div className="storyline-create-stage__summary-lead">
                <span className="storyline-field-label">暂定标题</span>
                <strong>
                  {preview?.story.title ? <StreamingText delayMs={60} speedMs={16} text={preview.story.title} /> : "案卷尚未成形"}
                </strong>
              </div>

              <div className="storyline-create-stage__summary-text">
                <div>
                  <span className="storyline-field-label">故事前提</span>
                  <p>{preview?.story.premise ?? "先在下一屏写下故事种子，再回到这里生成第一版预览。"}</p>
                </div>
                <div>
                  <span className="storyline-field-label">气质</span>
                  <p>{preview?.story.tone ? localizeStorylineValue(preview.story.tone) : "等待案卷归档"}</p>
                </div>
                <div>
                  <span className="storyline-field-label">路线幻想</span>
                  <p>{preview?.story.route_fantasy ?? "等后端先把这份案卷的关系幻想归档出来。"}</p>
                </div>
              </div>

              <StorylineMetaStrip
                items={[
                  { label: "篇幅", value: formatPlayLengthPreset(preview?.play_length_preset ?? playLengthPreset) },
                  { label: "人物", value: `${preview?.structure.expected_npc_count ?? "--"} 位` },
                  { label: "章节", value: `${preview?.structure.expected_beat_count ?? "--"} 章` },
                ]}
              />

              {previewFlashcards.length > 0 ? (
                <div className="storyline-chip-grid">
                  {previewFlashcards.map((card) => (
                    <StorylineTag key={card.card_id} tone={card.kind === "stable" ? "gold" : "default"}>
                      {localizeStorylineLabel(card.label)}：{localizeStorylineValue(card.value)}
                    </StorylineTag>
                  ))}
                </div>
              ) : null}
            </motion.div>
          </AnimatePresence>

          <StorylineActionRow>
            <motion.button
              className="studio-button studio-button--primary"
              disabled={preview ? jobLoading : previewLoading}
              onClick={handleStagePrimaryAction}
              type="button"
              whileHover={motionPreset.hoverLift}
              whileTap={motionPreset.tapPress}
            >
              {primaryActionLabel}
            </motion.button>
            <motion.button
              className="studio-button studio-button--secondary"
              onClick={preview ? onRequestPreview : onOpenLibrary}
              type="button"
              whileHover={motionPreset.hoverLift}
              whileTap={motionPreset.tapPress}
            >
              {preview ? "刷新预览" : "浏览档案库"}
            </motion.button>
          </StorylineActionRow>

          {error ? <p className="editorial-error">{error}</p> : null}
        </motion.aside>
      </section>

      <section className="storyline-create-workbench">
        <motion.form
          className="storyline-panel storyline-create-form"
          id="storyline-create-form"
          onSubmit={handleSubmit}
          {...motionPreset.inView({ y: 22, duration: 0.62 })}
        >
          <StorylineSectionHeader
            eyebrow={<StorylineTag tone="muted">故事种子</StorylineTag>}
            title="写下这场关系戏的第一记挑衅"
            subtitle="用一两句话交代主角、社交场域，以及那个会让所有人变脸的秘密。"
          />

          <label className="storyline-input-block" htmlFor="story-seed-input">
            <span className="storyline-field-label">机密简报</span>
            <textarea
              aria-label="故事种子"
              className="storyline-seed-input"
              id="story-seed-input"
              onChange={(event) => onSeedChange(event.target.value)}
              placeholder="例：董事会前夜，她被上司、旧爱和掌握黑账的人一起逼到必须公开站队。"
              rows={8}
              value={seed}
            />
          </label>

          <div className="storyline-create-actions">
            <StorylineActionRow>
              <motion.button
                className="studio-button studio-button--primary"
                disabled={preview ? jobLoading : previewLoading}
                onClick={preview ? onCreateAuthorJob : undefined}
                type={preview ? "button" : "submit"}
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
              >
                {primaryActionLabel}
              </motion.button>
              <motion.button
                className="studio-button studio-button--secondary"
                onClick={preview ? onRequestPreview : onOpenLibrary}
                type="button"
                whileHover={motionPreset.hoverLift}
                whileTap={motionPreset.tapPress}
              >
                {preview ? "刷新预览" : "浏览档案库"}
              </motion.button>
            </StorylineActionRow>
          </div>
        </motion.form>

        <div className="storyline-create-side-column">
          <motion.section className="storyline-panel storyline-length-panel" {...motionPreset.inView({ delay: 0.08, y: 22, duration: 0.62 })}>
            <StorylineSectionHeader
              eyebrow={<StorylineTag tone="muted">篇幅选择</StorylineTag>}
              title="决定这份案卷要烧多久"
              subtitle="篇幅越长，关系网越大，章节越多，也越有空间让失控在引爆前慢慢发酵。"
            />

            <div className="storyline-length-grid" role="list">
              {PLAY_LENGTH_OPTIONS.map((option) => (
                <motion.button
                  key={option.value}
                  className={`storyline-length-option ${playLengthPreset === option.value ? "is-active" : ""}`}
                  onClick={() => onPlayLengthPresetChange(option.value)}
                  type="button"
                  whileHover={motionPreset.hoverLift}
                  whileTap={motionPreset.tapPress}
                >
                  <span className="storyline-length-option__label">{option.label}</span>
                  <strong>{option.minutesLabel}</strong>
                  <p>{option.descriptor}</p>
                </motion.button>
              ))}
            </div>
          </motion.section>

          <motion.section className="storyline-panel storyline-length-panel" {...motionPreset.inView({ delay: 0.11, y: 22, duration: 0.62 })}>
            <StorylineSectionHeader
              eyebrow={<StorylineTag tone="muted">选角预筛</StorylineTag>}
              title="把角色性别偏好先交给后端硬筛"
              subtitle="这不是前端装饰项。当前稳定后端已经支持 `target_gender_pref`，前端入口要直接把这个业务约束带进去。"
            />

            <div className="storyline-length-grid" role="list">
              {TARGET_GENDER_OPTIONS.map((option) => (
                <motion.button
                  key={option.label}
                  className={`storyline-length-option ${targetGenderPref === option.value ? "is-active" : ""}`}
                  onClick={() => onTargetGenderPrefChange(option.value)}
                  type="button"
                  whileHover={motionPreset.hoverLift}
                  whileTap={motionPreset.tapPress}
                >
                  <span className="storyline-length-option__label">角色偏好</span>
                  <strong>{option.label}</strong>
                  <p>{option.description}</p>
                </motion.button>
              ))}
            </div>
          </motion.section>

          <motion.aside className="storyline-panel storyline-create-note" {...motionPreset.inView({ delay: 0.14, y: 22, duration: 0.62 })}>
            <StorylineAtmosphereTile
              asset={STORYLINE_ASSETS.backgrounds.corridorShadow}
              compact
              eyebrow="后台走廊"
              summary="很多故事还没写下来，风声就已经先穿过了门缝。"
              title="委托总在夜里先走漏半句"
            />
          </motion.aside>
        </div>
      </section>

      <StudioFooter />
    </div>
  )
}
