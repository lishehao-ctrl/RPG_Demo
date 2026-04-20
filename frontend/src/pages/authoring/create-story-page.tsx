import { useEffect, useState } from "react"
import { motion } from "motion/react"
import type { PlayLengthPreset, TargetGenderPref } from "../../index"
import { useCreateStoryFlow } from "../../features/authoring/create-story/model/use-create-story-flow"
import { getEditorialBackdropByView, getEditorialCharacterImage } from "../../shared/lib/editorial-assets"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

const PLAY_LENGTH_OPTIONS: Array<{ value: PlayLengthPreset; label: string }> = [
  { value: "5_8", label: "短局" },
  { value: "12_15", label: "标准" },
  { value: "15_20", label: "加长" },
  { value: "20_25", label: "旗舰" },
  { value: "30_45", label: "超级旗舰" },
]

const TARGET_GENDER_OPTIONS: Array<{ value: TargetGenderPref | null; label: string }> = [
  { value: null, label: "不限定" },
  { value: "female", label: "女性优先" },
  { value: "male", label: "男性优先" },
]

export function CreateStoryPage({
  onOpenAuthorJob,
  onOpenLibrary,
}: {
  onOpenAuthorJob: (jobId: string) => void
  onOpenLibrary: () => void
}) {
  const flow = useCreateStoryFlow()
  const motionPreset = useStorylineMotion()
  const [previewMode, setPreviewMode] = useState(false)

  useEffect(() => {
    if (flow.preview) {
      setPreviewMode(true)
    }
  }, [flow.preview])

  const handlePreview = async () => {
    const preview = await flow.requestPreview()
    if (preview) {
      setPreviewMode(true)
    }
  }

  const handleCreateAuthorJob = async () => {
    const jobId = await flow.createAuthorJob()
    if (jobId) {
      onOpenAuthorJob(jobId)
    }
  }

  const previewTheme = flow.preview?.theme.primary_theme
  const backdrop = getEditorialBackdropByView("create", previewTheme)

  return (
    <main className="mag-page">
      <section className="mag-detail-hero mag-hero--compact">
        <div className="mag-hero__media" style={{ backgroundImage: `url("${backdrop}")` }} />
        <div className="mag-hero__veil" />
        <div className="mag-detail-hero__inner">
          <motion.div className="mag-detail-hero__copy" {...motionPreset.reveal({ y: 24, duration: 0.72 })}>
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">新建案卷</span>
              <span className="mag-chip mag-chip--gold">{previewMode ? "预览确认" : "故事种子"}</span>
            </div>
            <span className="mag-kicker">Author 工作台已经切到新的 editorial 母版</span>
            <h1 className="mag-stage-title">{previewMode && flow.preview ? flow.preview.story.title : "从一句种子开始立案"}</h1>
            <p>
              {previewMode && flow.preview
                ? flow.preview.story.premise
                : "先把人物、秘密、站队压力和场景 promise 写出来。后端 preview 逻辑不变，只换成更适合上线的包装。"}
            </p>
            <div className="mag-stat-row">
              <span className="mag-stat-pill">预览先行</span>
              <span className="mag-stat-pill">不改后端契约</span>
              <span className="mag-stat-pill">编译前确认</span>
            </div>
          </motion.div>

          <motion.aside className="mag-detail-rail" {...motionPreset.reveal({ delay: 0.12, x: 20, y: 0, duration: 0.72 })}>
            <span className="mag-overline">当前配置</span>
            <div className="mag-side-stack">
              <div className="mag-mini-stat">
                <span>篇幅预设</span>
                <strong>{PLAY_LENGTH_OPTIONS.find((item) => item.value === flow.playLengthPreset)?.label ?? flow.playLengthPreset}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>选角偏好</span>
                <strong>{TARGET_GENDER_OPTIONS.find((item) => item.value === flow.targetGenderPref)?.label ?? "不限定"}</strong>
              </div>
              <div className="mag-mini-stat">
                <span>当前状态</span>
                <strong>{previewMode ? "等待确认编译" : "等待生成预览"}</strong>
              </div>
            </div>
          </motion.aside>
        </div>
      </section>

      <section className="mag-section">
        <div className="mag-section__inner">
          {!previewMode || !flow.preview ? (
            <div className="mag-form-layout">
              <motion.section className="mag-form-card" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
                <div className="mag-section__header">
                  <span className="mag-panel__eyebrow">起草台</span>
                  <h2>先写下这场关系戏会怎么失控</h2>
                  <p>种子越具体，preview 越容易给出可玩的关系钩子、秘密引线和场面梯度。</p>
                </div>

                <div className="mag-form-stack">
                  <div className="mag-form-field">
                    <label htmlFor="story-seed">故事种子</label>
                    <textarea
                      id="story-seed"
                      onChange={(event) => {
                        setPreviewMode(false)
                        flow.updateSeed(event.target.value)
                      }}
                      placeholder="例如：并购签字前夜，她被上司、旧爱和握着黑账的人同时逼到必须站队。"
                      value={flow.seed}
                    />
                  </div>

                  <div className="mag-form-field">
                    <label>篇幅预设</label>
                    <div className="mag-chip-select">
                      {PLAY_LENGTH_OPTIONS.map((option) => (
                        <button
                          className={`mag-chip-button ${flow.playLengthPreset === option.value ? "is-active" : ""}`}
                          key={option.value}
                          onClick={() => {
                            setPreviewMode(false)
                            flow.updatePlayLengthPreset(option.value)
                          }}
                          type="button"
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="mag-form-field">
                    <label>选角偏好</label>
                    <div className="mag-chip-select">
                      {TARGET_GENDER_OPTIONS.map((option) => (
                        <button
                          className={`mag-chip-button ${flow.targetGenderPref === option.value ? "is-active" : ""}`}
                          key={option.label}
                          onClick={() => {
                            setPreviewMode(false)
                            flow.updateTargetGenderPref(option.value)
                          }}
                          type="button"
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {flow.error ? <p className="editorial-error">{flow.error}</p> : null}

                  <div className="mag-action-row">
                    <button
                      className="mag-button mag-button--primary"
                      disabled={flow.previewLoading}
                      onClick={() => {
                        void handlePreview()
                      }}
                      type="button"
                    >
                      {flow.previewLoading ? "正在生成预览..." : "撰写预览"}
                    </button>
                    <button className="mag-button mag-button--secondary" onClick={onOpenLibrary} type="button">
                      返回档案库
                    </button>
                  </div>
                </div>
              </motion.section>

              <motion.aside className="mag-side-card" {...motionPreset.inView({ delay: 0.12, x: 18, y: 0, duration: 0.58 })}>
                <div className="mag-section__header">
                  <span className="mag-panel__eyebrow">写作提醒</span>
                  <h2>先给场面，不要先给设定</h2>
                </div>
                <div className="mag-side-stack">
                  <div className="mag-flashcard">
                    <span className="mag-label">人物压力</span>
                    <strong>谁在逼谁先站队</strong>
                  </div>
                  <div className="mag-flashcard">
                    <span className="mag-label">秘密引线</span>
                    <strong>哪件不能公开的东西一旦见光就会炸</strong>
                  </div>
                  <div className="mag-flashcard">
                    <span className="mag-label">场景 promise</span>
                    <strong>这场戏最适合发生在怎样的房间里</strong>
                  </div>
                </div>
              </motion.aside>
            </div>
          ) : (
            <div className="mag-form-layout">
              <motion.section className="mag-preview-paper" {...motionPreset.inView({ y: 20, duration: 0.58 })}>
                <div className="mag-section__header">
                  <span className="mag-panel__eyebrow">独家前瞻</span>
                  <h2>{flow.preview.story.title}</h2>
                  <p>{flow.preview.story.premise}</p>
                </div>

                <blockquote>{flow.preview.story.route_fantasy}</blockquote>

                <div className="mag-grid mag-grid--2">
                  <div className="mag-flashcard">
                    <span className="mag-label">关系钩子</span>
                    <strong>{flow.preview.relationship_hook ?? "待后端补全"}</strong>
                  </div>
                  <div className="mag-flashcard">
                    <span className="mag-label">秘密引线</span>
                    <strong>{flow.preview.secret_hook ?? "待后端补全"}</strong>
                  </div>
                </div>

                <div className="mag-grid mag-grid--2">
                  <div className="mag-flashcard-stack">
                    {flow.preview.flashcards.slice(0, 4).map((card) => (
                      <article className="mag-flashcard" key={card.card_id}>
                        <span className="mag-label">{card.label}</span>
                        <strong>{card.value}</strong>
                      </article>
                    ))}
                  </div>

                  <div className="mag-beat-list">
                    {flow.preview.beats.map((beat, index) => (
                      <article className="mag-beat-item" key={`${beat.title}-${index}`}>
                        <span className="mag-beat-item__index">{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <strong>{beat.title}</strong>
                          <p>{beat.goal}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>

                <div className="mag-action-row">
                  <button className="mag-button mag-button--secondary" onClick={() => setPreviewMode(false)} type="button">
                    返回编辑
                  </button>
                  <button
                    className="mag-button mag-button--primary"
                    disabled={flow.jobLoading}
                    onClick={() => {
                      void handleCreateAuthorJob()
                    }}
                    type="button"
                  >
                    {flow.jobLoading ? "正在启动编译..." : "确认并开始编译"}
                  </button>
                </div>
              </motion.section>

              <motion.aside className="mag-side-card" {...motionPreset.inView({ delay: 0.12, x: 18, y: 0, duration: 0.58 })}>
                <div className="mag-section__header">
                  <span className="mag-panel__eyebrow">人物落位</span>
                  <h2>这是谁的局</h2>
                </div>
                <div className="mag-cast-grid">
                  {flow.preview.cast_slots.slice(0, 4).map((slot, index) => (
                    <article className="mag-cast-card" key={slot.slot_label}>
                      <div className="mag-cast-card__visual">
                        <div className="mag-card-media" style={{ backgroundImage: `url("${getEditorialCharacterImage(index)}")` }} />
                        <strong>{slot.slot_label}</strong>
                      </div>
                      <p>{slot.public_role}</p>
                    </article>
                  ))}
                </div>
              </motion.aside>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
