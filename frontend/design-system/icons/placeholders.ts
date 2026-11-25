/**
 * VISUAL BLOCKER (UI A8 / plan 11.3-9): the 30 Figma icon components (`icon/*`, 24×24 grid, 2 px stroke) have not been
 * exported to the repository yet. No glyph is drawn and no third-party icon stands in for them: each use renders an
 * empty box of the exact Figma size, marked `data-icon-placeholder`, so layout matches and the gap stays visible.
 * Replace each entry with the exported SVG; tests list every placeholder still in use.
 */

export const ICON_NAMES = [
  "book", "home", "chart", "target", "sliders", "shield", "file", "lock", "check", "checkCircle", "x2", "x", "alert",
  "info", "scan", "upload", "plus", "retry", "external", "trash", "send", "loader", "search", "chevronRight",
  "chevronDown", "layers", "quiz", "message", "flame", "user",
] as const;

export type IconName = (typeof ICON_NAMES)[number];

/** Icons F0-A places on screen (all placeholders until the SVG export lands). */
export const F0A_ICON_USES: ReadonlyArray<{ icon: IconName; size: number; where: string }> = [
  { icon: "book", size: 18, where: "Wordmark mark (on-accent)" },
  { icon: "book", size: 20, where: "Auth trust point 1" },
  { icon: "file", size: 20, where: "Auth trust point 2" },
  { icon: "lock", size: 20, where: "Auth trust point 3" },
  { icon: "alert", size: 20, where: "Input Error, trailing icon in the field" },
  { icon: "alert", size: 16, where: "Input Error, leading icon in the helper row" },
  { icon: "alert", size: 20, where: "Notice Warning tone, leading icon" },
  { icon: "info", size: 20, where: "Notice Info tone, leading icon" },
  { icon: "loader", size: 16, where: "Button Loading spinner" },
];
