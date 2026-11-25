import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "../icons/Icon";

/** Button (UI §7.1). Height 44, padding 0/16, gap 8, radius 8, `text/label`. Hover, Focus and Disabled come from CSS. */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-fg-on-accent hover:bg-accent-hover active:bg-accent-pressed disabled:bg-disabled-bg disabled:text-disabled-fg",
  secondary:
    "border border-line-strong bg-surface text-fg hover:bg-subtle disabled:border-line disabled:bg-disabled-bg disabled:text-disabled-fg",
  ghost: "bg-transparent text-accent-fg hover:bg-accent-subtle disabled:bg-transparent disabled:text-disabled-fg",
  danger: "bg-danger-solid text-fg-on-accent hover:bg-danger-fg disabled:bg-disabled-bg disabled:text-disabled-fg",
};

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
  variant?: ButtonVariant;
  /** Loading (UI §7.1): spinner before the label, `aria-busy`, clicks ignored; the look stays the variant's own. */
  loading?: boolean;
  fullWidth?: boolean;
  leadingIcon?: ReactNode;
  children: ReactNode;
};

export function Button({ variant = "primary", loading = false, fullWidth = false, leadingIcon, children, onClick, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      aria-busy={loading || undefined}
      data-variant={variant}
      data-loading={loading || undefined}
      onClick={(event) => {
        if (loading) {
          event.preventDefault();
          return;
        }
        onClick?.(event);
      }}
      className={[
        "inline-flex h-control-md items-center justify-center gap-2 rounded-md px-4 text-label whitespace-nowrap",
        "transition-colors disabled:cursor-not-allowed data-[loading]:cursor-progress",
        fullWidth ? "w-full" : "",
        VARIANT[variant],
      ].join(" ")}
    >
      {loading ? <Icon name="loader" size={16} /> : leadingIcon}
      <span>{children}</span>
    </button>
  );
}
