import type { IconName } from "./placeholders";

/**
 * Icon slot. Until the Figma SVGs are exported (see placeholders.ts) it renders an empty box of the exact size: no
 * glyph is invented. Icons are decorative here (every icon in F0-A sits next to text), so they are hidden from
 * assistive technology.
 */
export function Icon({ name, size, className = "" }: { name: IconName; size: 16 | 18 | 20 | 24 | 28; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-icon-placeholder={name}
      className={`inline-block shrink-0 ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
