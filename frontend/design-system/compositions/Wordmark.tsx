import { Icon } from "../icons/Icon";

/** Wordmark (UI §7.23): 32×32 mark (radius 8, `accent/default`, `icon/book` 18 in on-accent) + "IntelliStudy" `text/title`, gap 12. */
export function Wordmark({ markOnly = false }: { markOnly?: boolean } = {}) {
  if (markOnly) {
    return (
      <span className="flex size-8 items-center justify-center rounded-md bg-accent text-fg-on-accent">
        <Icon name="book" size={18} />
      </span>
    );
  }
  return (
    <div className="flex h-8 items-center gap-3">
      <span className="flex size-8 items-center justify-center rounded-md bg-accent text-fg-on-accent">
        <Icon name="book" size={18} />
      </span>
      <span className="text-title text-fg">IntelliStudy</span>
    </div>
  );
}
