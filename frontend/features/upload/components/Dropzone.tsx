"use client";

import { useRef, useState } from "react";
import { Button } from "@/design-system/components/Button";
import { Icon } from "@/design-system/icons/Icon";
import { FIGMA } from "@/features/documents/strings";
import { ACCEPT_ATTRIBUTE } from "../validation";

/**
 * Upload dropzone (spec §3.5, §8.2.1): `bg/surface` with a 2 px dashed (8/6) `border/strong` stroke drawn inside, radius 16,
 * padding 32, centred: 56 circle with the upload icon, title, limits, "Choose files". Drag-over: `accent/subtle` fill and
 * an `accent/default` stroke, and the icon bubble lifts; the change is colour and transform only (no layout shift). Dropping files is a pointer
 * convenience; "Choose files" is the keyboard path (GF0B-27). The file input is hidden and never focusable on its own.
 */
export function Dropzone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      data-testid="dropzone"
      data-drag-over={over || undefined}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        const files = Array.from(event.dataTransfer.files);
        if (files.length) onFiles(files);
      }}
      className="group relative flex min-h-[248px] flex-col items-center justify-center gap-4 rounded-xl bg-surface p-6 text-center transition-colors duration-200 data-[drag-over]:bg-accent-subtle sm:p-8"
    >
      <svg aria-hidden="true" className="pointer-events-none absolute inset-0 size-full overflow-visible">
        <rect
          x="1"
          y="1"
          rx="15"
          ry="15"
          fill="none"
          strokeWidth="2"
          strokeDasharray="8 6"
          className="transition-[stroke] duration-200"
          style={{ width: "calc(100% - 2px)", height: "calc(100% - 2px)", stroke: over ? "var(--color-accent)" : "var(--color-line-strong)" }}
        />
      </svg>
      <span className="flex size-14 items-center justify-center rounded-full bg-accent-subtle text-accent-fg transition-transform duration-200 group-data-[drag-over]:-translate-y-1 group-data-[drag-over]:bg-surface">
        <Icon name="upload" size={24} />
      </span>
      <p className="text-title text-fg">{FIGMA.dropTitle}</p>
      <p className="text-body-sm text-fg-secondary">{FIGMA.dropHelper}</p>
      <Button onClick={() => input.current?.click()}>{FIGMA.chooseFiles}</Button>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT_ATTRIBUTE}
        data-testid="file-input"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = ""; // the same file can be chosen again later
          if (files.length) onFiles(files);
        }}
      />
    </div>
  );
}
