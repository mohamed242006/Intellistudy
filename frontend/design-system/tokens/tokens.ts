/**
 * Design tokens, exactly as recorded from the Figma variables in docs/figma_ui_context.md (UI §4).
 * This file is the single source; `npm run tokens` writes tokens.css from it, and tests check both against the
 * tables in the context document (gate GF0A-01). Components never use primitives directly (UI §3.2).
 */

export const primitives = {
  accent: { 50: "#ECF7FA", 100: "#D3EEF4", 200: "#A9DCE8", 300: "#78C4D7", 400: "#3FA5BF", 500: "#1B8AA6", 600: "#0F6F8A", 700: "#0B5970", 800: "#0A4457", 900: "#082F3D" },
  neutral: { 0: "#FFFFFF", 50: "#F6F8F9", 100: "#EDF0F2", 200: "#DDE2E6", 300: "#C3CBD1", 400: "#9AA5AD", 500: "#6B7782", 600: "#4F5A64", 700: "#38424B", 800: "#232B33", 850: "#1A2027", 900: "#131920", 950: "#0D1116" },
  green: { 50: "#E8F5EE", 300: "#86CFA6", 400: "#4DB37E", 500: "#2E9560", 600: "#1E7A4C", 700: "#17603B", 900: "#0F3D26" },
  amber: { 50: "#FDF4E3", 300: "#F0C675", 400: "#E0A33A", 500: "#B7791A", 600: "#A15C07", 700: "#7C4705", 900: "#4A2B04" },
  red: { 50: "#FCECEC", 300: "#F2A29B", 400: "#E5675C", 500: "#C9473B", 600: "#B42318", 700: "#8F1B12", 900: "#4F120D" },
} as const;

type Ramp = keyof typeof primitives;
type Ref = `${Ramp}/${string}`;

/** Semantic token -> [light primitive, dark primitive] (UI §4.1.2). */
export const semantic: Record<string, readonly [Ref, Ref]> = {
  "bg/canvas": ["neutral/50", "neutral/950"],
  "bg/surface": ["neutral/0", "neutral/900"],
  "bg/raised": ["neutral/0", "neutral/850"],
  "bg/subtle": ["neutral/100", "neutral/800"],
  "bg/scrim": ["neutral/950", "neutral/950"],
  "border/default": ["neutral/200", "neutral/700"],
  "border/strong": ["neutral/300", "neutral/600"],
  "text/primary": ["neutral/900", "neutral/50"],
  "text/secondary": ["neutral/600", "neutral/300"],
  "text/tertiary": ["neutral/500", "neutral/400"],
  "text/on-accent": ["neutral/0", "neutral/950"],
  "text/link": ["accent/700", "accent/300"],
  "accent/default": ["accent/600", "accent/400"],
  "accent/hover": ["accent/700", "accent/300"],
  "accent/pressed": ["accent/800", "accent/200"],
  "accent/subtle": ["accent/50", "accent/900"],
  "accent/subtle-border": ["accent/200", "accent/700"],
  "accent/fg": ["accent/700", "accent/300"],
  "focus/ring": ["accent/600", "accent/300"],
  "disabled/bg": ["neutral/100", "neutral/800"],
  "disabled/fg": ["neutral/400", "neutral/500"],
  "success/bg": ["green/50", "green/900"],
  "success/border": ["green/300", "green/700"],
  "success/fg": ["green/700", "green/300"],
  "success/solid": ["green/600", "green/400"],
  "warning/bg": ["amber/50", "amber/900"],
  "warning/border": ["amber/300", "amber/700"],
  "warning/fg": ["amber/700", "amber/300"],
  "warning/solid": ["amber/600", "amber/400"],
  "danger/bg": ["red/50", "red/900"],
  "danger/border": ["red/300", "red/700"],
  "danger/fg": ["red/700", "red/300"],
  "danger/solid": ["red/600", "red/400"],
  "mastery/not-started": ["neutral/500", "neutral/500"],
  "mastery/weak": ["red/500", "red/400"],
  "mastery/learning": ["amber/500", "amber/400"],
  "mastery/proficient": ["accent/500", "accent/400"],
  "mastery/mastered": ["green/500", "green/400"],
};

