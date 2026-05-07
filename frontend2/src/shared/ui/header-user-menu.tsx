import { type CSSProperties, useEffect, useRef, useState } from "react"
import { useAuth } from "../../app/auth-context"
import { useT } from "../lib/i18n"

type HeaderUser = {
  name: string
  world_count?: number
}

export function HeaderUserMenu({
  user,
  onLogin,
  onMyWorlds,
  onLogout,
}: {
  user?: HeaderUser | null
  onLogin?: () => void
  onMyWorlds?: () => void
  onLogout?: () => void
}) {
  const auth = useAuth()
  const t = useT()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  // Default behaviour resolves auth + nav inside the component so callers
  // can drop it in without wiring up callbacks.
  const handleLogin = () => {
    if (onLogin) onLogin()
    else window.location.hash = "#/login"
  }

  const handleMyWorlds = () => {
    if (onMyWorlds) onMyWorlds()
    else window.location.hash = "#/?mine"
  }

  const handleLogout = async () => {
    if (onLogout) {
      onLogout()
      return
    }
    try {
      await auth.logout()
    } catch {
      // best-effort
    }
    window.location.hash = "#/"
  }

  if (!user) {
    return (
      <button className="ts-btn ts-btn--ghost" onClick={handleLogin}>
        {t("header.login")}
      </button>
    )
  }

  return (
    <div ref={ref} style={humStyles.wrap} onMouseLeave={() => setOpen(false)}>
      <button
        style={{ ...humStyles.trigger, background: open ? "rgba(255,255,255,0.04)" : "transparent" }}
        onMouseEnter={() => setOpen(true)}
        onClick={() => setOpen(!open)}
      >
        <span style={humStyles.avatar}>{user.name?.[0]?.toUpperCase() || "·"}</span>
        <span style={humStyles.name}>@{user.name}</span>
        <svg
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          style={{
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform 160ms",
            color: "var(--text-faint)",
          }}
        >
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div style={humStyles.menu}>
          <button
            style={humStyles.item}
            onClick={() => {
              setOpen(false)
              handleMyWorlds()
            }}
          >
            <span>{t("header.my_worlds")}</span>
            <span style={humStyles.itemMeta}>{user.world_count ?? 0}</span>
          </button>
          <div style={humStyles.divider} />
          <button
            style={humStyles.item}
            onClick={() => {
              setOpen(false)
              void handleLogout()
            }}
          >
            <span style={{ color: "var(--text-muted)" }}>{t("header.signout")}</span>
          </button>
        </div>
      )}
    </div>
  )
}

const humStyles: Record<string, CSSProperties> = {
  wrap: { position: "relative" },
  trigger: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    height: 36,
    padding: "0 10px 0 6px",
    border: "1px solid var(--line)",
    borderRadius: 999,
    color: "var(--text)",
    fontSize: 13,
    transition: "background 160ms",
  },
  avatar: {
    width: 24,
    height: 24,
    borderRadius: 999,
    background: "var(--accent-soft)",
    color: "var(--accent)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 11,
    fontWeight: 600,
  },
  name: { fontFamily: "var(--font-ui)" },
  menu: {
    position: "absolute",
    top: "calc(100% + 6px)",
    right: 0,
    minWidth: 180,
    background: "var(--bg-elev)",
    border: "1px solid var(--line-strong)",
    borderRadius: 12,
    padding: 6,
    boxShadow: "0 16px 40px rgba(0,0,0,0.5)",
    animation: "tsFadeUp 160ms ease",
    zIndex: 10,
  },
  item: {
    width: "100%",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "9px 12px",
    borderRadius: 8,
    fontSize: 13,
    color: "var(--text)",
    transition: "background 140ms",
  },
  itemMeta: { fontSize: 11, color: "var(--text-faint)", fontVariantNumeric: "tabular-nums" },
  divider: { height: 1, background: "var(--line)", margin: "4px 0" },
}
