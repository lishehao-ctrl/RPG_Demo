import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./app/app"
import "./app/styles.css"
import "./app/storyline-theme.css"
import "./app/concept-review.css"
import "./app/editorial-live.css"

const rootElement = document.getElementById("root")

if (!rootElement) {
  throw new Error("Unable to find root element")
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
