/**
 * Display formats (UI §18 D-18, D-19, D-21). Pure functions; the clock is a parameter so tests are deterministic.
 */

/** Sizes in decimal units: "3.1 MB" (one decimal, UI D-18); smaller files in KB or bytes. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1_000) return `${Math.round(bytes / 1_000)} KB`;
  return `${bytes} B`;
}

/** "1 file" / "7 files" (UI D-19). */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/** Greeting date: "Thursday, 22 October" (weekday, day, month; no year). */
export function greetingDate(now: Date): string {
  const weekday = now.toLocaleDateString("en-GB", { weekday: "long" });
  const dayMonth = now.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
  return `${weekday}, ${dayMonth}`;
}

/** "Good morning" before 12:00, "Good afternoon" before 18:00, otherwise "Good evening" (local time). */
export function greeting(now: Date): string {
  const hour = now.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** First word of a display name, for the greeting. */
export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? "";
}

/** Avatar initials (D-21): first letters of the first and last words; one word → its first two letters. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "";
  if (words.length === 1) return Array.from(words[0]!).slice(0, 2).join("").toUpperCase();
  return `${Array.from(words[0]!)[0] ?? ""}${Array.from(words[words.length - 1]!)[0] ?? ""}`.toUpperCase();
}

/** Relative time (D-18): "just now", "5 minutes ago", "2 hours ago", "Yesterday", "3 days ago", then a date. */
export function relativeTime(iso: string | null, now: Date): string {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const seconds = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${plural(minutes, "minute")} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${plural(hours, "hour")} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
