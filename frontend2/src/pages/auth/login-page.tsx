import { type FormEvent, useState } from "react"
import { motion } from "motion/react"
import { useAuth } from "../../app/auth-context"
import { Header } from "../../shared/ui/header"
import { Button, ErrorState, Tag } from "../../shared/ui/primitives"

const USERNAME_PATTERN = /^[A-Za-z0-9_]{2,20}$/

export function LoginPage({
  next,
  onBackHome,
  onOpenCreate,
  onLoggedIn,
}: {
  next?: string
  onBackHome: () => void
  onOpenCreate: () => void
  onLoggedIn: (next?: string) => void
}) {
  const auth = useAuth()
  const [username, setUsername] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting) return
    const trimmed = username.trim()
    if (!USERNAME_PATTERN.test(trimmed)) {
      setError("用户名 2-20 字符，只能用字母、数字、下划线。")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await auth.login(trimmed)
      onLoggedIn(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后再试。")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page page-login">
      <Header onHome={onBackHome} onCreate={onOpenCreate} showCreateButton={false} />

      <main className="login-main">
        <motion.form
          className="login-form"
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          <Tag tone="accent">登录</Tag>
          <h1>用一个账号开始。</h1>
          <p className="login-form__sub">输入一个名字 — 第一次输入就是你的账号。下次输同样的名字会回到你创建过的 worlds。</p>

          <label className="login-input">
            <span>账号</span>
            <input
              type="text"
              autoComplete="username"
              autoFocus
              maxLength={20}
              placeholder="比如 shehao"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={submitting}
            />
          </label>

          <p className="login-form__hint">2–20 个字符 · 字母 / 数字 / 下划线</p>

          {error ? <ErrorState message={error} /> : null}

          <div className="login-actions">
            <Button type="submit" variant="primary" size="lg" disabled={submitting || !username.trim()}>
              {submitting ? "登录中..." : "进入"}
            </Button>
            <Button type="button" variant="ghost" onClick={onBackHome} disabled={submitting}>
              先逛逛
            </Button>
          </div>
        </motion.form>
      </main>
    </div>
  )
}
