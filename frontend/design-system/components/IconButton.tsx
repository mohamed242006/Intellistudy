import type { ButtonHTMLAttributes } from "react";
import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/placeholders";

/** IconButton (UI §7.11): 44×44, radius 8, one 20 px icon; Hover `bg/subtle`; an accessible name is required. */
export function IconButton({ icon, label, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "aria-label" | "children"> & {
  icon: IconName;
  label: string;
}) {
  return (
    <button
      type="button"
      {...rest}
      aria-label={label}
      title={label}
      className="inline-flex size-11 shrink-0 items-center justify-center rounded-md text-fg-secondary hover:bg-subtle disabled:cursor-not-allowed disabled:text-disabled-fg"
    >
      <Icon name={icon} size={20} />
    </button>
  );
}
