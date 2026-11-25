import type { ReactNode } from "react";
import { Icon } from "../icons/Icon";
import type { IconName } from "../icons/placeholders";

/**
 * EmptyState (UI §7.15): Page (max 560 wide, padding 64) or Panel (padding 32). 64 px icon bubble (`bg/subtle`,
 * icon 28) → title `text/h3` → body `text/body` secondary → one action.
 */
export function EmptyState({ size, icon, title, body, action, headingLevel = 2 }: {
  size: "page" | "panel";
  icon: IconName;
  title: string;
  body: string;
  action?: ReactNode;
  headingLevel?: 1 | 2 | 3;
}) {
  const Heading = (["h1", "h2", "h3"] as const)[headingLevel - 1]!;
  return (
    <div
      data-size={size}
      className={`mx-auto flex w-full flex-col items-center gap-4 text-center ${size === "page" ? "max-w-[560px] p-16 max-md:p-6" : "max-w-[340px] p-8"}`}
    >
      <span className="flex size-16 items-center justify-center rounded-full bg-subtle">
        <Icon name={icon} size={28} />
      </span>
      <Heading className="text-h3 text-fg">{title}</Heading>
      <p className="text-body text-fg-secondary">{body}</p>
      {action ? <div className="pt-2">{action}</div> : null}
    </div>
  );
}
