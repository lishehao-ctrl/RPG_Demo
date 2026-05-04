import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react"
import { AnimatePresence, motion } from "motion/react"

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost"
  size?: "md" | "lg"
}

export function Button({ variant = "primary", size = "md", className = "", ...rest }: ButtonProps) {
  return (
    <button
      className={`btn btn-${variant} btn-${size} ${className}`}
      {...rest}
    />
  )
}

export function Tag({
  children,
  tone = "default",
}: {
  children: ReactNode
  tone?: "default" | "muted" | "accent" | "warn"
}) {
  return <span className={`tag tag-${tone}`}>{children}</span>
}

export function Card({
  className = "",
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { children: ReactNode }) {
  return (
    <div className={`card ${className}`} {...rest}>
      {children}
    </div>
  )
}

export function Skeleton({ height = 18, width = "100%", className = "" }: { height?: number; width?: number | string; className?: string }) {
  return <div className={`skeleton ${className}`} style={{ height, width }} />
}

export function Drawer({
  open,
  onClose,
  children,
  side = "right",
  width = 480,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
  side?: "right" | "bottom"
  width?: number
}) {
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.div
            className="drawer-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
          />
          <motion.aside
            className={`drawer drawer-${side}`}
            style={side === "right" ? { width } : undefined}
            initial={side === "right" ? { x: width } : { y: "100%" }}
            animate={side === "right" ? { x: 0 } : { y: 0 }}
            exit={side === "right" ? { x: width } : { y: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 36 }}
          >
            {children}
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {hint ? <p>{hint}</p> : null}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return <div className="error-state">{message}</div>
}
