import { useState } from "react"
import { useAuth } from "../../app/auth-context"
import { LANGUAGE_OPTIONS, useLanguage, type Lang } from "../lib/i18n"
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
  const { lang, setLang, t } = useLanguage()
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
        <LanguageToggle lang={lang} onSelect={setLang} />

        {showCreateButton ? (
          <Button variant="primary" size="md" onClick={onCreate}>
            {t("header.write_story")}
          </Button>
        ) : null}

        {auth.loading ? (
          <span className="topbar-account__hint">...</span>
        ) : auth.isAnonymous ? (
          <Button variant="ghost" size="md" onClick={handleLogin}>
            {t("header.login")}
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
                  {t("header.logout")}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </header>
  )
}

function LanguageToggle({ lang, onSelect }: { lang: Lang; onSelect: (next: Lang) => void }) {
  // Two-pill segmented control. If we add a third locale we'll switch
  // to a dropdown, but two fits inline cleanly.
  return (
    <div className="topbar-lang" role="group" aria-label="language">
      {LANGUAGE_OPTIONS.map((opt) => {
        const active = opt.value === lang
        return (
          <button
            key={opt.value}
            type="button"
            className={`topbar-lang__pill${active ? " topbar-lang__pill--active" : ""}`}
            onClick={() => onSelect(opt.value)}
            aria-pressed={active}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
