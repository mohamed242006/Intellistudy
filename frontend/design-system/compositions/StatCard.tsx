/**
 * Stat card (UI §7.23): V gap 4, padding 24, radius 16, `bg/surface`, 1 px `border/default`; label `text/caption-strong`
 * tertiary → value `text/h2` → note `text/caption` secondary. Only real backend values are passed in (GF0B-10).
 */
export function StatCard({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex w-[205px] max-w-full flex-col gap-1 rounded-xl border border-line bg-surface p-6">
      <p className="text-caption-strong text-fg-tertiary">{label}</p>
      <p className="text-h2 text-fg">{value}</p>
      {note ? <p className="text-caption text-fg-secondary">{note}</p> : null}
    </div>
  );
}
