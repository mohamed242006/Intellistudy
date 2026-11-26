/**
 * SourceCard (UI §7.10): V, padding 16, gap 12, radius 12; header (index badge `[n]` + file name `text/label`) →
 * location `text/caption` → passage `text/body-sm` (the raw 14 px of the frame mapped to the style, UI §7.10).
 * Selected: `accent/subtle` fill, 2 px `accent/default` stroke, solid badge. Everything is plain text; line breaks are
 * kept and long words wrap. "Open in file" is not rendered (no document viewer exists).
 */
export function SourceCard({ number, fileName, location, passage, selected = false }: {
  number?: number;
  fileName: string;
  location: string;
  passage: string;
  selected?: boolean;
}) {
  return (
    <div
      data-selected={selected || undefined}
      className={`flex min-w-0 flex-col gap-3 rounded-lg p-4 ${selected ? "border-2 border-accent bg-accent-subtle" : "border border-line bg-surface"}`}
    >
      <div className="flex min-w-0 items-start gap-2">
        {number !== undefined ? (
          <span
            aria-hidden="true"
            className={`inline-flex h-[22px] min-w-6 shrink-0 items-center justify-center rounded-sm border px-1 text-caption-strong ${selected ? "border-accent bg-accent text-fg-on-accent" : "border-accent-subtle-border bg-accent-subtle text-accent-fg"}`}
          >
            [{number}]
          </span>
        ) : null}
        <span className="min-w-0 text-label break-all text-fg">{fileName}</span>
      </div>
      <p className="text-caption text-fg-secondary">{location}</p>
      <p className="text-body-sm break-words whitespace-pre-line text-fg">{passage}</p>
    </div>
  );
}
