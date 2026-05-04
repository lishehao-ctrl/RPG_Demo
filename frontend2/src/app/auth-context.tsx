import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { AuthUserResponse } from "../api/contracts"
import { useApi } from "./api-context"

type AuthState = {
  loading: boolean
  user: AuthUserResponse | null
  // True when the cookie corresponds to a user we created (signed-in), false
  // when the backend is just handing us the anonymous fallback user.
  isAnonymous: boolean
  login: (username: string) => Promise<AuthUserResponse>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

const ANONYMOUS_USER_ID_PREFIX = "local-dev"
// Backend's default_actor_id starts with "local-dev" or is literally "anonymous".
// Real signed-in users get user_id like "usr_<hex>", which we recognise by the prefix.
function detectAnonymous(user: AuthUserResponse | null): boolean {
  if (!user) return true
  if (user.user_id === "anonymous") return true
  if (user.user_id.startsWith(ANONYMOUS_USER_ID_PREFIX)) return true
  return false
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const api = useApi()
  const [user, setUser] = useState<AuthUserResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const response = await api.getAuthSession()
      setUser(response.user)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (username: string) => {
      const response = await api.loginAuth({ username })
      setUser(response.user)
      if (!response.user) {
        throw new Error("Login succeeded but no user payload returned")
      }
      return response.user
    },
    [api],
  )

  const logout = useCallback(async () => {
    try {
      await api.logoutAuth()
    } catch {
      // best-effort
    }
    await refresh()
  }, [api, refresh])

  const value = useMemo<AuthState>(
    () => ({
      loading,
      user,
      isAnonymous: detectAnonymous(user),
      login,
      logout,
      refresh,
    }),
    [loading, user, login, logout, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("AuthProvider missing")
  return ctx
}