/** Tailwind colour name for each semantic token (classes such as `bg-canvas`, `text-fg`, `border-line`). */
export const tailwindName: Record<string, string> = {
  "bg/canvas": "canvas", "bg/surface": "surface", "bg/raised": "raised", "bg/subtle": "subtle", "bg/scrim": "scrim",
  "border/default": "line", "border/strong": "line-strong",
  "text/primary": "fg", "text/secondary": "fg-secondary", "text/tertiary": "fg-tertiary",
  "text/on-accent": "fg-on-accent", "text/link": "fg-link",
  "accent/default": "accent", "accent/hover": "accent-hover", "accent/pressed": "accent-pressed",
  "accent/subtle": "accent-subtle", "accent/subtle-border": "accent-subtle-border", "accent/fg": "accent-fg",
  "focus/ring": "focus-ring", "disabled/bg": "disabled-bg", "disabled/fg": "disabled-fg",
  "success/bg": "success-bg", "success/border": "success-border", "success/fg": "success-fg", "success/solid": "success-solid",
  "warning/bg": "warning-bg", "warning/border": "warning-border", "warning/fg": "warning-fg", "warning/solid": "warning-solid",
  "danger/bg": "danger-bg", "danger/border": "danger-border", "danger/fg": "danger-fg", "danger/solid": "danger-solid",
  "mastery/not-started": "mastery-not-started", "mastery/weak": "mastery-weak", "mastery/learning": "mastery-learning",
  "mastery/proficient": "mastery-proficient", "mastery/mastered": "mastery-mastered",
};

/** Text styles (UI §4.2): px size / line-height, weight, letter-spacing in Figma percent. */
export const textStyles = {
  display: { size: 40, lineHeight: 48, weight: 700, letterSpacingPct: -1 },
  h1: { size: 32, lineHeight: 40, weight: 600, letterSpacingPct: -0.5 },
  h2: { size: 24, lineHeight: 32, weight: 600, letterSpacingPct: -0.25 },
  h3: { size: 20, lineHeight: 28, weight: 600, letterSpacingPct: 0 },
  title: { size: 16, lineHeight: 24, weight: 600, letterSpacingPct: 0 },
  "body-lg": { size: 18, lineHeight: 28, weight: 400, letterSpacingPct: 0 },
  body: { size: 16, lineHeight: 24, weight: 400, letterSpacingPct: 0 },
  "body-strong": { size: 16, lineHeight: 24, weight: 500, letterSpacingPct: 0 },
  "body-sm": { size: 14, lineHeight: 20, weight: 400, letterSpacingPct: 0 },
  label: { size: 14, lineHeight: 20, weight: 500, letterSpacingPct: 0 },
  caption: { size: 12, lineHeight: 16, weight: 400, letterSpacingPct: 0 },
  "caption-strong": { size: 12, lineHeight: 16, weight: 600, letterSpacingPct: 0.2 },
} as const;

/** Radius tokens (UI §4.5). */
export const radii = { sm: 4, md: 8, lg: 12, xl: 16, full: 999 } as const;

/** Spacing tokens (UI §4.3): Tailwind's 4 px spacing unit produces every value (p-4 = 16 px). */
export const spacing = [0, 4, 8, 12, 16, 24, 32, 40, 48, 64, 80, 96] as const;

/** Shadow styles (UI §4.5): colour #0D1217 = rgb(13 18 23). */
export const shadows = {
  sm: "0 1px 2px rgb(13 18 23 / 6%)",
  md: "0 4px 12px rgb(13 18 23 / 8%), 0 1px 2px rgb(13 18 23 / 5%)",
  lg: "0 16px 40px rgb(13 18 23 / 16%), 0 4px 8px rgb(13 18 23 / 6%)",
} as const;

/** Fixed sizes (UI §4.4) used as Tailwind spacing names, in px. */
export const sizes = {
  touch: 44, "control-md": 44, "control-lg": 48, sidebar: 264, rail: 72, "auth-brand": 640, "auth-card": 440,
} as const;

export function hexOf(ref: Ref): string {
  const [ramp, step] = ref.split("/") as [Ramp, string];
  const value = (primitives[ramp] as Record<string, string>)[step];
  if (!value) throw new Error(`unknown primitive ${ref}`);
  return value;
}
