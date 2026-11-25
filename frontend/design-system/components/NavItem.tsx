import Link from "next/link";
import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/placeholders";

/**
 * NavItem (UI §7.17): 44 high, padding 0/12, gap 12, radius 8, icon 20 + label. Default label `text/secondary`
 * (`text/label`); Hover `bg/subtle`, label primary; Selected `accent/subtle` fill, `accent/fg` label in
 * `text/body-strong` (as drawn: the selected label is larger, UI §7.17 inconsistency kept). `aria-current="page"`.
 */
export function NavItem({ href, icon, label, selected }: { href: string; icon: IconName; label: string; selected: boolean }) {
  return (
    <Link
      href={href}
      aria-current={selected ? "page" : undefined}
      className={[
        "flex h-control-md w-full items-center gap-3 rounded-md px-3",
        selected ? "bg-accent-subtle text-body-strong text-accent-fg" : "text-label text-fg-secondary hover:bg-subtle hover:text-fg",
      ].join(" ")}
    >
      <Icon name={icon} size={20} />
      <span>{label}</span>
    </Link>
  );
}

/** Rail item (UI §6.3): 44×44, radius 8, icon 20, no visible label; the selected item has `accent/subtle` fill. */
export function RailItem({ href, icon, label, selected }: { href: string; icon: IconName; label: string; selected: boolean }) {
  return (
    <Link
      href={href}
      aria-label={label}
      title={label}
      aria-current={selected ? "page" : undefined}
      className={`flex size-11 items-center justify-center rounded-md ${selected ? "bg-accent-subtle text-accent-fg" : "text-fg-secondary hover:bg-subtle"}`}
    >
      <Icon name={icon} size={20} />
    </Link>
  );
}
