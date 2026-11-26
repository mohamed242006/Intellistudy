import type { ReactNode } from "react";
import { ProgressBar } from "../components/ProgressBar";

/**
 * Quiz bar (UI §7.23, §8.7.4): H gap 24, padding 16/40, 77 high, `bg/surface`, bottom border: Exit action, title block
 * (title `text/label` + subtitle `text/caption` secondary), right-aligned position text; an 8 px ProgressBar below
 * with a text equivalent.
 */
export function QuizBar({ exit, title, subtitle, position, progress, progressLabel }: {
  exit: ReactNode;
  title: string;
  subtitle: string;
  position: string;
  progress: number;
  progressLabel: string;
}) {
  return (
    <div className="border-b border-line bg-surface">
      <div className="flex min-h-[77px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-4 md:px-10">
        {exit}
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-label break-words text-fg">{title}</span>
          <span className="text-caption break-words text-fg-secondary">{subtitle}</span>
        </div>
        <span className="text-label text-fg">{position}</span>
      </div>
      <ProgressBar value={progress} label={progressLabel} className="w-full! max-w-none rounded-none" />
    </div>
  );
}
