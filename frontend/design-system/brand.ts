/**
 * Brand asset paths, in one place. Both files are PLACEHOLDERS (see public/brand/README.md): no final logo or background
 * exists yet. Replace the files at these paths, or change the paths here; components never hard-code them.
 */
export const BRAND = {
  name: "IntelliStudy",
  /** Square mark. Shown next to the visible name, so it is decorative there (alt=""). */
  logoSrc: "/brand/intellistudy-logo.svg",
  /** Auth brand panel background; always drawn under an overlay so text contrast never depends on the image. */
  backgroundSrc: "/images/intellistudy-background.webp",
} as const;
