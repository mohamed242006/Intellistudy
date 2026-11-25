/** Return-path handling for /signin?next=… : only same-origin paths, never another origin (open-redirect guard). */

const AUTH_PATHS = new Set(["/signin", "/signup"]);

export function safeNextPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  try {
    const url = new URL(raw, "http://intellistudy.invalid");
    if (url.origin !== "http://intellistudy.invalid" || AUTH_PATHS.has(url.pathname)) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
