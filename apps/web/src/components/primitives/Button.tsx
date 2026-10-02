/**
 * Buttons.
 *
 * `variant="harness"` exists so that no control which acts on the *simulation*
 * can be mistaken for a physical actuator. Labels carry that distinction in
 * words, not just in styling.
 */
import type { ButtonHTMLAttributes, ReactNode } from "react"

type Variant = "default" | "primary" | "harness" | "danger" | "ghost"

const VARIANT_CLASS: Record<Variant, string> = {
  default: "border-rule bg-raised text-ink hover:border-rule-strong",
  primary: "border-teal bg-teal-wash text-teal hover:bg-teal-wash/70",
  harness: "border-amber bg-amber-wash text-amber hover:bg-amber-wash/70",
  danger: "border-red bg-red-wash text-red hover:bg-red-wash/70",
  ghost: "border-transparent bg-transparent text-ink-2 hover:text-ink",
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  children: ReactNode
}

export function Button({ variant = "default", className = "", children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-1.5 border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:border-rule disabled:bg-transparent disabled:text-ink-4 ${VARIANT_CLASS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

export function IconButton({
  label,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex h-[24px] w-[24px] items-center justify-center border border-rule bg-raised text-ink-2 hover:border-rule-strong hover:text-ink disabled:text-ink-4 ${className}`}
      {...rest}
    >
      {children}
    </button>
  )
}

/**
 * Toggle used for map layers. Rendered as a real checkbox input so keyboard and
 * screen-reader behaviour is native, with the swatch carrying the layer's own
 * colour/paint mark.
 */
export function LayerToggle({
  checked,
  onChange,
  label,
  swatch,
  description,
}: {
  checked: boolean
  onChange: () => void
  label: string
  swatch: string
  description: string
}) {
  return (
    <label className="flex cursor-pointer items-start gap-1.5 px-1.5 py-1 hover:bg-raised">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="mt-[3px] h-[11px] w-[11px] shrink-0 accent-[var(--nm-teal)]"
      />
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-[11px] text-ink-2">
          <span aria-hidden="true" className={`inline-block h-[8px] w-[8px] shrink-0 border ${swatch}`} />
          {label}
        </span>
        <span className="block text-[10px] leading-tight text-ink-3">{description}</span>
      </span>
    </label>
  )
}