import { initials } from "@/lib/format/format";

/** Avatar (UI §7.23): 36×36 circle, `accent/subtle`, initials `text/caption-strong` `accent/fg` (D-21). Decorative. */
export function Avatar({ name }: { name: string }) {
  return (
    <span aria-hidden="true" className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-caption-strong text-accent-fg">
      {initials(name)}
    </span>
  );
}
