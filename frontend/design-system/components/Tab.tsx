import Link from "next/link";

/**
 * Tab (UI §7.3) as a navigation link: the auth tabs switch between two routes, so they are links with
 * `aria-current="page"`, not an ARIA tablist. Height 44, padding 0/16, `text/label`; Selected = `accent/fg` label with a
 * 2 px `accent/default` bottom border; Hover = `bg/subtle`, radius 8.
 */
export function TabLink({ href, selected, children }: { href: string; selected: boolean; children: string }) {
  return (
    <Link
      href={href}
      aria-current={selected ? "page" : undefined}
      className={[
        "inline-flex h-control-md items-center px-4 text-label whitespace-nowrap",
        selected
          ? "text-accent-fg shadow-[inset_0_-2px_0_0_var(--color-accent)]"
          : "rounded-md text-fg-secondary hover:bg-subtle",
      ].join(" ")}
    >
      {children}
    </Link>
  );
}
