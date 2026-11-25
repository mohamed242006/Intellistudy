import type { ButtonHTMLAttributes, Ref } from "react";
import { Avatar } from "./Avatar";

/**
 * User card (UI §6.2, §7.23): 60 high, padding 12, gap 12: avatar 36 + name `text/label` + subtitle `text/caption`
 * secondary. Figma draws it as static; F0-B makes it the button that opens the account menu (plan decision 11.3-5).
 */
export function UserCard({ name, subtitle, ref, namePrefix, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className" | "children"> & {
  name: string;
  subtitle: string;
  ref?: Ref<HTMLButtonElement>;
  /** Screen-reader-only words before the visible name, so the accessible name contains the visible text (WCAG 2.5.3). */
  namePrefix?: string;
}) {
  return (
    <button ref={ref} type="button" {...rest} className="flex h-[60px] w-full items-center gap-3 rounded-md p-3 text-left hover:bg-subtle">
      <Avatar name={name} />
      <span className="flex min-w-0 flex-col">
        {namePrefix ? <span className="sr-only">{namePrefix} </span> : null}
        <span className="truncate text-label text-fg">{name}</span>
        <span className="truncate text-caption text-fg-secondary">{subtitle}</span>
      </span>
    </button>
  );
}
