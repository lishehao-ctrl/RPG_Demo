import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./app/app"
// tokens.css carries the Tiny Stories design system: CSS variables (--bg, --accent,
// --text, --radius-*, --font-*) and a handful of utility classes (.ts-btn, .ts-tag,
// .ts-link-dashed) that every page in the v2 redesign relies on. Imported BEFORE
// theme.css so legacy theme rules can override anything that needs tweaking.
import "./app/tokens.css"
import "./app/theme.css"

const rootElement = document.getElementById("root")
if (!rootElement) throw new Error("root element missing")

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
