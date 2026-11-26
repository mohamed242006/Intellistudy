/**
 * Summary copy. FIGMA = UI §8.5. BACKEND = fixed sentences the backend writes. PROVISIONAL = not drawn in Figma
 * (empty, generating, failed and error states; docs/F1_GATE.md section 6).
 */
export const FIGMA = {
  summaryTitle: (name: string) => `Summary: ${name}`,
  regenerate: "Regenerate",
  intro: "Every statement links to the page it came from. Select a badge to see the exact passage.",
  indexed: "Indexed",
  sources: (n: number) => (n === 1 ? "1 source" : `${n} sources`),
} as const;

export const PROVISIONAL = {
  summary: "Summary",
  generatedAt: (when: string) => `generated ${when}`,
  noSummaryTitle: "No summary yet",
  noSummaryBody: "IntelliStudy writes a summary of this file in which every statement cites the page or slide it comes from.",
  generate: "Generate summary",
  generatingTitle: "Writing the summary…",
  generatingBody: "This usually takes less than a minute. You can leave this page; the summary keeps being written.",
  regeneratingTitle: "Regenerating",
  regeneratingBody: "The current summary stays here until the new one is ready.",
  notReadyTitle: "This file isn’t ready yet",
  notReadyBody: "A summary can be written once the file has been processed.",
  failedFileTitle: "This file couldn’t be processed",
  failedFileBody: "Files that could not be processed have no summary.",
  failedTitle: "The summary couldn’t be written",
  lastRegenerationFailed: "The last regeneration failed",
  pollingStopped: "Status updates stopped.",
  pollingStoppedBody: "We couldn’t check the summary’s progress. Try again when your connection is back.",
  tryAgain: "Try again",
  loadError: "Couldn’t load this summary.",
  loadErrorBody: "Check your connection and try again.",
  range: (kind: "page" | "slide", start: number, end: number) =>
    kind === "page" ? (start === end ? `p. ${start}` : `pp. ${start}–${end}`) : start === end ? `slide ${start}` : `slides ${start}–${end}`,
  expand: (heading: string) => `${heading}`,
} as const;

/** Why a generation failed (`error_code`) or a request was refused (problem code), in fixed frontend copy. */
export const FAILURE: Readonly<Record<string, string>> = {
  llm_unavailable: "The AI service is unavailable right now. Try again later.",
  token_budget: "Your daily AI budget is used up. Try again tomorrow.",
  ungrounded: "No statement could be backed by this file’s text, so no summary was kept.",
  internal_error: "Something went wrong while writing the summary. Try again later.",
  document_not_ready: "This file isn’t ready yet. A summary can be written once it has been processed.",
  rate_limited: "Too many summary requests in the last hour.",
  network: "You appear to be offline. Check your connection and try again.",
  not_found: "This file no longer exists.",
  session_expired: "Your session expired. Sign in again.",
  fallback: "That didn’t work. Try again.",
};
