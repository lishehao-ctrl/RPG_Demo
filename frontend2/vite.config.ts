import { defineConfig, loadEnv } from "vite"
import react from "@vitejs/plugin-react-swc"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const backendTarget = env.VITE_BACKEND_PROXY_TARGET || env.VITE_API_BASE_URL || "http://127.0.0.1:8000"

  return {
    plugins: [react()],
    server: {
      port: 5174,
      proxy: {
        "^/(health|me|auth|author|stories|play|benchmark)": {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
