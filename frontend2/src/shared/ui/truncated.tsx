/**
 * <Truncated> — single-line or multi-line text with overflow ellipsis,
 * a dashed underline tell when content is actually being cut, and the
 * full text exposed via the native `title` attribute for hover.
 *
 * Why a component, not a CSS class:
 *   - We need to know AT RUNTIME whether the text is actually being
 *     truncated (to conditionally show the dashed underline). CSS alone
 *     can't observe that — we need ResizeObserver.
 *   - The underline is a state signal: "there is more to read." If we
 *     drew it unconditionally, users would learn to ignore it.
 *
 * Usage:
 *   <Truncated>{template.title}</Truncated>          // single line
 *   <Truncated lines={2}>{template.seed}</Truncated> // 2-line clamp
 *
 * Children must be a string — we copy it into the `title` attribute.
 * Composing styled chips/icons inside? Use plain CSS line-clamp; this
 * component is the simple text-only path.
 */

import {
  type CSSProperties,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react"

type TruncatedProps = {
  children: string
  lines?: number
  className?: string
  style?: CSSProperties
  /**
   * If true, force the dashed underline + tooltip on regardless of
   * whether the element is currently overflowing. Useful when the
   * upstream component already line-clamped via CSS and we just want
   * the affordance.
   */
  forceTruncated?: boolean
}

export function Truncated({
  children,
  lines = 1,
  className,
  style,
  forceTruncated = false,
}: TruncatedProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const isTruncated = useTruncationWatcher(ref, [children, lines])
  const showAffordance = forceTruncated || isTruncated

  const baseStyle: CSSProperties =
    lines === 1
      ? {
          display: "inline-block",
          maxWidth: "100%",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          verticalAlign: "bottom",
        }
      : {
          display: "-webkit-box",
          WebkitLineClamp: lines,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }

  const affordanceStyle: CSSProperties = showAffordance
    ? {
        borderBottom: "1px dashed var(--text-faint)",
        cursor: "help",
      }
    : {}

  return (
    <span
      ref={ref}
      className={className}
      title={showAffordance ? children : undefined}
      style={{ ...baseStyle, ...affordanceStyle, ...style }}
    >
      {children}
    </span>
  )
}

/**
 * Watch a ref'd element for whether its rendered text overflows its
 * box. Re-evaluates on content change AND on container resize (so a
 * narrowed grid column flips elements into truncated state).
 */
function useTruncationWatcher(
  ref: RefObject<HTMLElement | null>,
  deps: ReadonlyArray<unknown>,
): boolean {
  const [isTruncated, setIsTruncated] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => {
      // Allow 1px of slop — sub-pixel rounding produces false positives
      // on hi-dpi displays where scrollWidth = clientWidth + 0.5.
      const slop = 1
      const overflowsHorizontal = el.scrollWidth - el.clientWidth > slop
      const overflowsVertical = el.scrollHeight - el.clientHeight > slop
      setIsTruncated(overflowsHorizontal || overflowsVertical)
    }
    check()
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(check)
    observer.observe(el)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return isTruncated
}
