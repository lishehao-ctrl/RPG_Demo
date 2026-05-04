import { useEffect, useState } from "react"

export function StreamingText({
  text,
  speedMs = 22,
  delayMs = 0,
  className = "",
}: {
  text: string
  speedMs?: number
  delayMs?: number
  className?: string
}) {
  const [shown, setShown] = useState("")

  useEffect(() => {
    setShown("")
    if (!text) return

    let index = 0
    let cancelled = false

    const startTimer = window.setTimeout(() => {
      const interval = window.setInterval(() => {
        if (cancelled) return
        index += 1
        setShown(text.slice(0, index))
        if (index >= text.length) {
          window.clearInterval(interval)
        }
      }, Math.max(8, speedMs))

      return () => window.clearInterval(interval)
    }, delayMs)

    return () => {
      cancelled = true
      window.clearTimeout(startTimer)
    }
  }, [text, speedMs, delayMs])

  return <span className={className}>{shown}</span>
}
