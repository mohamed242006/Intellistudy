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
  duplicate_documents: "A file was selected twice. Check your selection and try again.",
  too_many_documents: "Choose at most 20 files for one summary.",
  rate_limited: "Too many summary requests in the last hour.",
  network: "You appear to be offline. Check your connection and try again.",
  not_found: "This file no longer exists.",
  session_expired: "Your session expired. Sign in again.",
  fallback: "That didn’t work. Try again.",
  database_outdated: "The server needs a database update before summaries work. Ask the administrator to apply the migrations.",
  server: "The server hit an error while handling this summary. Try again; if it keeps happening, check the server log.",
};

/** Why a summary could not be LOADED (not why it failed to generate); never "check your connection" for server errors. */
export const LOAD_PROBLEM = {
  network: { title: "You appear to be offline", body: "Check your connection and try again." },
  database_outdated: { title: "The server needs an update", body: "Its database is older than this version of IntelliStudy. An administrator must apply the database migrations." },
  server: { title: "The server couldn’t load this summary", body: "This is a server error, not your connection. Try again; if it keeps happening, check the server log." },
  session: { title: "Your session expired", body: "Sign in again to continue." },
  other: { title: "Couldn’t load this summary", body: "Try again in a moment." },
} as const;

/** Creating a summary from selected files, and the combined-summary page. */
export const COMBINED = {
  createTitle: "Create a summary",
  createBody: "Choose one file or several. One summary is written from all of them, and every statement cites the file and page it came from.",
  filesLegend: "Files to summarise",
  singleNote: "With one file, you get that file’s summary page.",
  yourSummaries: "Combined summaries",
  noCombined: "No combined summary yet.",
  fromFiles: (n: number) => (n === 1 ? "From 1 file" : `From ${n} files`),
  combinedBadge: "Combined summary",
  sourceFiles: "SOURCE FILES",
  openFile: (name: string) => `Open ${name}`,
  generatingTitle: "Writing the combined summary…",
  generatingBody: "Each file is read in full, in the order you chose. You can leave this page; the summary keeps being written.",
  delete: "Delete summary",
  deleteTitle: "Delete this summary?",
  deleteBody: "This removes the combined summary. Your files and their own summaries are not affected.",
  cancel: "Cancel",
  deleted: "Summary deleted.",
  intro: "Every statement links to the file and page it came from. Sections are grouped by file.",
  notFound: "This summary no longer exists. It is deleted when one of its files is deleted.",
} as const;
