import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./app/app"
import "./app/theme.css"

const rootElement = document.getElementById("root")
if (!rootElement) throw new Error("root element missing")

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
