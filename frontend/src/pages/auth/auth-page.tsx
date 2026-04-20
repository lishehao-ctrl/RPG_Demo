import { useEffect, useState } from "react"
import { motion } from "motion/react"
import { useAuth } from "../../app/providers/auth-provider"
import { getEditorialBackdropByView } from "../../shared/lib/editorial-assets"
import { toErrorMessage } from "../../shared/lib/errors"
import { useStorylineMotion } from "../../shared/ui/storyline-motion"

export function AuthPage({
  mode,
  nextHash,
  onResolveAuth,
  onOpenLibrary,
}: {
  mode: "login" | "register"
  nextHash?: string
  onResolveAuth: (nextHash?: string) => void
  onOpenLibrary: () => void
}) {
  const auth = useAuth()
  const motionPreset = useStorylineMotion()
  const [activeMode, setActiveMode] = useState<"login" | "register">(mode)
  const [displayName, setDisplayName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setActiveMode(mode)
    setError(null)
  }, [mode])

  const submit = async () => {
    setSubmitting(true)
    setError(null)
    try {
      if (activeMode === "register") {
        await auth.register({
          display_name: displayName.trim(),
          email: email.trim(),
          password,
        })
      } else {
        await auth.login({
          email: email.trim(),
          password,
        })
      }
      onResolveAuth(nextHash)
    } catch (nextError) {
      setError(toErrorMessage(nextError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="mag-page">
      <section className="mag-auth-layout">
        <motion.article className="mag-auth-stage" {...motionPreset.reveal({ y: 24, duration: 0.76 })}>
          <div className="mag-card-media" style={{ backgroundImage: `url("${getEditorialBackdropByView("auth")}")` }} />
          <div className="mag-hero__veil" />
          <div className="mag-auth-stage__content">
            <div className="mag-badge-row">
              <span className="mag-chip mag-chip--accent">身份入口</span>
              <span className="mag-chip mag-chip--gold">{nextHash ? "受限主链" : "档案库入口"}</span>
            </div>
            <span className="mag-kicker">登录后继续你的关系戏</span>
            <h1 className="mag-stage-title">{activeMode === "register" ? "建立你的案卷身份" : "登录后继续"}</h1>
            <p>
              {activeMode === "register"
                ? "注册后即可保存故事、发布案卷，并把每一场关系失控收进自己的档案库。"
                : "登录后即可继续起草案卷、追踪编译进度，并回到那场你还没走完的会话。"}
            </p>
            <div className="mag-stat-row">
              <span className="mag-stat-pill">保存案卷</span>
              <span className="mag-stat-pill">保存会话</span>
              <span className="mag-stat-pill">发布与回看</span>
            </div>
          </div>
        </motion.article>

        <motion.section className="mag-auth-card" {...motionPreset.reveal({ delay: 0.12, x: 18, y: 0, duration: 0.76 })}>
          <div className="mag-section__header">
            <span className="mag-panel__eyebrow">账户操作</span>
            <h2>{activeMode === "register" ? "创建账户" : "登录账户"}</h2>
            <p>视觉已经切到新母版，账户链路仍沿用当前后端契约和回跳逻辑。</p>
          </div>

          <div className="mag-auth-switcher" role="tablist" aria-label="认证模式">
            <button
              className={`mag-auth-switcher__button ${activeMode === "login" ? "is-active" : ""}`}
              onClick={() => setActiveMode("login")}
              type="button"
            >
              <strong>登录</strong>
              <span className="mag-auth-switcher__note">继续现有进度</span>
            </button>
            <button
              className={`mag-auth-switcher__button ${activeMode === "register" ? "is-active" : ""}`}
              onClick={() => setActiveMode("register")}
              type="button"
            >
              <strong>注册</strong>
              <span className="mag-auth-switcher__note">建立新的身份</span>
            </button>
          </div>

          <form
            className="mag-form-stack"
            onSubmit={(event) => {
              event.preventDefault()
              void submit()
            }}
          >
            {activeMode === "register" ? (
              <div className="mag-form-field">
                <label htmlFor="auth-display-name">显示名称</label>
                <input id="auth-display-name" onChange={(event) => setDisplayName(event.target.value)} type="text" value={displayName} />
              </div>
            ) : null}

            <div className="mag-form-field">
              <label htmlFor="auth-email">邮箱</label>
              <input id="auth-email" onChange={(event) => setEmail(event.target.value)} type="email" value={email} />
            </div>

            <div className="mag-form-field">
              <label htmlFor="auth-password">密码</label>
              <input id="auth-password" onChange={(event) => setPassword(event.target.value)} type="password" value={password} />
            </div>

            {error ? <p className="editorial-error">{error}</p> : null}

            <div className="mag-action-row">
              <button className="mag-button mag-button--primary" disabled={submitting} type="submit">
                {submitting ? "提交中..." : activeMode === "register" ? "创建账户" : "登录"}
              </button>
              <button className="mag-button mag-button--secondary" onClick={onOpenLibrary} type="button">
                返回档案库
              </button>
            </div>
          </form>
        </motion.section>
      </section>
    </main>
  )
}
