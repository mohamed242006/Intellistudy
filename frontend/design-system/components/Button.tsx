import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";
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

const BASE =
  "inline-flex h-control-md items-center justify-center gap-2 rounded-md px-4 text-label whitespace-nowrap transition-colors";

/** Classes of a Button variant, shared by ButtonLink so a navigation action looks exactly like a Button. */
export function buttonClasses(variant: ButtonVariant, fullWidth = false): string {
  return [BASE, fullWidth ? "w-full" : "", VARIANT[variant]].join(" ");
}

/** A link styled as a Button (navigation is a link, UI §18 D-5). `href` is always an app route built in code. */
export function ButtonLink({ href, variant = "primary", fullWidth = false, leadingIcon, children, ...rest }: {
  href: string;
  variant?: ButtonVariant;
  fullWidth?: boolean;
  leadingIcon?: ReactNode;
  children: ReactNode;
  "aria-label"?: string;
}) {
  return (
    <Link href={href} data-variant={variant} className={buttonClasses(variant, fullWidth)} {...rest}>
      {leadingIcon}
      <span>{children}</span>
    </Link>
  );
}

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
  variant?: ButtonVariant;
  /** Loading (UI §7.1): spinner before the label, `aria-busy`, clicks ignored; the look stays the variant's own. */
  loading?: boolean;
  fullWidth?: boolean;
  leadingIcon?: ReactNode;
  children: ReactNode;
  ref?: Ref<HTMLButtonElement>;
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
      className={[buttonClasses(variant, fullWidth), "disabled:cursor-not-allowed data-[loading]:cursor-progress"].join(" ")}
    >
      {loading ? <Icon name="loader" size={16} /> : leadingIcon}
      <span>{children}</span>
    </button>
  );
}
