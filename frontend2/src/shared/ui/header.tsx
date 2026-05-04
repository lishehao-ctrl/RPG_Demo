import { useState } from "react"
import { useAuth } from "../../app/auth-context"
import { Button } from "./primitives"

export function Header({
  onHome,
  onCreate,
  showCreateButton = true,
}: {
  onHome: () => void
  onCreate: () => void
  showCreateButton?: boolean
}) {
  const auth = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  const handleLogin = () => {
    // Hash routes are app-internal; jumping via location.hash keeps Header
    // independent of the navigate prop chain.
    window.location.hash = "#/login"
  }

  return (
    <header className="topbar">
      <button className="brand" onClick={onHome} type="button">
        <span className="brand-mark">·</span>
        <strong>Tiny Stories</strong>
      </button>

      <div className="topbar-actions">
        {showCreateButton ? (
          <Button variant="primary" size="md" onClick={onCreate}>
            写一个故事
          </Button>
        ) : null}

        {auth.loading ? (
          <span className="topbar-account__hint">...</span>
        ) : auth.isAnonymous ? (
          <Button variant="ghost" size="md" onClick={handleLogin}>
            登录
          </Button>
        ) : (
          <div className="topbar-account">
            <button
              type="button"
              className="topbar-account__pill"
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span className="topbar-account__avatar">{auth.user?.display_name.slice(0, 1).toUpperCase()}</span>
              <span className="topbar-account__name">{auth.user?.display_name}</span>
            </button>
            {menuOpen ? (
              <div className="topbar-account__menu" onMouseLeave={() => setMenuOpen(false)}>
                <button
                  type="button"
                  className="topbar-account__menu-item"
                  onClick={() => {
                    void auth.logout()
                    setMenuOpen(false)
                  }}
                >
                  退出登录
                </button>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </header>
  )
}
