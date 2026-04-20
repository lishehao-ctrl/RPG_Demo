import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react"
import type { AuthLoginRequest, AuthRegisterRequest, AuthSessionResponse, AuthUserResponse } from "../../index"
import { getDefaultApiClient } from "../config/api-client"

type AuthContextValue = {
  loading: boolean
  authenticated: boolean
  user: AuthUserResponse | null
  refreshSession: () => Promise<AuthSessionResponse>
  login: (request: AuthLoginRequest) => Promise<AuthSessionResponse>
  register: (request: AuthRegisterRequest) => Promise<AuthSessionResponse>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => getDefaultApiClient(), [])
  const conceptRoute = typeof window !== "undefined" && window.location.hash.startsWith("#/concept/")
  const [loading, setLoading] = useState(true)
  const [session, setSession] = useState<AuthSessionResponse>({
    authenticated: false,
    user: null,
  })

  const refreshSession = async () => {
    const nextSession = await client.getAuthSession()
    setSession(nextSession)
    return nextSession
  }

  useEffect(() => {
    let active = true

    const loadSession = async () => {
      if (conceptRoute) {
        if (active) {
          setSession({
            authenticated: false,
            user: null,
          })
          setLoading(false)
        }
        return
      }

      try {
        const nextSession = await client.getAuthSession()
        if (active) {
          setSession(nextSession)
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void loadSession()

    return () => {
      active = false
    }
  }, [client, conceptRoute])

  const value = useMemo<AuthContextValue>(
    () => ({
      loading,
      authenticated: session.authenticated,
      user: session.user,
      refreshSession,
      login: async (request) => {
        const nextSession = await client.loginAuth(request)
        setSession(nextSession)
        return nextSession
      },
      register: async (request) => {
        const nextSession = await client.registerAuth(request)
        setSession(nextSession)
        return nextSession
      },
      logout: async () => {
        await client.logoutAuth()
        setSession({
          authenticated: false,
          user: null,
        })
      },
    }),
    [client, loading, session.authenticated, session.user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error("Auth context is not available.")
  }
  return context
}
