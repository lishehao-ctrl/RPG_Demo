import { createContext, type ReactNode, useContext, useMemo } from "react"
import type { FrontendApiClient } from "../api/client"
import { createHttpApiClient } from "../api/http-client"

const ApiContext = createContext<FrontendApiClient | null>(null)

const DEFAULT_BASE_URL = (() => {
  const fromEnv = (import.meta.env.VITE_API_BASE_URL ?? "").trim()
  if (fromEnv) return fromEnv
  // Use current origin so requests like /stories hit the Vite dev proxy.
  if (typeof window !== "undefined") return window.location.origin
  return ""
})()

export function ApiProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => createHttpApiClient(DEFAULT_BASE_URL), [])
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>
}

export function useApi(): FrontendApiClient {
  const ctx = useContext(ApiContext)
  if (!ctx) throw new Error("ApiProvider missing")
  return ctx
}
