/** Source panel copy. FIGMA = UI §8.5.4, §8.6.4. PROVISIONAL = not drawn (docs/F1_GATE.md section 6). */
export const FIGMA = {
  sourceTitle: (n: number) => `Source [${n}]`,
  exactPassage: "EXACT PASSAGE",
  surroundingText: "SURROUNDING TEXT",
  allSourcesSummary: "ALL SOURCES IN THIS SUMMARY",
  allSourcesAnswer: "ALL SOURCES IN THIS ANSWER",
} as const;

export const PROVISIONAL = {
  closeSource: "Close source",
  sourceRegion: "Source",
  sourceLabel: (n: number, file: string, location: string) => `Source ${n}: ${file}, ${location}`,
  noSelection: "Select a citation badge to see the exact passage.",
  unavailable: "This source isn’t available.",
} as const;
